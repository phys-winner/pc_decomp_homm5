"""x87 stack to C locals for lifted bodies with a statically known stack depth.

The lifted code keeps the x87 stack in a global window (_st[i], fp_push,
fp_pop, fp_xch: recomp_types.h, RECOMP_X87_WINDOW). Every push and pop moves
the window pointer, writes value and integer shadow, and every _st[i] is a
load through it, so x87 arithmetic is a chain of memory operations.

MSVC code keeps the x87 stack empty at calls, except for the CRT's x87
argument helpers (_ftol, _CIpow, ...), and returns a float in st(0). This tool
computes, per body, the stack depth at every instruction relative to its entry
and the body's x87 interface: c values consumed from its caller's stack and p
values left for it. A body whose depth is consistent, and whose x87 code only
uses the generated forms below, gets one C local per stack slot:

    _st[i]            -> the slot at depth-1-i
    fp_push(v)        -> slot(depth) = v, shadow 0
    fp_push_i64(v)    -> slot(depth) = v with the exact shadow
    fp_pop()          -> slot(depth-1)
    fp_xch(i)         -> swap two slots and their shadows

The global window is touched only at the body's x87 boundaries: consumed
values are popped at entry, results pushed before each return, and around a
call the callee's x87 arguments are pushed and its results popped back. The
arithmetic is the same C on the same doubles, so results are bit-identical to
the window model; only the storage changes.

    python tools/x87_locals.py      # writes build/call-protocol/x87.json
"""
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import call_protocol as cp

X87_JSON = ROOT / 'build/call-protocol/x87.json'

PUSH = {'fld', 'fild', 'fbld', 'fldz', 'fld1', 'fldpi', 'fldl2e', 'fldl2t', 'fldlg2', 'fldln2'}
POP1 = {'fstp', 'fistp', 'fisttp', 'fbstp', 'fcomp', 'fucomp', 'ficomp', 'fcompi', 'fucompi', 'fcomip',
        'fucomip', 'faddp', 'fsubp', 'fsubrp', 'fmulp', 'fdivp', 'fdivrp', 'fpatan', 'fyl2x', 'fyl2xp1'}
POP2 = {'fcompp', 'fucompp'}
ZERO = {'fst', 'fist', 'fcom', 'fucom', 'fcomi', 'fucomi', 'ficom', 'fadd', 'fsub', 'fsubr', 'fmul', 'fdiv',
        'fdivr', 'fiadd', 'fisub', 'fisubr', 'fimul', 'fidiv', 'fidivr', 'fchs', 'fabs', 'fsqrt', 'fsin', 'fcos',
        'frndint', 'fscale', 'f2xm1', 'fxam', 'ftst', 'fxch', 'fldcw', 'fnstcw', 'fstcw', 'fnstsw', 'fstsw',
        'fnclex', 'fclex', 'fwait', 'wait', 'fnop', 'ffree', 'fcmovb', 'fcmove', 'fcmovbe', 'fcmovu',
        'fcmovnb', 'fcmovne', 'fcmovnbe', 'fcmovnu'}
READS_ST1 = {'fcompp', 'fucompp', 'fpatan', 'fyl2x', 'fyl2xp1', 'fscale', 'fprem', 'fprem1'}
# Anything else that names the x87 state: opaque (the body keeps the window).
BARRIER = {'fninit', 'finit', 'fnsave', 'fsave', 'frstor', 'fxsave', 'fxrstor', 'fldenv', 'fnstenv', 'fstenv',
           'fincstp', 'fdecstp', 'ffreep', 'fsincos', 'fxtract', 'fprem', 'fprem1'}
# The window model gives emms no effect (the lifter emits a comment).
NO_X87 = {'emms', 'femms'}
ST_RE = re.compile(r'st\((\d)\)')


