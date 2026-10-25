"""Apply the whole-program call-boundary summary (tools/call_protocol.py) to
generated bodies: masked register publication at calls, tails and exits, and
flags only where a reader exists. See recomp_types.h, "Masked call protocol".

The summary is produced from the canonical generated sources; this pass only
rewrites statements whose shape it recognises and leaves anything else on the
full protocol (RECOMP_CALL / RECOMP_ICALL / RECOMP_ITAIL + all registers).
It runs after the other source passes, so their regions keep their pins.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / 'build/call-protocol/summary.json'

ABI4 = 0x01 | 0x02 | 0x04 | 0x10        # eax ecx edx esp
ALL = 0xFF

FUNCTION_START = re.compile(rb'^void (sub_[0-9A-F]{8})(?:_lifted)?\(void\) \{\r?$', re.M)
FUNCTION_END = re.compile(rb'\n\}\r?\n')
CALL = re.compile(rb'RECOMP_CALL\((sub_[0-9A-F]{8})\);')
SITE = re.compile(rb'[^\r\n]*?/\* 0x([0-9A-F]{8}): ')
ICALL_OPEN = b'RECOMP_ICALL('
ICALL_SITE = re.compile(rb'\); (?:RECOMP_FLAGS_IN\(\); goto L_[0-9A-F]{8}; )?/\* 0x([0-9A-F]{8}): ')
RET_FLAGS = re.compile(rb'RECOMP_FLAGS_OUT\(\); (esp \+= \d+; \{ (?:RECOMP_EH_LEAVE\(\); )?RECOMP_REGS_OUT\(\); return; \})')
TAIL_CONST = re.compile(rb'RECOMP_ITAIL\(0x([0-9A-F]{8})u\); \{ ((?:RECOMP_EH_LEAVE\(\); )?)RECOMP_REGS_OUT\(\); return; \}')
TAIL_SWITCH = re.compile(rb'RECOMP_ITAIL\(_itail_tgt\); \{ ((?:RECOMP_EH_LEAVE\(\); )?)RECOMP_REGS_OUT\(\); return; \}')
EXIT = re.compile(rb'RECOMP_REGS_OUT\(\);( return;|\r?\n\}\r?\n$)')


class Protocol:
    def __init__(self, path=SUMMARY, full=()):
        data = json.loads(Path(path).read_text())
        self.flags_in = set(data['flags_in'])
        self.flags_out = set(data['flags_out'])
        self.regs = {name: tuple(masks) for name, masks in data['regs'].items()}
        self.problem_sites = {int(p['address'], 16) for p in data['problems']}
        self.unknown_tail_flags = set(data.get('flags_out_unknown_tail', ()))
        self.known = set(data['names'])
        # Bodies the host replaces keep the full protocol on both sides.
        self.full = set(full)
        self._declared = {}

    def declared(self, module):
        """Names the module's own header declares (direct tails stay in-module)."""
        if module not in self._declared:
            header = ROOT / f'generated/{module}-x86/{module}_funcs.h'
            self._declared[module] = set(re.findall(r'^void (sub_[0-9A-F]{8})\(void\);', header.read_text(), re.M))
        return self._declared[module]

    def cs(self, name):
        return self.regs.get(name, (0, 0))

    def call_masks(self, callee):
        if callee in self.full or callee not in self.known:
            return ALL, ALL, 1
        cs_in, cs_out = self.cs(callee)
        return ABI4 | cs_in | cs_out, ABI4 | cs_out, int(callee in self.flags_in)

    def exit_mask(self, name):
        if name in self.full or name not in self.known:
            return ALL
        return ABI4 | self.cs(name)[1]


def rewrite_icalls(body, proto):
    out, pos = [], 0
    while True:
        at = body.find(ICALL_OPEN, pos)
        if at < 0:
            break
        depth, i = 1, at + len(ICALL_OPEN)
        while i < len(body) and depth:
            c = body[i]
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
            elif c == 0x0A:
                break
            i += 1
        if depth:
            out.append(body[pos:at + len(ICALL_OPEN)])
            pos = at + len(ICALL_OPEN)
            continue
        expr = body[at + len(ICALL_OPEN):i - 1]
        site = ICALL_SITE.match(body, i - 1)
        if not site or int(site[1], 16) in proto.problem_sites:
            out.append(body[pos:i])
        else:
            out += [body[pos:at], b'RECOMP_ICALL_P(%s, 0x%02Xu, 0x%02Xu, 0, 0x%su)' % (expr, ABI4, ABI4, site[1])]
        pos = i
    out.append(body[pos:])
    return b''.join(out)


def transform_body(name, body, proto, module):
    """Rewrite one function body (the text after its opening line)."""
    exit_mask = proto.exit_mask(name)
    full_body = exit_mask == ALL
    keep_flags = full_body or name in proto.flags_out

    def call(match):
        pub, rel, fl = proto.call_masks(match[1].decode())
        site = SITE.match(body, match.end())
        return b'RECOMP_CALL_P(%s, 0x%02Xu, 0x%02Xu, %d, 0x%su);' % (
            match[1], pub, rel, fl, site[1] if site else b'0')

    def tail_const(match):
        target = 'sub_' + match[1].decode()
        if target not in proto.known or target in proto.full or target not in proto.declared(module):
            return match[0]
        pub, _, fl = proto.call_masks(target)
        return b'RECOMP_TAIL_P(%s, 0x%02Xu, %d); { %sreturn; }' % (
            target.encode(), pub | exit_mask, fl, match[2])

    def tail_switch(match):
        if keep_flags:
            return match[0]
        return b'RECOMP_ITAIL_P(_itail_tgt, 0x%02Xu, 0); { %sreturn; }' % (ABI4 | exit_mask, match[1])

    body = CALL.sub(call, body)
    body = rewrite_icalls(body, proto)
    if not keep_flags:
        body = RET_FLAGS.sub(lambda m: m[1], body)
    if not full_body:
        body = TAIL_CONST.sub(tail_const, body)
        body = TAIL_SWITCH.sub(tail_switch, body)
        body = EXIT.sub(lambda m: b'RECOMP_EXIT_P(0x%02Xu);%s' % (exit_mask, m[1]), body)
    return body


def apply_protocol(text, proto, module):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            continue
        name = match[1].decode()
        parts += [text[pos:match.end()], transform_body(name, text[match.end():end.end()], proto, module)]
        pos = end.end()
    return b''.join(parts + [text[pos:]]) if parts else text
