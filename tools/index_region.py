"""AOT index expansion for the pinned H5 writer's pure, bounded region.

The caller supplies valid locked-buffer RAM. Fast copies require disjoint,
non-wrapping spans outside the runtime register globals and enough backedge
budget to avoid every guest handoff. Other inputs retain the exact old body.
Warmup reads and each four-index load/two-store sequence remain volatile.
"""
import hashlib
import re

FUNCTION_SHA256 = '1c69781ee0c17b73045e12cb36c09f60a49dc64d07d980fc517eadcae2de2cf1'
FUNCTION_START = re.compile(rb"^void sub_00C362E0\(void\) \{\r?$", re.M)
FUNCTION_END = re.compile(rb"^\}\r?$", re.M)
NEEDLE = b"    /* cmp ecx, 4 */ /* 0x00C364BA: cmp ecx, 4 */"

HOST_GUARD = r"""
static inline int h5_index_region_host_ok(uint32_t source,uint32_t destination,uint32_t count) {
    uintptr_t low=(uintptr_t)g_mm, high=low+sizeof g_mm;
    uintptr_t slot=(uintptr_t)&g_backedges;
    if(slot<low)low=slot;
    if(slot+sizeof g_backedges>high)high=slot+sizeof g_backedges;
    slot=(uintptr_t)&recomp_yield_hook;
    if(slot<low)low=slot;
    if(slot+sizeof recomp_yield_hook>high)high=slot+sizeof recomp_yield_hook;
    uintptr_t src=(uintptr_t)ADDR(source),dst=(uintptr_t)ADDR(destination);
    return (src+(uintptr_t)count*2u<=low || src>=high) &&
           (dst+(uintptr_t)count*4u<=low || dst>=high);
}
""".encode()

FAST_REGION = r"""
    /* H5_INDEX_REGION_FAST_BEGIN */
    {
        uint32_t h5_n = ecx;
        if (h5_n >= 64u && h5_n <= 32766u) {
            uint32_t h5_steps = (h5_n + 13u) / 16u + h5_n / 4u + h5_n % 4u;
            uint64_t h5_src_end = (uint64_t)esi + h5_n * 2u;
            uint64_t h5_dst_end = (uint64_t)edi + h5_n * 4u;
            if ((!recomp_yield_hook ||
                 (RECOMP_BACKEDGE_COUNTER < RECOMP_YIELD_EVERY &&
                  h5_steps < RECOMP_YIELD_EVERY - RECOMP_BACKEDGE_COUNTER)) &&
                h5_src_end <= UINT32_MAX && h5_dst_end <= UINT32_MAX &&
                (h5_src_end <= edi || h5_dst_end <= esi) &&
                h5_index_region_host_ok(esi, edi, h5_n)) {
                typedef uint16_t h5_unaligned16 __attribute__((aligned(1),may_alias));
                typedef uint32_t h5_unaligned32 __attribute__((aligned(1),may_alias));
                typedef uint64_t h5_unaligned64 __attribute__((aligned(1),may_alias));
                typedef uint16_t h5_u16x4 __attribute__((vector_size(8),aligned(1),may_alias));
                typedef uint32_t h5_u32x4 __attribute__((vector_size(16)));
                h5_u32x4 h5_bias = {ebx,ebx,ebx,ebx}, h5_last = {0,0,0,0};
                _mm[1] = (uint64_t)ebx | ((uint64_t)ebx << 32);
                _mm[0] = 0;
                eax = h5_n - 2u;
                do {
                    edx = *(volatile h5_unaligned32 *)ADDR(esi + eax * 2u);
                    eax -= 16u;
                } while ((int32_t)eax > 0);
                for (uint32_t h5_i = 0; h5_i < h5_n / 4u; ++h5_i) {
                    h5_u16x4 h5_input = *(volatile h5_u16x4 *)ADDR(esi);
                    uint64_t h5_low, h5_high;
                    h5_last = __builtin_convertvector(h5_input,h5_u32x4) + h5_bias;
                    memcpy(&h5_low, &h5_last, 8);
                    memcpy(&h5_high, (const char *)&h5_last + 8, 8);
                    *(volatile h5_unaligned64 *)ADDR(edi) = h5_low;
                    *(volatile h5_unaligned64 *)ADDR(edi + 8u) = h5_high;
                    esi += 8u; edi += 16u;
                }
                memcpy(&_mm[3], &h5_last, 16);
                ecx = h5_n % 4u;
                if (ecx) {
                    do {
                        eax = (uint32_t)*(volatile h5_unaligned16 *)ADDR(esi) + ebx;
                        *(volatile h5_unaligned32 *)ADDR(edi) = eax;
                        esi += 2u; edi += 4u; --ecx;
                    } while (ecx);
                    _flag_a=1u; _flag_b=1u; _flag_k=FK_DEC; _cf=0;
                } else {
                    _flag_a=0; _flag_b=0; _flag_k=FK_CMP; _cf=0;
                }
                RECOMP_BACKEDGE_COUNTER += h5_steps;
                goto L_00C36519;
            }
        }
    }
    /* H5_INDEX_REGION_FAST_END */
""".encode()


def index_region(text):
    match = FUNCTION_START.search(text)
    if not match:
        return text
    end = FUNCTION_END.search(text, match.end())
    if not end:
        return text
    stop = text.find(b"\n", end.end())
    stop = stop + 1 if stop >= 0 else len(text)
    original = text[match.start():stop]
    body = original.replace(b"\r\n", b"\n")
    if hashlib.sha256(body.rstrip(b"\n") + b"\n").hexdigest() != FUNCTION_SHA256:
        return text
    replacement = HOST_GUARD + body.replace(NEEDLE, FAST_REGION + NEEDLE, 1)
    if b"\r\n" in original:
        replacement = replacement.replace(b"\n", b"\r\n")
    return text[:match.start()] + replacement + text[stop:]