def x87_effect(d):
    """(delta, highest st index read) or None for a barrier; (0, -1) for non-x87."""
    m = d.mnemonic.split()[-1]
    if m in BARRIER:
        return None
    if m in NO_X87:
        return 0, -1
    if m == 'fptan':
        return 1, 0                                    # st(0) = tan(st(0)), then push 1.0
    if m in PUSH:
        delta = 1
    elif m in POP1:
        delta = -1
    elif m in POP2:
        delta = -2
    elif m in ZERO:
        delta = 0
    elif m.startswith('f') and m not in ('fs', 'fs:'):
        return None                                    # an x87 form this pass does not know
    else:
        return 0, -1
    reads = [int(k) for k in ST_RE.findall(d.op_str)]
    high = max(reads) if reads else -1
    if m in PUSH:
        # fld st(i) reads st(i) before the push; memory/constant loads read nothing.
        return delta, high
    if m in ('fldcw', 'fnstcw', 'fstcw', 'fnstsw', 'fstsw', 'fnclex', 'fclex', 'fwait', 'wait', 'fnop', 'ffree'):
        return 0, -1
    high = max(high, 0)
    # The operand-less forms work on st(0) and st(1); a memory operand does not.
    if m in READS_ST1 or (m in ('faddp', 'fsubp', 'fsubrp', 'fmulp', 'fdivp', 'fdivrp', 'fxch',
                                'fcom', 'fcomp', 'fucom', 'fucomp') and not d.op_str.strip()):
        high = max(high, 1)
    return delta, high


class Summary:
    __slots__ = ('ok', 'known', 'c', 'p', 'depth', 'calls', 'reason', 'maxdepth', 'delta', 'pending')


EXIT = 'exit'


def call_result(b, i, effects, summaries, limit=256):
    """Whether call i, made at an empty stack to a callee of unknown interface,
    leaves a float, judged from every path after it: 1 if a path reads or pops
    below what it pushed itself, or its next call takes one more x87 argument
    than the path pushed; 0 if the next call takes exactly what was pushed
    (the ABI's stack at a call). EXIT if every path leaves the body undecided
    (call f; ret passes a float through, if f returns one); None if paths
    disagree or the search gives up."""
    if b.exit[i] is not None:
        return 0 if b.exit[i][0] == 'stop' else None
    results, seen, steps = set(), set(), 0
    work = [(t, 0) for t in b.succ[i]]
    while work:
        j, local = work.pop()
        if (j, local) in seen:
            continue
        seen.add((j, local))
        steps += 1
        if steps > limit:
            return None
        c = b.call[j]
        if c is not None:
            callee = summaries.get(c[1]) if c[0] == 'direct' and c[1] else None
            cg = callee.c if callee is not None and callee.ok and callee.known else 0
            if cg == local:
                results.add(0)
            elif cg == local + 1:
                results.add(1)
            else:
                return None
            continue
        delta, high = effects[j]
        if high >= local or local + delta < 0:
            results.add(1)
            continue
        local += delta
        e = b.exit[j]
        if e is not None:
            if e[0] != 'stop':
                results.add(EXIT)
            continue
        for t in b.succ[j]:
            work.append((t, local))
    decided = results - {EXIT}
    if len(decided) > 1:
        return None
    if decided:
        return decided.pop()
    return EXIT if results else 0


