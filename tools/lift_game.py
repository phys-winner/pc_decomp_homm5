"""Checked x86-to-C generation reused from The Void, without game-specific patches."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference/pcrecomp"))
from tools.pe.pe_analyze import analyze_pe, build_iat_map
from tools.disasm.disasm32 import Disassembler
from tools.lift.lift32 import Lifter
from tools.lift.generate import lift_function_linear as _vendor_lift_function_linear
from tools.lift.eh32 import resume_points, funcinfo, catch_funclets, PROLOGUE_WINDOW
from capstone.x86 import (X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_XMM0,
                         X86_REG_XMM7, X86_REG_EBP, X86_REG_ESP)


class CheckedLifter(Lifter):
    def _make_condition(self, mnemonic):
        condition = super()._make_condition(mnemonic)
        state = self._flag_state
        if state is None or state[0] not in ("test", "and", "or", "xor"):
            return condition
        # MSVC 14.51 /O1 and /O2 can fold a signed cast of two left-aligned
        # narrow captures to nonnegative. Test the actual x86 sign bit with
        # unsigned arithmetic; the vendor still normalizes jcc/setcc/cmovcc.
        left, right = (part.strip() for part in state[1].split(",", 1))
        value = f"((uint32_t)({left}) & (uint32_t)({right}))"
        sign = f"({value} & 0x80000000u)"
        predicates = {
            f"TEST_S({state[1]})": f"({sign} != 0u)",
            f"TEST_NS({state[1]})": f"({sign} == 0u)",
            f"TEST_G({state[1]})": f"({value} != 0u && {sign} == 0u)",
            f"TEST_LE({state[1]})": f"({value} == 0u || {sign} != 0u)",
        }
        return predicates.get(condition, condition)

    def lift_instruction(self, instruction):
        mnemonic = instruction.mnemonic.split()[-1]
        if mnemonic in ("pusha", "pushaw"):
            return ["{ uint32_t _pusha_sp = esp; "
                    "PUSH16(esp, eax); PUSH16(esp, ecx); PUSH16(esp, edx); PUSH16(esp, ebx); "
                    "PUSH16(esp, _pusha_sp); PUSH16(esp, ebp); PUSH16(esp, esi); PUSH16(esp, edi); }"]
        if mnemonic in ("popa", "popaw"):
            return ["SET_LO16(edi, POP16_VAL(esp)); SET_LO16(esi, POP16_VAL(esp)); "
                    "SET_LO16(ebp, POP16_VAL(esp)); esp += 2; "
                    "SET_LO16(ebx, POP16_VAL(esp)); SET_LO16(edx, POP16_VAL(esp)); "
                    "SET_LO16(ecx, POP16_VAL(esp)); SET_LO16(eax, POP16_VAL(esp));"]
        if mnemonic in ("fnsave", "fsave", "frstor"):
            text = instruction.mnemonic + " " + instruction.op_str
            return [f"void_lift_trap(0x{instruction.address:08X}u, {json.dumps(text)}); "
                    f"/* 0x{instruction.address:08X}: {text} */"]
        if mnemonic == "pause":
            # Spin-wait hint. The spinning loop's back edge already yields the machine.
            return [f"/* pause */ /* 0x{instruction.address:08X}: {instruction.mnemonic} {instruction.op_str} */"]
        if mnemonic in ("fprem", "fprem1"):
            if instruction.operands:
                return [f'void_lift_trap(0x{instruction.address:08X}u, "unsupported FPREM operands");']
            return [f"void_fpu_remainder(0x{instruction.address:08X}u, {int(mnemonic == 'fprem1')}); "
                    f"/* 0x{instruction.address:08X}: {instruction.mnemonic} {instruction.op_str} */"]
        if mnemonic in ("movsb", "movsw", "movsd"):
            prefixes = []
            for byte in instruction.bytes:
                if byte not in (0xF0, 0xF2, 0xF3, 0x2E, 0x36, 0x3E, 0x26, 0x64, 0x65, 0x66, 0x67):
                    break
                prefixes.append(byte)
            opcode = instruction.bytes[len(prefixes)] if len(prefixes) < len(instruction.bytes) else 0
            if opcode in (0xA4, 0xA5) and any(prefix in (0xF2, 0xF3) for prefix in prefixes):
                if any(prefix in (0x67, 0x64, 0x65) for prefix in prefixes):
                    return [f'void_lift_trap(0x{instruction.address:08X}u, "unsupported REP MOVS address/segment");']
                size = {"movsb": 1, "movsw": 2, "movsd": 4}[mnemonic]
                # Sequential element reads preserve deliberate overlap propagation.
                return [f"while (ecx) {{ MEM{size * 8}(edi) = MEM{size * 8}(esi); "
                        f"esi += _df * {size}; edi += _df * {size}; --ecx; }} "
                        f"/* 0x{instruction.address:08X}: {instruction.mnemonic} {instruction.op_str} */"]
        if mnemonic == "pmuludq":
            operands = instruction.operands
            if (len(operands) != 2 or operands[0].type != X86_OP_REG or
                    not X86_REG_XMM0 <= operands[0].reg <= X86_REG_XMM7):
                return [f'void_lift_trap(0x{instruction.address:08X}u, "unsupported PMULUDQ operands");']
            destination = operands[0].reg - X86_REG_XMM0
            source = operands[1]
            if source.type == X86_OP_REG and X86_REG_XMM0 <= source.reg <= X86_REG_XMM7:
                value = f"_xmm[{source.reg - X86_REG_XMM0}]"
            elif source.type == X86_OP_MEM and source.size == 16:
                value = f"xmm_ld({self._fmt_mem_addr(source.mem)})"
            else:
                return [f'void_lift_trap(0x{instruction.address:08X}u, "unsupported PMULUDQ operands");']
            return [f"{{ xmm_t _a = _xmm[{destination}], _b = {value}; "
                    f"_xmm[{destination}].u64[0] = (uint64_t)_a.u32[0] * _b.u32[0]; "
                    f"_xmm[{destination}].u64[1] = (uint64_t)_a.u32[2] * _b.u32[2]; }} "
                    f"/* 0x{instruction.address:08X}: {instruction.mnemonic} {instruction.op_str} */"]
        lines = super().lift_instruction(instruction)
        unsupported = ("UNIMPLEMENTED:", "unknown reg ", "unknown condition:")
        if any(marker in line for line in lines for marker in unsupported) or instruction.mnemonic == "int3":
            text = instruction.mnemonic + " " + instruction.op_str
            return [f"void_lift_trap(0x{instruction.address:08X}u, {json.dumps(text)});"]
        return lines


def lift_function_linear(*args, **kwargs):
    """Keep vendor generation, but conditions belong to the guest machine."""
    body = _vendor_lift_function_linear(*args, **kwargs)
    declaration = "    int _fpu_cmp = 0;\n"
    if body.count(declaration) != 1:
        raise ValueError("Pinned vendor FPU condition declaration changed")
    return body.replace(declaration, "", 1)


class BoundedDisassembler(Disassembler):
    """Fail visibly on an excessive decode rather than silently truncate it."""
    max_windows = 16384
    # The vendor scan stops at 256 entries. A declared table is read whole: H5's
    # spell-name switch (0x009F2438) has 353 arms, and an id past 255 reached a
    # missing arm (0x009F1E06) as an unresolved dispatch.
    max_declared_entries = 4096

    def __init__(self, *args, jump_tables=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.jump_tables = {address: (0, value) if type(value) is int else value
                            for address, value in (jump_tables or {}).items()}
        limit = self.max_declared_entries
        for address, (first_index, count) in self.jump_tables.items():
            if (type(address) is not int or type(first_index) is not int or type(count) is not int
                    or not -256 <= first_index <= 255 or not 1 <= count <= limit
                    or first_index + count > limit):
                raise ValueError(f"Declared jump tables require integer VAs, first indices in -256..255, "
                                 f"counts in 1..{limit} and last indices below {limit}")
            self._declared_table(address, first_index, count)

    def _declared_table(self, address, first_index, count):
        raw = self.read_bytes(address + first_index * 4, count * 4)
        if len(raw) != count * 4:
            raise ValueError(f"Truncated declared jump table {address:#x}")
        targets = []
        for index in range(count):
            target = struct.unpack_from("<I", raw, index * 4)[0]
            if target == 0:
                continue
            if not self.is_code_address(target):
                raise ValueError(f"Invalid jump table {address:#x} slot {first_index + index}: {target:#x}")
            targets.append(target)
        return targets

    def jump_table_targets(self, instruction, limit=256):
        for operand in instruction.operands or ():
            if operand.type != X86_OP_MEM:
                continue
            memory = operand.mem
            address = memory.disp & 0xFFFFFFFF
            if not memory.base and memory.index and memory.scale == 4 and address in self.jump_tables:
                # The declaration, not the scan limit, sizes the table.
                first_index, count = self.jump_tables[address]
                return self._declared_table(address, first_index, count)
        return super().jump_table_targets(instruction, limit)

    def disassemble_function(self, address, imports=None):
        self._windows = 0
        self._start = address
        return super().disassemble_function(address, imports)

    def disassemble_at(self, *args, **kwargs):
        self._windows += 1
        if self._windows > self.max_windows:
            raise ValueError(f"Decode window limit exceeded at {self._start:#x}")
        return super().disassemble_at(*args, **kwargs)


def function_dispatch_targets(function):
    """Targets which emitted calls/tails can reach outside this body's labels."""
    instructions = {i.address: i for b in function.blocks.values() for i in b.instructions}
    targets = set(function.calls_to) | (set(function.jump_targets) - instructions.keys())
    for instruction in instructions.values():
        if instruction.is_jump:
            target = instruction.get_branch_target()
            if target is not None and target not in instructions:
                targets.add(target)
        if not instruction.is_ret and not instruction.is_uncond_jump and instruction.mnemonic not in ("int3", "hlt"):
            if instruction.end_address not in instructions:
                targets.add(instruction.end_address)
    return targets


