/* Exact generated 87E5A4..D3 arithmetic; includes computed NaN payloads. */

#include <assert.h>
#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
static uint8_t memory[0x30000];
#define ADDR(va) (memory+(uint32_t)(va))
#define MEM32(va) (*(uint32_t *)ADDR(va))
static uint32_t eax,ecx,edx,ebx,esp,ebp,esi,edi;
static uint32_t _cf,_flag_k,_flag_a,_flag_b;
#define RECOMP_X87_SLOTS 256
static double g_st_win[256];
static int64_t g_st_i64_win[256];
static int g_fp_sp;
#define g_st (*(double (*)[8])(g_st_win + g_fp_sp))
#define g_st_i64 (*(int64_t (*)[8])(g_st_i64_win + g_fp_sp))
static int g_fp_top,void_fpu_cmp;
static uint16_t g_fpu_cw;
static unsigned guard_operands[7];
#define _st g_st
#define _fp_top g_fp_top
enum {
    FK_NONE = 0,
    FK_CMP,     /* cmp, sub       -- a - b            */
    FK_ADD,     /* add            -- a + b            */
    FK_TEST,    /* and/or/xor/test/shift -- a & b     */
    FK_BT,      /* bt             -- CF = bit b of a  */
    FK_FCOM,    /* fcom           -- a is -1/0/1, 2 = unordered */
    /* INC and DEC are ADD and SUB that do NOT write CF. No condition can tell
     * them apart (a jcc reading CF after an inc is reading a flag the
     * instruction never wrote), but PUSHFD can: it has to report the carry
     * that was already there rather than the one the addition would have
     * produced. */
    FK_INC,     /* inc            -- a + b, CF preserved */
    FK_DEC,     /* dec            -- a - b, CF preserved */
    /* The flags as a literal word, from POPFD. Nothing is derived: every flag
     * is read from its own bit. The lazy triple cannot express an arbitrary
     * combination of flags, and a program that restores a saved EFLAGS is
     * asking for exactly that. */
    FK_EFLAGS
};
/* ACTUAL_WINDOW_HELPERS */
/* BASELINE_WINDOW_HELPERS */
#define fp_push(v) baseline_window_push((v))
#define fp_pop() baseline_window_pop()