def analyse_body(name, b, summaries, assume=0):
    """Depth at every instruction (relative to entry) and the (c, p) interface.
    Calls whose float result only passes through to this body's exits take
    `assume` (0 or 1) for it and set s.pending."""
    s = Summary()
    s.ok, s.known, s.c, s.p, s.depth, s.calls, s.reason, s.maxdepth, s.delta, s.pending = (
        False, True, 0, 0, {}, {}, '', 0, {}, False)
    n = len(b.insns)
    if not n:
        s.reason = 'empty'
        return s
    entry = b.f.addresses.index(b.f.va) if b.f.va in b.f.addresses else 0
    effects = []
    for d in b.insns:
        if d is None:
            effects.append((0, -1))
            continue
        e = x87_effect(d)
        if e is None:
            s.reason = 'barrier ' + d.mnemonic
            return s
        effects.append(e)
    depth = [None] * n
    depth[entry] = 0
    work = [entry]
    need = 0                     # values read from below the entry depth
    net = None
    inferred = False             # a call's interface came from the ABI, not a summary
    while work:
        i = work.pop()
        d0 = depth[i]
        d = b.insns[i]
        delta, high = effects[i]
        c = b.call[i]
        if c is not None:
            target = c[1] if c[0] == 'direct' else None
            summary = summaries.get(target) if target else None
            if summary is not None and summary.ok and summary.known:
                cg, pg = summary.c, summary.p
                if d0 < cg:
                    # Only the CRT's argument helpers take x87 values, and
                    # their callers push them; passing this body's own
                    # arguments through is not an MSVC pattern.
                    s.reason = f'call consumes below entry at {b.f.addresses[i]:08X}'
                    return s
            else:
                # The ABI: nothing on the x87 stack at the call; a float result
                # is read after it, or passes through to the exits.
                if d0 != 0:
                    s.reason = f'call at depth {d0} with unknown x87 interface at {b.f.addresses[i]:08X}'
                    return s
                pg = call_result(b, i, effects, summaries)
                if pg is None:
                    s.reason = f'unknown result at {b.f.addresses[i]:08X}'
                    return s
                if pg == EXIT:
                    pg = assume
                    s.pending = True
                cg = 0
                inferred = True
            after = d0 - cg + pg
            s.calls[b.f.addresses[i]] = (cg, pg)
        else:
            if high >= 0 and d0 - 1 - high < -need:
                need = high + 1 - d0
            after = d0 + delta
            if after < -need:
                need = -after
        e = b.exit[i]
        if e is not None:
            if e[0] == 'ret':
                exit_net = after
            elif e[0] == 'tail':
                # A tail jump hands the stack to its target, which then
                # returns to this body's caller: the body's interface
                # includes the target's. An indirect target (an import thunk's
                # jmp [IAT], a virtual tail) is unknown.
                summary = summaries.get(e[1]) if e[1] else None
                if summary is None or not summary.ok or not summary.known:
                    s.reason = f'tail with unknown x87 interface at {b.f.addresses[i]:08X}'
                    return s
                if after != 0 or summary.c:
                    # The rewrite spills nothing before a tail.
                    s.reason = f'tail at depth {after}'
                    return s
                exit_net = summary.p
            else:
                exit_net = None
            if exit_net is not None:
                if net is None:
                    net = exit_net
                elif net != exit_net:
                    s.reason = 'inconsistent return depth'
                    return s
        for t in b.succ[i]:
            if depth[t] is None:
                depth[t] = after
                work.append(t)
            elif depth[t] != after:
                s.reason = f'depth conflict at {b.f.addresses[t]:08X}'
                return s
        s.maxdepth = max(s.maxdepth, after, d0)
    if need and inferred:
        # A float result the ABI guess missed looks exactly like a value taken
        # from the caller: the guess cannot be trusted here.
        s.reason = 'consumes below entry with an inferred call'
        return s
    s.c = need
    s.p = (net if net is not None else 0) + need
    if s.p < 0 or s.p > 2 or s.c > 3 or (s.pending and (s.c or s.p > 1)):
        s.reason = f'unusual interface c={s.c} p={s.p}'
        return s
    s.depth = {b.f.addresses[i]: depth[i] for i in range(n) if depth[i] is not None}
    s.delta = {f'{b.f.addresses[i]:08X}': effects[i][0] for i in range(n)
               if b.call[i] is None and effects[i][0]}
    s.ok = True
    return s


def analyse_full(name, b, summaries):
    """analyse_body, deciding pass-through float results: when only one
    assumption is consistent it is the fact. When both are, nothing after
    such a call reads below what it pushed itself, so the body is rewritten
    assuming no float (a float the callee leaves stays on the global window
    and passes through), but its callers cannot rely on its interface."""
    s0 = analyse_body(name, b, summaries, 0)
    if not s0.pending:
        return s0
    s1 = analyse_body(name, b, summaries, 1)
    if s0.ok and s1.ok:
        s0.known = False
        return s0
    if s1.ok:
        return s1
    return s0


def analyse(out=X87_JSON):
    start = time.time()
    functions, bodies, helpers = cp.prepare(ROOT / 'build/call-protocol')
    summaries = {}
    for round_ in range(40):
        changed = 0
        for name, b in bodies.items():
            s = analyse_full(name, b, summaries)
            old = summaries.get(name)
            if (old is None or old.ok != s.ok or (s.ok and ((old.c, old.p, old.known) != (s.c, s.p, s.known)
                                                              or old.calls != s.calls))):
                changed += 1
            summaries[name] = s
        ok = sum(1 for s in summaries.values() if s.ok)
        print(f'x87 round {round_ + 1}: ok={ok} changed={changed} ({time.time() - start:.1f}s)', flush=True)
        if not changed:
            break
    else:
        raise SystemExit('x87 summaries did not converge')
    # Every rewritten call site must agree with its callee's final interface.
    for name, s in summaries.items():
        if not s.ok:
            continue
        b = bodies[name]
        for i, c in enumerate(b.call):
            if c is None or c[0] != 'direct':
                continue
            callee = summaries.get(c[1])
            if callee is not None and callee.ok and callee.known:
                assert s.calls.get(b.f.addresses[i], (callee.c, callee.p)) == (callee.c, callee.p), (name, c[1])
    reasons = Counter(s.reason.split(' at ')[0].split(' ')[0] for s in summaries.values() if not s.ok)
    print('not ok:', reasons.most_common(12), flush=True)
    interfaces = Counter((s.c, s.p) if s.known else 'unknown' for s in summaries.values() if s.ok)
    print('interfaces:', interfaces.most_common(10), flush=True)
    data = {name: dict(c=s.c, p=s.p, depth={f'{a:08X}': v for a, v in s.depth.items() if v},
                       calls={f'{a:08X}': list(v) for a, v in s.calls.items() if v != (0, 0)},
                       delta=s.delta, **({} if s.known else dict(u=1)))
            for name, s in summaries.items() if s.ok}
    out.write_text(json.dumps(data, separators=(',', ':')) + '\n')
    return summaries