def complete_eh_owner(decoder, function, imports):
    """Keep metadata-proven cold catch continuations in their frame's body."""
    if hasattr(function, "eh_resume"):
        return
    instructions = sorted({i.address: i for b in function.blocks.values()
                           for i in b.instructions}.values(), key=lambda i: i.address)
    scanner_instructions = instructions
    bias = 0
    if (len(instructions) >= 3 and instructions[0].address == function.address
            and instructions[0].mnemonic == "push" and instructions[0].op_str == "ebp"):
        lea, sub = instructions[1:3]
        if (lea.address == instructions[0].end_address and sub.address == lea.end_address
                and lea.mnemonic == "lea" and len(lea.operands) == 2
                and lea.operands[0].type == X86_OP_REG and lea.operands[0].reg == X86_REG_EBP
                and lea.operands[1].type == X86_OP_MEM
                and sub.mnemonic == "sub" and len(sub.operands) == 2
                and sub.operands[0].type == X86_OP_REG and sub.operands[0].reg == X86_REG_ESP
                and sub.operands[1].type == X86_OP_IMM):
            memory = lea.operands[1].mem
            if (memory.base == X86_REG_ESP and not memory.index and not memory.segment
                    and 0 < -memory.disp <= 0x1000 and (-memory.disp) % 4 == 0
                    and sub.operands[1].imm == -memory.disp):
                bias = -memory.disp
                # Normalize only the metadata scanner; emitted guest instructions stay exact.
                scanner_instructions = [instructions[0], replace(lea, mnemonic="mov", op_str="ebp, esp"), *instructions[2:]]
    candidates = resume_points(decoder.md, decoder.read_bytes, scanner_instructions)
    function.eh_frame_bias = bias if candidates is not None else 0
    function.eh_resume = None if candidates is None else set()
    function.eh_added_instructions = 0
    if not candidates:
        return
    handler, fi = None, None
    for instruction in instructions[:PROLOGUE_WINDOW]:
        if instruction.mnemonic == "push" and instruction.op_str.startswith("0x"):
            handler = int(instruction.op_str, 16)
        elif instruction.mnemonic == "mov" and instruction.op_str.endswith("dword ptr fs:[0]") and handler is not None:
            fi = funcinfo(decoder.read_bytes, handler)
            break
    if fi is None:
        raise ValueError(f"EH owner {function.address:#x} has no verified FuncInfo")
    funclets = set(catch_funclets(decoder.read_bytes, fi))
    if len(funclets) > 256 or len(candidates) > 256:
        raise ValueError(f"EH owner {function.address:#x} exceeds bounded catch/resume count")
    returns = set()
    for entry in sorted(funclets):
        catch = decoder.disassemble_function(entry, imports)
        if catch is None or not catch.blocks or catch.num_instructions > 4096:
            raise ValueError(f"Cannot decode bounded EH funclet {entry:#x}")
        reachable = {i.address: i for b in catch.blocks.values() for i in b.instructions}
        ends = {i.end_address: i for i in reachable.values()}
        for instruction in reachable.values():
            previous = ends.get(instruction.address)
            if instruction.is_ret and previous is not None and previous.mnemonic == "mov" and previous.op_str.startswith("eax, 0x"):
                returns.add(int(previous.op_str[5:], 16))
    # The vendor scanner can walk linearly past a RET. Require a reachable RET
    # predecessor in the actual named catch CFG before trusting its return VA.
    verified = candidates & returns
    before = {i.address for i in instructions}
    for entry in sorted(verified):
        if not decoder.is_code_address(entry):
            raise ValueError(f"EH resume {entry:#x} is outside module code")
        if entry not in before:
            resume = decoder.disassemble_function(entry, imports)
            if resume is None or not resume.blocks or resume.num_instructions > 16384:
                raise ValueError(f"Cannot decode bounded EH continuation {entry:#x}")
            function.blocks.update(resume.blocks)
            function.calls_to.update(resume.calls_to)
            function.jump_targets.update(resume.jump_targets)
            function.end = max(function.end, resume.end)
        function.eh_resume.add(entry)
    if verified:
        # call_funclet resolves these through the global dispatch table.
        function.calls_to.update(funclets)
    after = {i.address for b in function.blocks.values() for i in b.instructions}
    function.eh_added_instructions = len(after - before)


