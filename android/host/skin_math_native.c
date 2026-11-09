/* Packed signed-word matrix transforms. The guest tables, staged saturation
 * and normalization are exact; the three entrypoints share one typed kernel. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_00C68210(void);
extern void sub_00C682D0(void);
extern void sub_00C683E0(void);

typedef struct skin_matrix { uint64_t column[3]; } skin_matrix;
typedef struct skin_math_result {
    uint64_t mm[8];
    uint32_t coefficient, packed, third_weight;
} skin_math_result;

static inline uint64_t skin_matrix_product(const uint64_t axis[3],
        const skin_matrix *matrix, uint64_t product[3])
{
    for(unsigned component=0;component<3;component++)
        product[component]=mmx_pmulhw(axis[component],matrix->column[component]);
    return mmx_paddsw(mmx_paddsw(product[0],product[1]),product[2]);
}

static inline __attribute__((always_inline)) skin_math_result skin_transform_packed(unsigned bones,uint32_t packed,
        uint32_t constants,const uint32_t matrix_address[3],uint32_t frame)
{
    skin_math_result result;
    result.mm[5]=g_mm[5];result.mm[6]=g_mm[6];
    uint64_t low_rgb=packed&0x00FFFFFFu;
    uint64_t decoded=mmx_psubw(mmx_punpcklbw(0,low_rgb),MEM64(constants));
    uint64_t right=decoded>>16;
    uint64_t axis[3]={decoded,mmx_paddw(decoded<<16,decoded>>32),
                     mmx_paddw(decoded<<32,right)};

    /* Preserve the original guest read order: one column across all bones,
     * then the next column. No guest writes occur before the final output. */
    skin_matrix matrices[3];
    for(unsigned column=0;column<3;column++)
        for(unsigned bone=0;bone<bones;bone++)
            matrices[bone].column[column]=MEM64(matrix_address[bone]+column*8u);

    uint64_t products[3][3],transformed[3],weighted[3];
    for(unsigned bone=0;bone<bones;bone++)
        transformed[bone]=skin_matrix_product(axis,&matrices[bone],products[bone]);

    uint64_t combined=transformed[0];
    uint32_t weights[3]={0,0,0};
    if(bones>1) {
        for(unsigned bone=0;bone<bones;bone++)weights[bone]=MEM8(frame+0x20u+bone*8u);
        for(unsigned bone=0;bone<bones;bone++) {
            uint64_t coefficient=MEM64(0x010CD990u+weights[bone]*8u);
            weighted[bone]=mmx_pmulhw(mmx_psllw(transformed[bone],4),coefficient);
        }
        combined=mmx_paddsw(weighted[0],weighted[1]);
        if(bones==3)combined=mmx_paddsw(combined,weighted[2]);
        result.mm[5]=weighted[1];
        result.mm[6]=products[1][2];
    }

    uint64_t scaled=mmx_psllw(combined,3);
    uint64_t square_pairs=mmx_pmaddwd(scaled,scaled);
    uint64_t square_high=square_pairs>>32;
    uint64_t square_sum=mmx_paddd(square_pairs,square_high);
    uint32_t table_index=(uint32_t)square_sum>>18;
    uint32_t coefficient=MEM16(0x010CE990u+table_index*2u);
    uint64_t normalization=(uint64_t)coefficient*0x0001000100010001ull;
    uint64_t normalized=mmx_psllw(mmx_pmulhw(scaled,normalization),5);
    uint64_t bytes=mmx_psrlw(mmx_paddw(normalized,MEM64(constants+8u)),8);
    uint64_t packed_bytes=mmx_packuswb(bytes,bytes);

    result.mm[0]=decoded;
    result.mm[1]=packed_bytes;
    result.mm[2]=normalization;
    result.mm[3]=square_high;
    result.mm[4]=bones==3?products[2][2]:right;
    result.mm[7]=bones==3?weighted[2]:low_rgb;
    result.coefficient=coefficient;
    result.packed=(packed&0xFF000000u)|(uint32_t)packed_bytes;
    result.third_weight=weights[2];
    return result;
}

/* Specialize the bounded kernel for each of the three exported arities. */
static inline __attribute__((always_inline)) void skin_math_entry(unsigned bones,uint32_t original)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(original);
    (void)_flag_k;
    esp-=8;
    PUSH32(esp,ebx);
    PUSH32(esp,esi);
    PUSH32(esp,edi);
    MEM32(esp+0x10)=edx;
    MEM32(esp+0xC)=ecx;
    uint32_t packed=MEM32(MEM32(esp+0x10));
    uint32_t matrices[3]={MEM32(esp+0x1C),0,0};
    if(bones>1)matrices[1]=MEM32(esp+0x24);
    if(bones==3)matrices[2]=MEM32(esp+0x2C);
    uint32_t constants=MEM32(esp+0x18);
    skin_math_result result=skin_transform_packed(bones,packed,constants,matrices,esp);
    for(unsigned reg=0;reg<8;reg++)g_mm[reg]=result.mm[reg];
    eax=result.coefficient;
    ecx=result.packed;
    if(bones==3)edx=result.third_weight;
    /* Reload the actual guest spill: output may alias the saved frame. */
    esi=MEM32(esp+0xC);
    MEM32(esi)=ecx;
    edi=POP32_VAL(esp);
    esi=POP32_VAL(esp);
    ebx=POP32_VAL(esp);
    static const uint32_t returns[3]={12,24,32};
    esp+=8+returns[bones-1];
    RECOMP_EXIT_P(0x17u);
}

void void_skin_math_one(void){skin_math_entry(1,0x00C68210u);}
void void_skin_math_two(void){skin_math_entry(2,0x00C682D0u);}
void void_skin_math_three(void){skin_math_entry(3,0x00C683E0u);}

static int skin_math_mode(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-skin-math", "[skin-math-native] mode=%d (cached for this process)");
    return mode;
}
void void_skin_math_one_dispatch(void){if(skin_math_mode())void_skin_math_one();else sub_00C68210();}
void void_skin_math_two_dispatch(void){if(skin_math_mode())void_skin_math_two();else sub_00C682D0();}
void void_skin_math_three_dispatch(void){if(skin_math_mode())void_skin_math_three();else sub_00C683E0();}