# --- source rewrite ----------------------------------------------------------
class Unsupported(Exception):
    pass


FUNCTION_START = re.compile(rb'^void (sub_[0-9A-F]{8})(?:_lifted)?\(void\) \{\r?$', re.M)
FUNCTION_END = re.compile(rb'\n\}\r?\n')
COMMENT_ADDR = re.compile(rb'/\* 0x([0-9A-F]{8}): ')
LABEL_LINE = re.compile(rb'^L_([0-9A-F]{8}):')
TOKEN = re.compile(rb'fp_push_i64\(|fp_push\(|fp_pop\(\)|fp_xch\(|_st\[(\d+)\]|g_st_i64\[(\d+)\]'
                   rb'|\b(?:g_st|_st|g_st_i64|_fp_top|g_fp_top|g_fp_sp|g_st_win|g_st_i64_win|fp_window_\w+|'
                   rb'void_fpu_remainder|fp_push_impl|fp_pop_impl|h5_fpu_cache\w*)\b')
CALL_START = re.compile(rb'RECOMP_(?:CALL_P|ICALL_P|CALL|ICALL)\(')
SKIP_BODY = (b'RECOMP_EH_ENTER', b'h5_fpu_cache', b'H5_FPU_CACHE', b'void_fpu_remainder')


def slot(n):
    return b'_x87s%d' % n if n >= 0 else b'_x87m%d' % -n


def islot(n):
    return b'_x87i%d' % n if n >= 0 else b'_x87im%d' % -n


def matching(text, start):
    """Index just past the parenthesis that closes the one before `start`."""
    depth, i = 1, start
    while i < len(text):
        c = text[i]
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if not depth:
                return i + 1
        i += 1
    raise Unsupported('unbalanced')


class Rewriter:
    def __init__(self, low):
        self.low = low          # lowest slot index that exists (-c)
        self.used = set()

    def use(self, n):
        if n < self.low:
            raise Unsupported('slot below the consumed values')
        self.used.add(n)
        return n

    def code(self, text, depth, allow_stack=True):
        out, pos = [], 0
        while True:
            m = TOKEN.search(text, pos)
            if not m:
                break
            out.append(text[pos:m.start()])
            tok = m.group(0)
            if tok in (b'fp_push(', b'fp_push_i64('):
                if not allow_stack:
                    raise Unsupported('push inside an operand')
                end = matching(text, m.end())
                inner, _ = self.code(text[m.end():end - 1], depth, allow_stack=False)
                n = self.use(depth)
                macro = b'X87_SET' if tok == b'fp_push(' else b'X87_SET_I64'
                out.append(b'%s(%s, %s, (%s))' % (macro, slot(n), islot(n), inner))
                depth += 1
                pos = end
            elif tok == b'fp_pop()':
                if not allow_stack:
                    raise Unsupported('pop inside an operand')
                n = self.use(depth - 1)
                out.append(slot(n))
                depth -= 1
                pos = m.end()
            elif tok == b'fp_xch(':
                end = matching(text, m.end())
                k = int(text[m.end():end - 1])
                a, b = self.use(depth - 1), self.use(depth - 1 - k)
                out.append(b'X87_XCH(%s, %s, %s, %s)' % (slot(a), islot(a), slot(b), islot(b)))
                pos = end
            elif m.group(1) is not None:
                out.append(slot(self.use(depth - 1 - int(m.group(1)))))
                pos = m.end()
            elif m.group(2) is not None:
                out.append(islot(self.use(depth - 1 - int(m.group(2)))))
                pos = m.end()
            else:
                raise Unsupported('global x87 state: ' + tok.decode())
        out.append(text[pos:])
        return b''.join(out), depth