def collect_functions(binary, catalog, extra_entries=(), *, label="Game", max_entries=100000,
                      jump_tables=None, compact=False):
    """Close a module's call graph, including constructor/vtable/callback seeds."""
    raw = binary.read_bytes()
    entries = {f["address"] for f in catalog}
    entries.update(extra_entries)
    catalog_entries = set(entries)
    info = analyze_pe(str(binary))
    entries.add(info.image_base + info.entry_point_rva)
    imports = build_iat_map(info)
    decoder = BoundedDisassembler(raw, info.image_base, info.sections, jump_tables=jump_tables)
    # CRT constructor arrays and C++ vtables name entries with no direct callers.
    for section in info.sections:
        if section.is_code:
            continue
        data = raw[section.raw_offset:section.raw_offset + section.raw_size]
        for offset in range(0, len(data) - 3, 4):
            pointer = struct.unpack_from("<I", data, offset)[0]
            if decoder.is_code_address(pointer):
                entries.add(pointer)
    functions = {}
    rejected_entries = []
    pending = sorted(entries)
    print(f"{label}: decoding {len(entries)} initial entries", file=sys.stderr, flush=True)
    while pending:
        if len(entries) > max_entries:
            raise ValueError(f"{label}: entry limit {max_entries} exceeded")
        address = pending.pop()
        if address in functions:
            continue
        function = decoder.disassemble_function(address, imports)
        if function is None or not function.blocks:
            if address not in catalog_entries:
                rejected_entries.append(hex(address))
                continue
            raise ValueError(f"Cannot decode catalog entry {address:#x}")
        complete_eh_owner(decoder, function, imports)
        functions[address] = function
        # Callback/destructor pointers are also computed or pushed in code.
        for block in function.blocks.values():
            for instruction in block.instructions:
                if instruction.is_jump or instruction.is_call:
                    continue
                for operand in instruction.operands or []:
                    pointer = operand.imm if operand.type == X86_OP_IMM else None
                    if instruction.mnemonic == "lea" and operand.type == X86_OP_MEM:
                        memory = operand.mem
                        if not memory.base and not memory.index:
                            pointer = memory.disp
                    if pointer is not None and decoder.is_code_address(pointer) and pointer not in entries:
                        entries.add(pointer)
                        pending.append(pointer)
        for target in sorted(function_dispatch_targets(function)):
            if target not in entries and decoder.is_code_address(target):
                entries.add(target)
                pending.append(target)
        if compact:
            # Large images retain only closure metadata; emit re-decodes one body at a time.
            function.blocks.clear()
            function.calls_to.clear()
            function.jump_targets.clear()
        if len(functions) % 1000 == 0:
            print(f"{label}: decoded {len(functions)} functions; {len(pending)} pending",
                  file=sys.stderr, flush=True)
    print(f"{label}: decoded {len(functions)} functions", file=sys.stderr, flush=True)
    return info, imports, decoder, functions, rejected_entries


