/* Generated code addresses guest memory as g_guest_mem + VA
 * (RECOMP_GUEST_PROVENANCE in recomp_types.h): a hidden absolute symbol at the
 * fixed guest window. It lives alone in this file: a module that also
 * referenced it would ask the assembler for a PC-relative fixup the window is
 * out of range for, and with no functions here ThinLTO never imports any. */
__asm__(".globl g_guest_mem\n\t.hidden g_guest_mem\n\t.set g_guest_mem, 0x2000000000");
