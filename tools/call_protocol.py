"""Whole-program call-boundary analysis for the lifted guest code.

Every lifted body publishes the lazy flags (RECOMP_FLAGS_OUT) before each call
and before each `ret`, and every call writes back and reloads all eight guest
registers. Most of that traffic carries values nobody reads. This tool reads
the generated bodies, re-decodes their x86 instructions from the lifted images
and computes, over the whole program:

  flags   which functions may read the flags they were entered with
          (flags_in) and which must publish their exit flags because a caller
          reads them after the call (flags_out);
  regs    per function, the guest registers it may read on entry (reg_in) and
          the ones whose exit value may differ from the entry value (reg_out),
          treating MSVC callee-saved spills (push in the prologue, pop before
          every ret) as transparent.

Indirect calls and tail calls through unknown targets follow the MSVC ABI
(eax/ecx/edx/esp in and out, flags dead across calls); call sites that would
need more are reported as `problems` and keep the full protocol.

    python tools/call_protocol.py [--out build/call-protocol/summary.json]
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import re
import time

import capstone
from capstone import x86_const as X

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'config/modules.json').read_text())

FUNC_RE = re.compile(rb'^void (sub_([0-9A-F]{8}))\(void\) \{\r?$', re.M)
END_RE = re.compile(rb'\n\}\r?\n')
# The disassembly text may contain '*' (scaled index: [edx + ecx*4]).
INSN_RE = re.compile(rb'/\* 0x([0-9A-F]{8}): ([^\r\n]*?) \*/')
CALL_LINE_RE = re.compile(rb'RECOMP_CALL\((sub_[0-9A-F]{8}|recomp_\w+)\);')
LABEL_RE = re.compile(rb'^L_([0-9A-F]{8}):', re.M)

# --- registers ------------------------------------------------------------
REGS = ('eax', 'ecx', 'edx', 'ebx', 'esp', 'ebp', 'esi', 'edi')
BIT = {name: 1 << i for i, name in enumerate(REGS)}
ALL = (1 << len(REGS)) - 1
VOLATILE = BIT['eax'] | BIT['ecx'] | BIT['edx']
CALLEE_SAVED = BIT['ebx'] | BIT['esi'] | BIT['edi'] | BIT['ebp']
ABI_IN = VOLATILE | BIT['esp']
ABI_OUT = VOLATILE | BIT['esp']

_FULL = {}
_SUB = {}
for _full, _parts in (('eax', ('eax', 'ax', 'al', 'ah')), ('ecx', ('ecx', 'cx', 'cl', 'ch')),
                      ('edx', ('edx', 'dx', 'dl', 'dh')), ('ebx', ('ebx', 'bx', 'bl', 'bh')),
                      ('esp', ('esp', 'sp', 'spl')), ('ebp', ('ebp', 'bp', 'bpl')),
                      ('esi', ('esi', 'si', 'sil')), ('edi', ('edi', 'di', 'dil'))):
    for _part in _parts:
        _FULL[_part] = _full
        _SUB[_part] = _part != _full


# --- flags ----------------------------------------------------------------
def _bits(*names):
    value = 0
    for name in names:
        value |= getattr(X, 'X86_EFLAGS_' + name, 0)
    return value


STATUS = ('CF', 'ZF', 'SF', 'OF', 'PF', 'AF')
TEST_ANY = _bits(*('TEST_' + f for f in STATUS))
DEF_BITS = {f: _bits('MODIFY_' + f, 'RESET_' + f, 'SET_' + f, 'UNDEFINED_' + f) for f in STATUS}
FLAG_READERS = {'pushf', 'pushfd', 'lahf', 'into'}
FLAG_WRITERS = {'popf', 'popfd'}
SHIFTS = {'shl', 'shr', 'sar', 'sal', 'rol', 'ror', 'rcl', 'rcr', 'shld', 'shrd'}


# Flag effects by mnemonic, in the two units of the lifter's lazy flags:
# L = _flag_k/_flag_a/_flag_b (ZF SF OF PF AF) and C = _cf. capstone's
# eflags table is incomplete (nothing for `test byte ptr [m], r8`), so this
# table is explicit. A CF reader may derive CF from L lazily, so it reads both.
FL_L, FL_C, FL_BOTH = 1, 2, 3
L_READERS = {'je', 'jne', 'jz', 'jnz', 'js', 'jns', 'jo', 'jno', 'jp', 'jnp', 'jpe', 'jpo',
             'jl', 'jnge', 'jge', 'jnl', 'jle', 'jng', 'jg', 'jnle', 'loope', 'loopne', 'loopz', 'loopnz'}
C_READERS = {'jb', 'jc', 'jnae', 'jae', 'jnb', 'jnc', 'jbe', 'jna', 'ja', 'jnbe',
             'adc', 'sbb', 'rcl', 'rcr', 'cmc', 'salc', 'daa', 'das', 'aaa', 'aas',
             'pushf', 'pushfd', 'pushfw', 'lahf', 'into'}
CC_L = {'e', 'ne', 'z', 'nz', 's', 'ns', 'o', 'no', 'p', 'np', 'pe', 'po', 'l', 'nge', 'ge', 'nl', 'le', 'ng', 'g', 'nle'}
FULL_KILL = {'add', 'sub', 'cmp', 'and', 'or', 'xor', 'test', 'neg', 'adc', 'sbb', 'cmpxchg', 'xadd',
             'imul', 'mul', 'div', 'idiv', 'bsf', 'bsr', 'popf', 'popfd', 'popfw', 'comisd', 'ucomisd',
             'comiss', 'ucomiss', 'fcomi', 'fcomip', 'fucomi', 'fucomip', 'ptest', 'lzcnt', 'tzcnt',
             'popcnt', 'andn', 'blsi', 'blsr', 'blsmsk', 'bextr'}
L_KILL = {'inc', 'dec'}
C_KILL = {'bt', 'bts', 'btr', 'btc', 'clc', 'stc', 'cmc', 'sahf'}
COUNT_KILL = {'shl', 'sal', 'shr', 'sar', 'shld', 'shrd'}
ROTATE = {'rol', 'ror', 'rcl', 'rcr'}
STRING_KILL = {'cmpsb', 'cmpsw', 'cmpsd', 'scasb', 'scasw', 'scasd'}


def flag_effect(m, insn, ops):
    if m in L_READERS:
        use = FL_L
    elif m in C_READERS:
        use = FL_BOTH
    elif m.startswith(('set', 'cmov', 'fcmov')):
        cc = m[3:] if m.startswith('set') else m[4:] if m.startswith('cmov') else m[5:]
        use = FL_L if cc in CC_L else FL_BOTH
    elif m.startswith('j') and m not in ('jmp', 'jecxz', 'jcxz'):
        use = FL_BOTH
    else:
        use = 0
    if m in FULL_KILL:
        kill = FL_BOTH
    elif m in L_KILL:
        kill = FL_L
    elif m in C_KILL:
        kill = FL_C
    elif m in COUNT_KILL:
        kill = FL_BOTH if ops and ops[-1].type == X.X86_OP_IMM and (ops[-1].imm & 31) != 0 else 0
    elif m in ROTATE:
        kill = FL_C if ops and ops[-1].type == X.X86_OP_IMM and (ops[-1].imm & 31) != 0 else 0
    elif m in STRING_KILL:
        # SSE cmpsd takes xmm operands; a rep-prefixed string compare may run 0 times.
        sse = any(op.type == X.X86_OP_REG and insn.reg_name(op.reg).startswith('xmm') for op in ops)
        kill = FL_BOTH if not sse and not any(prefix in (0xF2, 0xF3) for prefix in insn.prefix) else 0
    else:
        kill = 0
    return use, kill


class Decoded:
    __slots__ = ('address', 'size', 'mnemonic', 'op_str', 'kind', 'target', 'reads', 'writes',
                 'partial', 'flag_use', 'flag_kill', 'imm', 'push_reg', 'pop_reg', 'table')


def classify(insn):
    d = Decoded()
    d.address, d.size, d.mnemonic, d.op_str = insn.address, insn.size, insn.mnemonic, insn.op_str
    m = insn.mnemonic.split()[-1]
    d.kind, d.target, d.imm = 'op', None, 0
    ops = insn.operands
    if m == 'call':
        d.kind = 'call' if ops and ops[0].type == X.X86_OP_IMM else 'icall'
        d.target = ops[0].imm & 0xFFFFFFFF if d.kind == 'call' else None
    elif m in ('ret', 'retn'):
        d.kind = 'ret'
        d.imm = ops[0].imm if ops and ops[0].type == X.X86_OP_IMM else 0
    elif m == 'jmp':
        d.kind = 'jmp' if ops and ops[0].type == X.X86_OP_IMM else 'ijmp'
        d.target = ops[0].imm & 0xFFFFFFFF if d.kind == 'jmp' else None
    elif insn.group(X.X86_GRP_JUMP):
        d.kind = 'jcc'
        d.target = ops[0].imm & 0xFFFFFFFF if ops and ops[0].type == X.X86_OP_IMM else None
    elif m in ('int3', 'hlt', 'ud2'):
        d.kind = 'stop'
    if m == 'push' and ops and ops[0].type == X.X86_OP_IMM:
        d.imm = ops[0].imm & 0xFFFFFFFF
    # jmp [index*4 + table] (no base): a switch over a table of local targets;
    # 0 for every other indirect jump (a tail call through a pointer or vtable).
    d.table = 0
    if d.kind == 'ijmp' and ops and ops[0].type == X.X86_OP_MEM and ops[0].mem.index != 0 \
            and ops[0].mem.scale == 4 and ops[0].mem.base == 0:
        d.table = ops[0].mem.disp & 0xFFFFFFFF
    elif d.kind == 'ijmp' and ops and ops[0].type == X.X86_OP_REG:
        d.table = 1          # jmp reg: targets unknown, may be local
    try:
        read, written = insn.regs_access()
    except capstone.CsError:
        read, written = [], []
    reads = writes = partial = 0
    for reg in read:
        name = insn.reg_name(reg)
        if name in _FULL:
            reads |= BIT[_FULL[name]]
    for reg in written:
        name = insn.reg_name(reg)
        if name in _FULL:
            bit = BIT[_FULL[name]]
            writes |= bit
            if _SUB[name]:
                partial |= bit
    # A partial write keeps the rest of the register: it reads it as well.
    reads |= partial
    if m in ('xor', 'sub') and len(ops) == 2 and ops[0].type == ops[1].type == X.X86_OP_REG \
            and ops[0].reg == ops[1].reg:
        name = insn.reg_name(ops[0].reg)
        if name in _FULL and not _SUB[name]:
            reads &= ~BIT[_FULL[name]]
    # Alignment NOPs (lea r, [r] / mov r, r / xchg r, r) touch nothing.
    if len(ops) == 2 and ops[0].type == X.X86_OP_REG and (
            (m == 'lea' and ops[1].type == X.X86_OP_MEM and ops[1].mem.base == ops[0].reg
             and ops[1].mem.index == 0 and ops[1].mem.disp == 0) or
            (m in ('mov', 'xchg') and ops[1].type == X.X86_OP_REG and ops[1].reg == ops[0].reg)):
        reads = writes = partial = 0
    d.reads, d.writes, d.partial = reads, writes, partial
    d.flag_use, d.flag_kill = flag_effect(m, insn, ops)
    d.push_reg = d.pop_reg = None
    if m == 'push' and ops and ops[0].type == X.X86_OP_REG:
        name = insn.reg_name(ops[0].reg)
        if name in _FULL and not _SUB[name]:
            d.push_reg = name
    elif m == 'pop' and ops and ops[0].type == X.X86_OP_REG:
        name = insn.reg_name(ops[0].reg)
        if name in _FULL and not _SUB[name]:
            d.pop_reg = name
    elif m == 'leave':
        d.pop_reg = 'ebp'
    return d


class Image:
    def __init__(self, path):
        import pefile
        pe = pefile.PE(str(path), fast_load=True)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.data = pe.get_memory_mapped_image()
        pe.close()

    def code(self, va, size=16):
        offset = va - self.base
        return self.data[offset:offset + size]


def load_decoded(module, addresses, cache_dir):
    image_path = ROOT / 'generated/input' / module['file']
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()[:16]
    cache = cache_dir / f"decode6-{module['name']}-{digest}.pickle"
    decoded = {}
    if cache.exists():
        for address, row in pickle.loads(cache.read_bytes()).items():
            if row is None:
                decoded[address] = None
                continue
            d = Decoded()
            for slot, value in zip(Decoded.__slots__, row):
                setattr(d, slot, value)
            decoded[address] = d
    missing = sorted(a for a in addresses if a not in decoded)
    if missing:
        image = Image(image_path)
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        for address in missing:
            got = next(md.disasm(image.code(address), address, 1), None)
            decoded[address] = classify(got) if got else None
        rows = {address: None if d is None else tuple(getattr(d, slot) for slot in Decoded.__slots__)
                for address, d in decoded.items()}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps(rows, protocol=pickle.HIGHEST_PROTOCOL))
    return decoded


class Function:
    __slots__ = ('name', 'va', 'module', 'source', 'addresses', 'tags', 'callees', 'eh', 'labels', 'switch_after')

    def __init__(self, name, va, module, source):
        self.name, self.va, self.module, self.source = name, va, module, source
        self.addresses, self.tags, self.callees, self.eh, self.labels = [], [], {}, False, set()
        # generate.py rewrites an intra-body `jmp [table]` into
        # `{ _itail_tgt = ...; goto _ljump; }` and drops its comment: remember
        # the instruction it follows, the jump is decoded after it.
        self.switch_after = set()


def lifted_tag(line):
    """How the lifter emitted the instruction on this line."""
    if b'void_lift_trap(' in line:
        return 'trap'
    if b'RECOMP_CALL(' in line:
        return 'call'
    if b'RECOMP_ICALL(' in line:
        return 'icall'
    if b'RECOMP_ITAIL(' in line or b'RECOMP_RET_JUMP(' in line:
        return 'tail'
    if b'goto _ljump' in line or b'goto *_jt' in line:
        return 'switch'
    if b'return;' in line:
        return 'ret'
    return 'op'


def parse_functions():
    functions = {}
    for module in MANIFEST:
        folder = ROOT / f"generated/{module['name']}-x86"
        for chunk in sorted(folder.glob(module['name'] + '_[0-9][0-9][0-9][0-9].c')):
            text = chunk.read_bytes()
            for match in FUNC_RE.finditer(text):
                end = END_RE.search(text, match.end())
                body = text[match.end():end.end()]
                f = Function(match[1].decode(), int(match[2], 16), module, chunk.name)
                f.eh = b'RECOMP_EH_ENTER()' in body
                f.labels = {int(x, 16) for x in LABEL_RE.findall(body)}
                seen = set()
                last = label = None
                for line in body.split(b'\n'):
                    insn = INSN_RE.search(line)
                    if not insn:
                        at = LABEL_RE.match(line)
                        if at:
                            label = int(at[1], 16)
                        elif b'_itail_tgt = ' in line and b'goto _ljump' in line and (label is not None or last is not None):
                            # (position, address after a label, else the instruction it follows)
                            f.switch_after.add((len(f.addresses), label, last))
                        continue
                    label = None
                    address = int(insn[1], 16)
                    if address in seen:
                        continue
                    seen.add(address)
                    tag = lifted_tag(line)
                    if tag == 'call' and b'; jmp 0x' in insn[2]:
                        tag = 'pushjmp'
                    f.addresses.append(address)
                    f.tags.append(tag)
                    last = address
                    if tag in ('call', 'pushjmp'):
                        callee = CALL_LINE_RE.search(line)
                        if callee:
                            f.callees[address] = callee[1].decode()
                functions[f.name] = f
    return functions


# --- per-function control flow ---------------------------------------------
class Body:
    """Compact CFG of one lifted body: instruction i has successors succ[i]
    (indices) and an exit kind exit[i]: None, ('ret',), ('tail', name|None),
    ('stop',). call[i] is ('direct', name) / ('native',) / None."""
    __slots__ = ('f', 'insns', 'succ', 'exit', 'call')


IMAGES = {}


def image_u32(module, va):
    image = IMAGES.get(module['name'])
    if image is None:
        image = IMAGES[module['name']] = Image(ROOT / 'generated/input' / module['file'])
    offset = va - image.base
    if offset < 0 or offset + 4 > len(image.data):
        return None
    return int.from_bytes(image.data[offset:offset + 4], 'little')


NORETURN_IMPORTS = {'ExitProcess', 'TerminateProcess', 'ExitThread', 'FatalAppExitA', 'FatalAppExitW',
                    'RaiseException', 'abort', 'exit', '_exit', '_amsg_exit', '_CxxThrowException', 'longjmp',
                    '_cexit', '__report_gsfailure', 'FatalExit'}
IAT_NAMES = {}


def iat_names():
    """IAT slot VA -> imported function name, for every module."""
    if not IAT_NAMES:
        import pefile
        for module in MANIFEST:
            pe = pefile.PE(str(ROOT / 'generated/input' / module['file']), fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []) or []:
                for imp in entry.imports:
                    if imp.name:
                        IAT_NAMES[imp.address] = imp.name.decode(errors='replace')
            pe.close()
        IAT_NAMES[0] = ''
    return IAT_NAMES


def noreturn_icall(d):
    """`call dword ptr [IAT]` to an import that never returns."""
    if d is None or d.kind != 'icall' or not d.op_str.startswith('dword ptr [0x'):
        return False
    try:
        slot = int(d.op_str[len('dword ptr ['):-1], 16)
    except ValueError:
        return False
    return iat_names().get(slot, '') in NORETURN_IMPORTS


def build_body(f, decoded, names):
    b = Body()
    b.f = f
    n = len(f.addresses)
    index = {a: i for i, a in enumerate(f.addresses)}
    insns = [decoded.get(a) for a in f.addresses]
    succ, exits, calls = [[] for _ in range(n)], [None] * n, [None] * n
    leaders = sorted(index[a] for a in f.labels if a in index)

    def flow(i, address):
        if address in index:
            succ[i].append(index[address])
        elif exits[i] is None:
            exits[i] = ('tail', names.get(address))
        else:
            exits[i] = ('tail', None)

    for i, d in enumerate(insns):
        tag = f.tags[i]
        if d is None or tag == 'trap':
            exits[i] = ('stop',)
            continue
        nxt = d.address + d.size
        if tag == 'pushjmp':
            # push label; jmp func: a call returning to the pushed label.
            calls[i] = ('direct', f.callees.get(d.address))
            flow(i, d.imm)
            continue
        if d.kind == 'ret':
            exits[i] = ('ret',)
        elif d.kind == 'stop':
            exits[i] = ('stop',)
        elif d.kind == 'jmp':
            flow(i, d.target)
        elif d.kind == 'ijmp':
            if d.table == 1:
                succ[i].extend(leaders)
            elif d.table:
                # The same table walk direct_jump_tables uses: entries while
                # they stay inside this body. The index is range-checked
                # before the jump, so a resolved table never leaves the body.
                for k in range(1024):
                    target = image_u32(f.module, d.table + 4 * k)
                    if target is None or target not in index:
                        break
                    succ[i].append(index[target])
                if succ[i]:
                    continue
            exits[i] = ('tail', None)
        elif d.kind == 'jcc':
            if d.target is not None:
                flow(i, d.target)
            flow(i, nxt)
        elif d.kind in ('call', 'icall'):
            if tag == 'tail':
                exits[i] = ('tail', None)          # call_pop: hands its caller over
                continue
            calls[i] = ('direct', f.callees.get(d.address)) if tag == 'call' else ('native',)
            if tag != 'call' and noreturn_icall(d):
                exits[i] = ('stop',)
                continue
            flow(i, nxt)
        else:
            if tag == 'tail':
                exits[i] = ('tail', None)
                continue
            flow(i, nxt)
    b.insns, b.succ, b.exit, b.call = insns, succ, exits, calls
    assert all(0 <= s_ < n for row in succ for s_ in row), f.name
    return b


# --- flags ------------------------------------------------------------------
def flags_liveness(b, flags_in, need_out):
    """Per-instruction live-in mask of the two flag units."""
    n = len(b.insns)
    live_in = [0] * n
    dirty = True
    while dirty:
        dirty = False
        for i in range(n - 1, -1, -1):
            out = 0
            for s in b.succ[i]:
                out |= live_in[s]
            e = b.exit[i]
            if e is not None:
                if e[0] == 'ret':
                    out |= FL_BOTH if need_out else 0
                elif e[0] == 'tail' and e[1] is not None and e[1] in flags_in:
                    out |= FL_BOTH
            c = b.call[i]
            d = b.insns[i]
            if c is not None:
                value = FL_BOTH if c[0] == 'direct' and c[1] in flags_in else 0
            elif d is None:
                value = 0
            else:
                value = d.flag_use | (out & ~d.flag_kill)
            if value != live_in[i]:
                live_in[i] = value
                dirty = True
    return live_in


FLAG_ROOTS = {}


def flags_pass(bodies, flags_in, flags_out, problems):
    """One whole-program pass; returns True when a set grew."""
    changed = False
    for name, b in bodies.items():
        need_out = name in flags_out
        live_in = flags_liveness(b, flags_in, need_out)
        for i, c in enumerate(b.call):
            if c is None or not any(live_in[s] for s in b.succ[i]):
                continue
            if c[0] == 'direct' and c[1]:
                if c[1] not in flags_out:
                    flags_out.add(c[1])
                    FLAG_ROOTS.setdefault(c[1], (name, f'{b.f.addresses[i]:08X}'))
                    changed = True
            else:
                problems.setdefault((name, b.f.addresses[i]), 'flags live after native/indirect call')
        if need_out:
            for e in b.exit:
                if e is not None and e[0] == 'tail' and e[1] is not None and e[1] not in flags_out:
                    flags_out.add(e[1])
                    changed = True
        entry = b.f.addresses.index(b.f.va) if b.f.va in b.f.addresses else 0
        if live_in and live_in[entry] and name not in flags_in:
            flags_in.add(name)
            changed = True
    return changed


# --- callee-saved registers ---------------------------------------------------
# Volatile registers (eax/ecx/edx) and esp always cross every call and exit,
# so their entry values are always current. Only ebx/esi/edi/ebp need a
# summary: cs_in, the ones a body (or a callee through it) may read on entry,
# and cs_out, the ones whose exit value may differ from the entry value.
#
# A forward pass tracks each callee-saved register as E (holds its entry
# value), S (entry value saved on the stack; the register may be reused) or
# X (changed without a save). push r takes E to S, pop r (or leave for ebp)
# takes S back to E; any other write leaves S alone and turns E into X. An
# exit where some register is not E puts it in cs_out. The MSVC SEH/EH frame
# helpers save and restore on their caller's behalf and are modelled as such.
CS_REGS = ('ebx', 'esi', 'edi', 'ebp')
CS_BITS = tuple(BIT[r] for r in CS_REGS)
CS = CALLEE_SAVED
ABI4 = ABI_IN
ST_NONE, ST_E, ST_S, ST_X = 0, 1, 2, 3
HELPER_SUMMARY = {
    # cs_in, cs_out, must_def
    'seh_prolog': (0, BIT['ebp'], BIT['ebp']),
    'seh_epilog': (BIT['ebp'], CS, CS),
    'eh_prolog': (0, BIT['ebp'], BIT['ebp']),
}


def helper_kind(b):
    """Recognise the MSVC frame helpers by their instructions."""
    text = [(d.mnemonic, d.op_str) for d in b.insns if d is not None]
    ops = set(text)
    if ('mov', 'dword ptr [esp + 0x10], ebp') in ops and ('lea', 'ebp, [esp + 0x10]') in ops \
            and ('push', 'ebx') in ops and ('push', 'esi') in ops and ('push', 'edi') in ops \
            and not any(m == 'pop' for m, _ in text):
        return 'seh_prolog'
    if len(text) <= 12 and ('mov', 'ecx, dword ptr [ebp - 0x10]') in ops and ('leave', '') in ops \
            and ('pop', 'edi') in ops and ('pop', 'esi') in ops and ('pop', 'ebx') in ops:
        return 'seh_epilog'
    if len(text) <= 12 and ('mov', 'dword ptr [esp + 0xc], ebp') in ops and ('lea', 'ebp, [esp + 0xc]') in ops \
            and ('push', '-1') in ops:
        return 'eh_prolog'
    return None


def _merge(a, b):
    if a == b or b == ST_NONE:
        return a
    if a == ST_NONE:
        return b
    return ST_X


def cs_states(b, entry, cs_out, helpers, bodies):
    """Forward E/S/X states (tuple per register) at each instruction entry."""
    n = len(b.insns)
    state = [None] * n
    state[entry] = (ST_E,) * 4
    work = [entry]
    while work:
        i = work.pop()
        cur = list(state[i])
        d = b.insns[i]
        c = b.call[i]
        if c is not None and c[0] == 'direct':
            kind = helpers.get(c[1])
            if kind in ('seh_prolog', 'eh_prolog'):
                regs = CS if kind == 'seh_prolog' else BIT['ebp']
                for k, bit in enumerate(CS_BITS):
                    if regs & bit and cur[k] == ST_E:
                        cur[k] = ST_S
            elif kind == 'seh_epilog':
                for k in range(4):
                    cur[k] = ST_E if cur[k] == ST_S else ST_X
            else:
                out = cs_out.get(c[1], 0) if c[1] in bodies else CS
                for k, bit in enumerate(CS_BITS):
                    if out & bit and cur[k] == ST_E:
                        cur[k] = ST_X
        elif d is not None and c is None:
            for k, reg in enumerate(CS_REGS):
                bit = CS_BITS[k]
                if d.push_reg == reg:
                    if cur[k] == ST_E:
                        cur[k] = ST_S
                elif d.pop_reg == reg:
                    cur[k] = ST_E if cur[k] == ST_S else ST_X
                elif d.writes & bit:
                    if cur[k] == ST_E:
                        cur[k] = ST_X
        new = tuple(cur)
        for s_ in b.succ[i]:
            old = state[s_]
            merged = new if old is None else tuple(_merge(x, y) for x, y in zip(old, new))
            if merged != old:
                state[s_] = merged
                work.append(s_)
    return state


def module_entries():
    """Export and entry-point VAs of every module: reachable from outside."""
    import pefile
    entries = set()
    for module in MANIFEST:
        pe = pefile.PE(str(ROOT / 'generated/input' / module['file']), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
        base = pe.OPTIONAL_HEADER.ImageBase
        entries.add(base + pe.OPTIONAL_HEADER.AddressOfEntryPoint)
        for symbol in getattr(getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', []) or []:
            if symbol.address:
                entries.add(base + symbol.address)
        pe.close()
    return entries


def find_fragments(bodies, helpers):
    """Bodies reached only by direct tail jumps from other bodies: continuations
    of a function the catalog split (second halves, shared epilogues). They are
    analysed as part of every body that jumps into them."""
    called, tailed = set(), set()
    for b in bodies.values():
        for c in b.call:
            if c is not None and c[0] == 'direct' and c[1]:
                called.add(c[1])
        for e in b.exit:
            if e is not None and e[0] == 'tail' and e[1]:
                tailed.add(e[1])
    candidates = {name for name in tailed - called if name not in helpers and bodies[name].insns}
    vas = {bodies[name].f.va for name in candidates}
    taken = address_taken(None, vas) | module_entries()
    return {name for name in candidates if bodies[name].f.va not in taken}


class Graph:
    """A head body plus every fragment reachable from it through direct tail
    jumps, as one CFG. origin[i] = (body name, local index)."""
    __slots__ = ('name', 'insns', 'succ', 'exit', 'call', 'origin', 'entry', 'eh', 'frag_entries')


def build_graph(name, bodies, fragments):
    g = Graph()
    g.name = name
    g.insns, g.succ, g.exit, g.call, g.origin = [], [], [], [], []
    g.frag_entries = {}
    base = {}
    order = [name]
    g.eh = False
    k = 0
    while k < len(order):
        body_name = order[k]
        k += 1
        b = bodies[body_name]
        base[body_name] = len(g.insns)
        g.eh = g.eh or b.f.eh
        for i in range(len(b.insns)):
            g.insns.append(b.insns[i])
            g.succ.append(list(b.succ[i]))
            g.exit.append(b.exit[i])
            g.call.append(b.call[i])
            g.origin.append((body_name, i))
        for e in b.exit:
            if e is not None and e[0] == 'tail' and e[1] in fragments and e[1] not in base and e[1] not in order:
                order.append(e[1])
    for body_name, offset in base.items():
        b = bodies[body_name]
        for i in range(len(b.insns)):
            node = offset + i
            g.succ[node] = [offset + s_ for s_ in b.succ[i]]
            e = b.exit[i]
            if e is not None and e[0] == 'tail' and e[1] in base:
                target = bodies[e[1]]
                entry = target.f.addresses.index(target.f.va) if target.f.va in target.f.addresses else 0
                g.succ[node].append(base[e[1]] + entry)
                g.exit[node] = None
        if body_name != name:
            target = bodies[body_name]
            g.frag_entries[body_name] = base[body_name] + (
                target.f.addresses.index(target.f.va) if target.f.va in target.f.addresses else 0)
    head = bodies[name]
    g.entry = head.f.addresses.index(head.f.va) if head.f.va in head.f.addresses else 0
    return g


def cs_pass(graphs, bodies, cs_in, cs_out, helpers, fragments):
    changed = False
    frag_in, frag_out = defaultdict(int), defaultdict(int)
    for name, g in graphs.items():
        n = len(g.insns)
        if not n:
            continue
        kind = helpers.get(name)
        if kind:
            h_in, h_out, _ = HELPER_SUMMARY[kind]
            if cs_in.get(name) != h_in or cs_out.get(name) != h_out:
                cs_in[name], cs_out[name] = h_in, h_out
                changed = True
            continue
        entry = g.entry
        state = cs_states(g, entry, cs_out, helpers, bodies)
        out = 0
        for i, e in enumerate(g.exit):
            if e is None or e[0] not in ('ret', 'tail') or state[i] is None:
                continue
            for k, bit in enumerate(CS_BITS):
                if state[i][k] in (ST_S, ST_X):
                    out |= bit
            if e[0] == 'tail':
                out |= cs_out.get(e[1], 0) if e[1] is not None and e[1] in bodies else 0
        if g.eh:
            out |= CS     # a caught throw resumes with whatever the runtime set
        out |= cs_out.get(name, 0)
        # Entry liveness: a save (push of an E register) is not a use.
        live = [0] * n
        dirty = True
        while dirty:
            dirty = False
            for i in range(n - 1, -1, -1):
                lo = 0
                for s_ in g.succ[i]:
                    lo |= live[s_]
                e = g.exit[i]
                if e is not None:
                    if e[0] == 'ret':
                        lo |= out
                    elif e[0] == 'tail':
                        lo |= out
                        if e[1] is not None:
                            lo |= (cs_in.get(e[1], 0) | cs_out.get(e[1], 0)) if e[1] in bodies else CS
                c = g.call[i]
                d = g.insns[i]
                if c is not None:
                    if c[0] == 'direct':
                        callee = c[1]
                        kind_c = helpers.get(callee)
                        if kind_c:
                            h_in, h_out, h_must = HELPER_SUMMARY[kind_c]
                            value = (lo & ~h_must) | h_in
                        elif callee in bodies:
                            value = lo | cs_in.get(callee, 0) | cs_out.get(callee, 0)
                        else:
                            value = lo | CS
                    else:
                        value = lo
                    if d is not None:
                        value |= d.reads & CS
                elif d is None:
                    value = 0
                else:
                    st = state[i]
                    uses = d.reads & CS
                    if d.push_reg in CS_REGS and st is not None and st[CS_REGS.index(d.push_reg)] == ST_E:
                        uses &= ~BIT[d.push_reg]
                    value = (lo & ~(d.writes & ~d.partial & CS)) | uses
                if value != live[i]:
                    live[i] = value
                    dirty = True
        new_in = live[entry] | cs_in.get(name, 0)
        if new_in != cs_in.get(name, 0):
            cs_in[name] = new_in
            changed = True
        if out != cs_out.get(name, 0):
            cs_out[name] = out
            changed = True
        for fragment, node in g.frag_entries.items():
            frag_in[fragment] |= live[node]
            frag_out[fragment] |= out
    # A fragment exits on behalf of each head that reaches it: its exit
    # publishes all their outputs, and a head's tail publishes what it reads.
    for fragment in fragments:
        new_in = frag_in[fragment] | cs_in.get(fragment, 0)
        new_out = frag_out[fragment] | cs_out.get(fragment, 0)
        if new_in != cs_in.get(fragment, 0) or new_out != cs_out.get(fragment, 0):
            cs_in[fragment], cs_out[fragment] = new_in, new_out
            changed = True
    return changed


def address_taken(functions, wanted):
    """Function VAs (from `wanted`) stored as aligned dwords in any image:
    vtables, callback tables, pushed or stored addresses."""
    import struct
    found = set()
    for module in MANIFEST:
        image = Image(ROOT / 'generated/input' / module['file'])
        data = image.data
        for (value,) in struct.iter_unpack('<I', data[:len(data) & ~3]):
            if value in wanted:
                found.add(value)
        # Unaligned immediates in code (push offset f / mov [x], offset f).
        for offset in range(1, 4):
            chunk = data[offset:offset + ((len(data) - offset) & ~3)]
            for (value,) in struct.iter_unpack('<I', chunk):
                if value in wanted:
                    found.add(value)
    return found


def prepare(out_dir):
    """Parsed bodies with recovered computed jumps, decoded instructions and CFGs."""
    start = time.time()
    functions = parse_functions()
    print(f'parsed {len(functions)} bodies in {time.time() - start:.1f}s', flush=True)
    by_module = defaultdict(set)
    for f in functions.values():
        by_module[f.module['name']].update(f.addresses)
    decoded = {}
    for module in MANIFEST:
        decoded.update(load_decoded(module, by_module[module['name']], out_dir))
    print(f'decoded {len(decoded)} instructions in {time.time() - start:.1f}s', flush=True)
    # Recover the uncommented computed jumps (see Function.switch_after): the
    # jump sits at the label before it, or right after the instruction it follows.
    def jump_address(entry):
        position, label, last = entry
        if label is not None:
            return label
        d = decoded.get(last)
        return d.address + d.size if d is not None else None
    missing = defaultdict(set)
    for f in functions.values():
        for entry in f.switch_after:
            address = jump_address(entry)
            if address is not None and address not in decoded:
                missing[f.module['name']].add(address)
    for module in MANIFEST:
        if missing[module['name']]:
            decoded.update(load_decoded(module, missing[module['name']] | by_module[module['name']], out_dir))
    switches = 0
    for f in functions.values():
        for entry in sorted(f.switch_after, key=lambda e: -e[0]):
            target = jump_address(entry)
            j = decoded.get(target) if target is not None else None
            if j is None or j.kind != 'ijmp' or target in f.addresses:
                continue
            f.addresses.insert(entry[0], target)
            f.tags.insert(entry[0], 'switch')
            switches += 1
    print(f'recovered {switches} computed jumps', flush=True)
    names = {f.va: f.name for f in functions.values()}
    bodies = {name: build_body(f, decoded, names) for name, f in functions.items()}
    print(f'built bodies in {time.time() - start:.1f}s', flush=True)
    helpers = {name: kind for name, b in bodies.items() for kind in [helper_kind(b)] if kind}
    noreturn = mark_noreturn(bodies)
    print(f'noreturn bodies {len(noreturn)} ({time.time() - start:.1f}s)', flush=True)
    return functions, bodies, helpers


def mark_noreturn(bodies):
    noreturn = set()
    while True:
        grew = False
        for name, b in bodies.items():
            if name in noreturn or not b.insns:
                continue
            entry = b.f.addresses.index(b.f.va) if b.f.va in b.f.addresses else 0
            seen, work, returns = {entry}, [entry], False
            while work and not returns:
                i = work.pop()
                e = b.exit[i]
                c = b.call[i]
                if c is not None and c[0] == 'direct' and c[1] in noreturn:
                    continue
                if e is not None and e[0] in ('ret', 'tail'):
                    returns = True
                    break
                for s_ in b.succ[i]:
                    if s_ not in seen:
                        seen.add(s_)
                        work.append(s_)
            if not returns:
                noreturn.add(name)
                grew = True
        if not grew:
            break
    # Cut the fall-through after calls to them.
    for b in bodies.values():
        for i, c in enumerate(b.call):
            if c is not None and c[0] == 'direct' and c[1] in noreturn:
                b.succ[i] = []
                b.exit[i] = ('stop',)
    return noreturn


def analyze(out_dir):
    start = time.time()
    functions, bodies, helpers = prepare(out_dir)
    flags_in, flags_out, problems = set(), set(), {}
    rounds = 0
    while True:
        rounds += 1
        grew = flags_pass(bodies, flags_in, flags_out, problems)
        print(f'flags round {rounds}: in={len(flags_in)} out={len(flags_out)} problems={len(problems)} '
              f'({time.time() - start:.1f}s)', flush=True)
        if not grew:
            break
    print(f'frame helpers: {sorted(helpers.items())}', flush=True)
    fragments = find_fragments(bodies, helpers)
    graphs = {name: build_graph(name, bodies, fragments) for name in bodies if name not in fragments}
    print(f'fragments {len(fragments)}, heads {len(graphs)} ({time.time() - start:.1f}s)', flush=True)
    cs_in, cs_out = {}, {}
    rounds = 0
    while True:
        rounds += 1
        grew = cs_pass(graphs, bodies, cs_in, cs_out, helpers, fragments)
        print(f'regs round {rounds}: in={sum(1 for v in cs_in.values() if v)} '
              f'out={sum(1 for v in cs_out.values() if v)} ({time.time() - start:.1f}s)', flush=True)
        if not grew:
            break
    return functions, bodies, flags_in, flags_out, problems, cs_in, cs_out, helpers, fragments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/call-protocol/summary.json')
    args = parser.parse_args()
    functions, bodies, flags_in, flags_out, problems, cs_in, cs_out, helpers, fragments = analyze(args.out.parent)
    nonabi = {f.va for name, f in functions.items() if cs_in.get(name) or cs_out.get(name)}
    taken = address_taken(functions, nonabi)
    regs = {name: [cs_in.get(name, 0), cs_out.get(name, 0)] for name in sorted(functions)
            if cs_in.get(name) or cs_out.get(name)}
    summary = dict(functions=len(functions), flags_in=sorted(flags_in), flags_out=sorted(flags_out),
                   problems=[dict(function=k[0], address=f'{k[1]:08X}', reason=v)
                             for k, v in sorted(problems.items())],
                   regs=regs, nonabi_address_taken=sorted(f'sub_{va:08X}' for va in taken),
                   names=sorted(functions), helpers=helpers, fragments=sorted(fragments),
                   flags_roots={k: list(v) for k, v in sorted(FLAG_ROOTS.items())})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=1) + '\n')
    print(f'flags_in={len(flags_in)} flags_out={len(flags_out)} problems={len(problems)} '
          f'nonabi={len(nonabi)} nonabi_taken={len(taken)} -> {args.out}', flush=True)


if __name__ == '__main__':
    main()