def emit_functions(generated, imports, decoder, functions, *, label="Game",
                   header_name="recomp_funcs.h", chunk_prefix="recomp", additional_entries=()):
    """Emit explicit source lists; names are full live VAs for cross-module calls."""
    generated.mkdir(parents=True, exist_ok=True)
    addresses = sorted(functions)
    all_addresses = sorted(set(functions) | set(additional_entries))
    names = {a: f"sub_{a:08X}" for a in all_addresses}
    lifter = CheckedLifter(iat_map=imports, lifted=set(all_addresses),
                           precise_sbb=True, precise_carry=True)
    header = ["#pragma once", '#include "recomp_types.h"',
              "void void_lift_trap(uint32_t address, const char *instruction);"]
    header += [f"void {names[a]}(void);" for a in all_addresses]
    (generated / header_name).write_text("\n".join(header) + "\n")
    emitted = 0
    traps = []
    sources = []
    for chunk, start in enumerate(range(0, len(addresses), 100)):
        bodies = ['#define RECOMP_GENERATED_CODE', f'#include "{header_name}"']
        for address in addresses[start:start + 100]:
            function = functions[address]
            if not function.blocks:
                function = decoder.disassemble_function(address, imports)
            instructions = sorted({i.address: i for b in function.blocks.values()
                                   for i in b.instructions}.values(), key=lambda i: i.address)
            complete_eh_owner(decoder, function, imports)
            instructions = sorted({i.address: i for b in function.blocks.values()
                                   for i in b.instructions}.values(), key=lambda i: i.address)
            eh = function.eh_resume
            body = lift_function_linear(lifter, names[address], instructions,
                                        set(function.blocks), address,
                                        indirect_targets=function.jump_targets,
                                        eh_resume=eh)
            if eh and function.eh_frame_bias:
                assert body.count("    RECOMP_EH_ENTER();") == 1
                # The runtime matches EBP+4; longjmp jumps past this initial-only adjustment.
                body = body.replace("    RECOMP_EH_ENTER();", "    RECOMP_EH_ENTER();\n"
                                    f"    _ehf.entry_esp -= 0x{function.eh_frame_bias:X}u;")
            bodies.append(body)
            emitted += len(instructions)
            if "void_lift_trap(" in body:
                traps.append(hex(address))
        filename = f"{chunk_prefix}_{chunk:04d}.c"
        (generated / filename).write_text("\n\n".join(bodies) + "\n")
        sources.append(filename)
        count = min(start + 100, len(addresses))
        if count % 1000 == 0 or count == len(addresses):
            print(f"{label}: emitted {count}/{len(addresses)} functions",
                  file=sys.stderr, flush=True)
    return {"functions": len(addresses), "emitted_instructions_with_overlap": emitted,
            "eh_owners": sum(bool(f.eh_resume) for f in functions.values()),
            "cold_eh_added_instructions": sum(f.eh_added_instructions for f in functions.values()),
            "functions_containing_traps": traps, "sources": sources}


def emit_dispatch(destination, addresses, headers):
    addresses = list(addresses)
    if len(set(addresses)) != len(addresses):
        raise ValueError("Duplicate live VAs in merged dispatch")
    table = [f'#include "{header}"' for header in headers]
    table.append("const recomp_dispatch_entry_t recomp_dispatch_table[] = {")
    table += [f"    {{0x{a:08X}u, sub_{a:08X}}}," for a in sorted(addresses)]
    table += ["};", f"const uint32_t recomp_dispatch_count = {len(addresses)};"]
    destination.write_text("\n".join(table) + "\n")