static __attribute__((noinline)) void original(void) {
    fp_push(*(float*)&MEM32(ecx + edi + 0x4)); /* 0x0087E5A4: fld dword ptr [ecx + edi + 4] */
    eax = 0x2AAAAAABu; /* 0x0087E5A8: mov eax, 0x2aaaaaab */
    _st[0] *= (double)*(float*)ADDR(ebp + 0x34); /* 0x0087E5AD: fmul dword ptr [ebp + 0x34] */
    _flag_a = (uint32_t)(ebx); _flag_b = (uint32_t)(1);
    _cf = (uint32_t)((uint32_t)(_flag_a + _flag_b) < (uint32_t)_flag_a);
    ebx = ebx + 1; /* 0x0087E5B0: add ebx, 1 */
    _flag_k = FK_ADD;
    fp_push(*(float*)&MEM32(ecx + edi + 0x8)); /* 0x0087E5B3: fld dword ptr [ecx + edi + 8] */
    _flag_a = (uint32_t)(edi); _flag_b = (uint32_t)(0xCu);
    _cf = (uint32_t)((uint32_t)(_flag_a + _flag_b) < (uint32_t)_flag_a);
    edi = edi + 0xCu; /* 0x0087E5B7: add edi, 0xc */
    _flag_k = FK_ADD;
    _st[0] *= (double)*(float*)ADDR(ebp + 0x38); /* 0x0087E5BA: fmul dword ptr [ebp + 0x38] */
    { double _v = fp_pop(); _st[0] += _v; } /* 0x0087E5BD: faddp st(1) */
    fp_push(*(float*)&MEM32(ecx + edi + (-0xC))); /* 0x0087E5BF: fld dword ptr [ecx + edi - 0xc] */
    ecx = MEM32(esp + 0x40); /* 0x0087E5C3: mov ecx, dword ptr [esp + 0x40] */
    _st[0] *= (double)*(float*)ADDR(ebp + 0x30); /* 0x0087E5C7: fmul dword ptr [ebp + 0x30] */
    { double _v = fp_pop(); _st[0] += _v; } /* 0x0087E5CA: faddp st(1) */
    _st[0] += (double)*(float*)ADDR(ebp + 0x3C); /* 0x0087E5CC: fadd dword ptr [ebp + 0x3c] */
    { float _v = (float)fp_pop(); *(float*)ADDR(ecx + ebx * 4 + (-0x4)) = _v; } /* 0x0087E5CF: fstp dword ptr [ecx + ebx*4 - 4] */

}
#undef fp_push
#undef fp_pop
#define fp_push(v) fp_window_push((v))
#define fp_pop() fp_window_pop()
static __attribute__((noinline)) void cached(void) {
    fp_push(*(float*)&MEM32(ecx + edi + 0x4)); /* 0x0087E5A4: fld dword ptr [ecx + edi + 4] */
    eax = 0x2AAAAAABu; /* 0x0087E5A8: mov eax, 0x2aaaaaab */
    _st[0] *= (double)*(float*)ADDR(ebp + 0x34); /* 0x0087E5AD: fmul dword ptr [ebp + 0x34] */
    _flag_a = (uint32_t)(ebx); _flag_b = (uint32_t)(1);
    _cf = (uint32_t)((uint32_t)(_flag_a + _flag_b) < (uint32_t)_flag_a);
    ebx = ebx + 1; /* 0x0087E5B0: add ebx, 1 */
    _flag_k = FK_ADD;
    fp_push(*(float*)&MEM32(ecx + edi + 0x8)); /* 0x0087E5B3: fld dword ptr [ecx + edi + 8] */
    _flag_a = (uint32_t)(edi); _flag_b = (uint32_t)(0xCu);
    _cf = (uint32_t)((uint32_t)(_flag_a + _flag_b) < (uint32_t)_flag_a);
    edi = edi + 0xCu; /* 0x0087E5B7: add edi, 0xc */
    _flag_k = FK_ADD;
    _st[0] *= (double)*(float*)ADDR(ebp + 0x38); /* 0x0087E5BA: fmul dword ptr [ebp + 0x38] */
    { double _v = fp_pop(); _st[0] += _v; } /* 0x0087E5BD: faddp st(1) */
    fp_push(*(float*)&MEM32(ecx + edi + (-0xC))); /* 0x0087E5BF: fld dword ptr [ecx + edi - 0xc] */
    ecx = MEM32(esp + 0x40); /* 0x0087E5C3: mov ecx, dword ptr [esp + 0x40] */
    _st[0] *= (double)*(float*)ADDR(ebp + 0x30); /* 0x0087E5C7: fmul dword ptr [ebp + 0x30] */
    { double _v = fp_pop(); _st[0] += _v; } /* 0x0087E5CA: faddp st(1) */
    _st[0] += (double)*(float*)ADDR(ebp + 0x3C); /* 0x0087E5CC: fadd dword ptr [ebp + 0x3c] */
    { float _v = (float)fp_pop(); *(float*)ADDR(ecx + ebx * 4 + (-0x4)) = _v; } /* 0x0087E5CF: fstp dword ptr [ecx + ebx*4 - 4] */

}
typedef struct {
    uint64_t st[8];int64_t shadow[8];int top,cmp,sp;uint16_t cw;
    uint32_t regs[8],flags[4];uint8_t memory[0x20000];
} snapshot;
static snapshot entry,expected,actual;
static void take(snapshot *s) {
    memset(s,0,sizeof *s);
    memcpy(s->st,g_st,sizeof g_st);memcpy(s->shadow,g_st_i64,sizeof g_st_i64);
    s->top=g_fp_top;s->cmp=void_fpu_cmp;s->cw=g_fpu_cw;s->sp=g_fp_sp;
    const uint32_t regs[]={eax,ecx,edx,ebx,esp,ebp,esi,edi};
    const uint32_t flags[]={_cf,_flag_k,_flag_a,_flag_b};
    memcpy(s->regs,regs,sizeof regs);memcpy(s->flags,flags,sizeof flags);
    memcpy(s->memory,ADDR(0x10000),sizeof s->memory);
}
static void restore(const snapshot *s) {
    g_fp_sp=s->sp;memcpy(g_st,s->st,sizeof g_st);memcpy(g_st_i64,s->shadow,sizeof g_st_i64);
    g_fp_top=s->top;void_fpu_cmp=s->cmp;g_fpu_cw=s->cw;
    eax=s->regs[0];ecx=s->regs[1];edx=s->regs[2];ebx=s->regs[3];
    esp=s->regs[4];ebp=s->regs[5];esi=s->regs[6];edi=s->regs[7];
    _cf=s->flags[0];_flag_k=s->flags[1];_flag_a=s->flags[2];_flag_b=s->flags[3];
    memcpy(ADDR(0x10000),s->memory,sizeof s->memory);
}
static uint64_t random_state=0xC4A53871DE46B209ull;
static uint64_t random64(void) {
    random_state^=random_state<<13;random_state^=random_state>>7;
    random_state^=random_state<<17;return random_state;
}
static uint32_t float_bits(unsigned test,unsigned i) {
    static const uint32_t edge[]={0,0x80000000u,0x3F800000u,0xBF800000u,
        0x7F800000u,0xFF800000u,0x7FC12345u,0xFFC54321u,0x7FA12345u,
        1,0x80000001u,0x7F7FFFFFu,0xFF7FFFFFu,0x00800000u,0x3F000000u};
    uint32_t r=(uint32_t)random64();
    if(test<256) return (r&0x807FFFFFu)|((110u+(r>>24)%31u)<<23);
    if(test<512) {
        if((r&0x7F800000u)==0x7F800000u)r^=0x00800000u;
        return r;
    }
    return (i&1)?r:edge[(test+i)%(sizeof edge/sizeof *edge)];
}
static unsigned layouts[16];
static void initialize(unsigned test,unsigned rounding) {
    g_fp_sp=test%249;for(unsigned i=0;i<0x20000;i+=4)MEM32(0x10000+i)=float_bits(test,i);
    for(unsigned i=0;i<8;++i) {
        static const uint64_t edge[]={0,0x8000000000000000ull,
            0x7FF0000000000000ull,0xFFF0000000000000ull,
            0x7FF8123456789ABCull,0xFFF876543210ABCDull,
            0x7FF0123456789ABCull,1};
        uint64_t bits=(test&1)?random64():edge[(test+i)%8];
        memcpy(g_st+i,&bits,8);g_st_i64[i]=(int64_t)random64();
    }
    g_fp_top=(int)(test%33)-16;void_fpu_cmp=(int)(uint32_t)random64();
    g_fpu_cw=(uint16_t)(0x037Fu|(rounding<<10));
    eax=(uint32_t)random64();edx=(uint32_t)random64();
    ebx=(uint32_t)random64();esi=(uint32_t)random64();esp=0x18000;ebp=0x14000;
    edi=(test&1)?0xFFFFFFF0u:(test%32)*4u;
    uint32_t vector=0x11000,target=0x16000;
    unsigned layout=(test>=768&&test<960)?0:test%16;++layouts[layout];
    switch(layout) {
    case 1:target=vector;break;
    case 2:target=vector+4;break;
    case 3:target=vector+8;break;
    case 4:target=ebp+0x30;break;
    case 5:target=ebp+0x34;break;
    case 6:target=ebp+0x38;break;
    case 7:target=ebp+0x3C;break;
    case 8:target=esp+0x40;break;
    case 9:ebp=vector-0x30;break;
    case 10:ebp=esp+0x0C;break;
    case 11:vector=esp+0x3C;break;
    case 12:vector=0x11001;ebp=0x14002;target=0x16003;break;
    case 13:target=vector+2;break;
    case 14:ebp=vector-0x32;target=ebp+0x31;break;
    case 15:target=esp+0x41;break;
    }
    ecx=vector-edi;
    MEM32(esp+0x40)=target-ebx*4u;
    uint32_t operands[]={vector+4,ebp+0x34,vector+8,ebp+0x38,vector,ebp+0x30,ebp+0x3C};
    if(test>=768&&test<880) {
        static const uint32_t special[]={0x7FC12345u,0x7FA54321u,0x7F800000u,0xFF800000u};
        for(unsigned i=0;i<7;++i)MEM32(operands[i])=0x3F000000u+i;
        unsigned operand=(test-768)%7;
        MEM32(operands[operand])=special[((test-768)/7)%4];++guard_operands[operand];
    } else if(test>=896&&test<960) {
        for(unsigned i=0;i<7;++i)MEM32(operands[i])=((test+i)&1)?0xFF7FFFFFu:0x7F7FFFFFu;
    }
    _cf=(uint32_t)random64();_flag_k=(uint32_t)random64();
    _flag_a=(uint32_t)random64();_flag_b=(uint32_t)random64();
}
static int same(const snapshot *a,const snapshot *b) {
    return !memcmp(a,b,sizeof *a);
}
static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;
    assert(same(&expected,&actual));
    static const size_t offsets[]={offsetof(snapshot,st),offsetof(snapshot,st)+56,
        offsetof(snapshot,shadow),offsetof(snapshot,shadow)+56,offsetof(snapshot,top),
        offsetof(snapshot,cmp),offsetof(snapshot,cw),offsetof(snapshot,regs),
        offsetof(snapshot,flags),offsetof(snapshot,memory),sizeof(snapshot)-1};
    for(unsigned i=0;i<sizeof offsets/sizeof *offsets;++i) {
        ((uint8_t *)&actual)[offsets[i]]=1;assert(!same(&expected,&actual));
        ((uint8_t *)&actual)[offsets[i]]=0;
    }
    uint32_t left=0x7FC12345u,right=0xFFC54321u;
    memcpy(expected.memory,&left,4);memcpy(actual.memory,&right,4);
    assert(!same(&expected,&actual)); /* Computed NaNs are also bitwise. */
}
int main(void) {
    assert(fesetround(FE_TONEAREST)==0);comparison_contract();
    unsigned cases=0;
    for(unsigned rc=0;rc<4;++rc)for(unsigned test=0;test<1024;++test) {
        initialize(test,rc);take(&entry);original();take(&expected);
        restore(&entry);cached();take(&actual);
        if(!same(&expected,&actual)) {
            const uint8_t *a=(const uint8_t *)&expected,*b=(const uint8_t *)&actual;
            for(size_t i=0;i<sizeof expected;++i)if(a[i]!=b[i]) {
                fprintf(stderr,"Mismatch case=%u rc=%u byte=%zu expected=%02X actual=%02X\n",
                        test,rc,i,a[i],b[i]);break;
            }
            return 1;
        }
        assert(expected.top==entry.top);
        assert(expected.regs[0]==0x2AAAAAABu && expected.regs[3]==entry.regs[3]+1u);
        assert(expected.regs[4]==entry.regs[4] && expected.regs[5]==entry.regs[5]);
        assert(expected.regs[2]==entry.regs[2] && expected.regs[6]==entry.regs[6]);
        assert(expected.regs[7]==entry.regs[7]+12u);
        assert(!memcmp(expected.st,entry.st,6*sizeof(uint64_t)));
        assert(!memcmp(expected.shadow,entry.shadow,6*sizeof(int64_t)));
        for(unsigned i=6;i<8;++i)assert(!expected.st[i]&&!expected.shadow[i]);
        ++cases;
    }
    for(unsigned i=0;i<16;++i)assert(layouts[i]);
    for(unsigned i=0;i<7;++i)assert(guard_operands[i]);

    printf("PASS %u current-vs-unhinted x87 window projection comparisons: all raw memory/FPU/shadows/depth/CW/status/GPR/flags exact; 16 aliases; all4RC; NaN/Inf/subnormal/signedzero; wrapped registers\n",cases);
    return 0;
}