def transform_function(name, body, info):
    """Rewrite one body; raise Unsupported to leave it on the window."""
    if any(marker in body for marker in SKIP_BODY):
        raise Unsupported('excluded body')
    if not TOKEN.search(body) and not info.get('calls'):
        return None
    c, p = info['c'], info['p']
    depths = {int(a, 16): v for a, v in info.get('depth', {}).items()}
    calls = {int(a, 16): tuple(v) for a, v in info.get('calls', {}).items()}
    net = p - c
    if (c or p) and (b'RECOMP_TAIL_P' in body or b'RECOMP_ITAIL' in body or b'RECOMP_RET_JUMP' in body):
        raise Unsupported('x87 interface with a tail exit')
    rw = Rewriter(-c)
    lines = body.split(b'\n')
    out = []
    depth = 0
    entered = False
    deltas = {int(a, 16): v for a, v in info.get('delta', {}).items()}
    current, start_depth = None, 0
    for line in lines:
        cm = COMMENT_ADDR.search(line)
        lm = LABEL_LINE.match(line)
        if cm or lm:
            # The text of the previous instruction must move the stack exactly
            # as its decoded instruction does.
            if current is not None and current not in calls and depth - start_depth != deltas.get(current, 0):
                raise Unsupported('instruction text and stack effect differ')
            current = None
        if lm:
            depth = depths.get(int(lm.group(1), 16), 0)
        if cm:
            address = int(cm.group(1), 16)
            depth = depths.get(address, 0)
            current, start_depth = address, depth
        else:
            address = None
        cut = line.find(b'/*')
        code, tail = (line, b'') if cut < 0 else (line[:cut], line[cut:])
        call = CALL_START.search(code)
        if call and address in calls:
            cg, pg = calls[address]
            pre, depth = rw.code(code[:call.start()], depth)
            before = depth
            end = matching(code, call.end())
            # The call statement ends with ';' right after its parenthesis.
            stmt_end = end + 1 if code[end:end + 1] == b';' else end
            spill = b''.join(b'X87_GPUSH(%s, %s); ' % (slot(rw.use(k)), islot(k))
                             for k in range(before - cg, before))
            fill = b''.join(b' X87_GPOP(%s, %s);' % (slot(rw.use(k)), islot(k))
                            for k in range(before - cg + pg - 1, before - cg - 1, -1))
            code = pre + spill + code[call.start():stmt_end] + fill + code[stmt_end:]
            depth = before - cg + pg
        else:
            code, depth = rw.code(code, depth)
        line = code + tail
        if b'return;' in line and cm is not None and b': ret' in tail:
            if depth != net:
                raise Unsupported('return depth')
            push = b''.join(b'X87_GPUSH(%s, %s); ' % (slot(rw.use(k)), islot(k)) for k in range(-c, net))
            push += b'X87_CHECK_EXIT(0x%08Xu, %d, %d, %d); ' % (int(name[4:], 16), c, p, int(info.get('u', 0)))
            indent = len(line) - len(line.lstrip())
            line = line[:indent] + push + line[indent:]
        out.append(line)
        if not entered and b'RECOMP_ENTER(' in line:
            entered = True
            pops = b''.join(b'X87_GPOP(%s, %s); ' % (slot(rw.use(k)), islot(k)) for k in range(-1, -c - 1, -1))
            out.append(b'    X87_CHECK_ENTER(); ' + pops)
    if not rw.used:
        return None
    names = sorted(rw.used)
    declare = (b'    double ' + b', '.join(slot(n) + b' = 0' for n in names) + b';' +
               b' int64_t ' + b', '.join(islot(n) + b' = 0' for n in names) + b';')
    text = b'\n'.join(out)
    marker = b'RECOMP_REGS_LOCALS'
    at = text.find(marker)
    if at < 0:
        raise Unsupported('no locals marker')
    at = text.find(b'\n', at)
    return text[:at + 1] + declare + b'\r' * (b'\r\n' in text) + b'\n' + text[at + 1:]


class Plan:
    def __init__(self, path=X87_JSON):
        self.info = json.loads(Path(path).read_text())
        self.stats = Counter()


def apply_x87(text, plan):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            continue
        name = match[1].decode()
        body = text[match.end():end.end()]
        info = plan.info.get(name)
        new = None
        if info is not None:
            try:
                new = transform_function(name, body, info)
                plan.stats['rewritten' if new is not None else 'no x87'] += 1
            except Unsupported as error:
                plan.stats['kept: ' + str(error).split(':')[0]] += 1
                new = None
        else:
            plan.stats['no summary'] += 1
        parts += [text[pos:match.end()], new if new is not None else body]
        pos = end.end()
    return b''.join(parts + [text[pos:]]) if parts else text


if __name__ == '__main__':
    analyse()
