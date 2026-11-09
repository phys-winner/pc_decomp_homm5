"""Reference semantics versus fresh actual all-edition production C."""
from pathlib import Path
import hashlib,json,re,sys,unittest
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'build/tests/reference-native'
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools')]
import pefile
from editions import generated_root,protocol_root
from test_scene_native import body,transformed
from test_vector_native import PREFIX,EVENT_COMPARE
from test_mmx_packed import CLANG,command,environment,pc_header
from x87_locals import Plan,apply_x87

FACTS={
 'toe':('004FA280','00C05AC0','00C05B10','00731290','00611AA0','0061F290','008C61D0','00D119FC','00F272C0','00F78FC0'),
 'vanilla':('00459100','00A44BE0','00A44C30','006CD9F0','00961930','0065B5D0','00B20550','00C0D69E','00F06A04','00F2CC48'),
 'hof':('0047B340','008078A0','008078F0','006AF170','00756120','004C04D0','00A02160','00C09BCE','00ED47C0','00EEFE40'),
}
BASE_HELPER=r'''
static void reference_hof_base(void) {
 REF_LOCALS
 RECOMP_ENTER(0x00456050u);
 eax=ecx;REF_TEST(eax,eax);
 if(eax) {
  ecx=MEM32(MEM32(eax)-4);ecx=LOCATOR(ecx)->offset;REF_TEST(ecx,ecx);
  if(ecx) {
   edx=eax;REF_CMP(edx,ecx);edx-=ecx;
   ecx=MEM32(MEM32(edx)-4);REF_TEST(ecx,ecx);
   if(ecx) {REF_CMP(LOCATOR(ecx)->type,0x00ED47C0u);if(LOCATOR(ecx)->type==0x00ED47C0u)eax=edx;}
  }
 }
 esp+=4;RECOMP_EXIT_P(0x17u);
}
'''

def adapt(source,edition,fixture=False):
 mapping=dict(zip(FACTS['toe'],FACTS[edition]))
 # Exact call-site identities in matched original functions, not an edition delta.
 ranges=[(0x4FA280,0x4FA2E6,0),(0xC05AC0,0xC05B04,1),(0xC05B10,0xC05B54,2),
         (0x731290,0x7312D7,3),(0x611AA0,0x611AC5,4),(0x61F290,0x61F2A3,5)]
 def address(m):
  value=m[1];v=int(value,16)
  for start,end,i in ranges:
   if start<=v<=end:
    offset=v-start
    if edition=='hof' and i==0 and offset>=0x3B:offset-=0x1F
    return f'{int(FACTS[edition][i],16)+offset:08X}'
  return mapping.get(value,value)
 source=re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])',address,source)
 if edition=='hof':
  source=source.replace('/* HOF_BASE_HELPER */',BASE_HELPER)
  begin=source.index('        /* BASE_CONVERSION_BEGIN */');end=source.index('        /* BASE_CONVERSION_END */',begin)+len('        /* BASE_CONVERSION_END */')
  source=source[:begin]+'''        edx=0;REF_TEST(0,0);ecx=eax;
        RECOMP_CALL_P(reference_hof_base,0x17u,0x17u,0,0x0047B357u);
        RECOMP_FLAGS_IN();'''+source[end:]
 if fixture:
  source=source.replace('0x'+FACTS[edition][8],'0x00032000').replace('0x'+FACTS[edition][9],'0x00032040')
 return source

HARNESS=r'''
enum { SLOT=0x1400,NEW=0x6000,OLD=0x7000,RAWVT=0x8100,BASEVT=0x8000,
       RAWCOL=0x9100,BASECOL=0x9000,NEWVB=0xA000,OLDVB=0xA100,TD=0x32000,TILETD=0x32040 };
static unsigned tile,reading,shape,alias,mutation;static uint32_t new_object,slot;
static void callback(unsigned kind,unsigned pop) {
 assert(++callbacks<16);record(kind);
 uint32_t result=0xA5000000u|kind;
 if(kind==1) {
  assert(g_ecx==ARCHIVE);result=0x98760000u|reading;
  if(mutation&1)MEM32(ARCHIVE)=VTABLE+0x100;
 }
 if(kind==2) {
  assert(g_ecx==ARCHIVE);result=new_object;
  if(mutation&2)MEM32(slot)=0;
 }
 if(kind==3) {
  assert(g_ecx==ARCHIVE);
  MEM32(0x1600)=MEM32(g_esp+4);
  if(mutation&4)MEM32(slot)=0;
 }
 if(kind==4) {
  assert(MEM32(g_esp+4)==new_object&&MEM32(g_esp+8)==0);
  assert(MEM32(g_esp+12)==TD&&MEM32(g_esp+16)==TILETD&&MEM32(g_esp+20)==0);
  result=(mutation&8)?0:NEW;
  if(mutation&16)MEM32(slot)=0;
 }
 if(kind==5) {assert(MEM32(g_esp+4)==0xFFFFFu);MEM32(0x1604)=g_ecx;}
 g_eax=result;g_ecx=0xBC000000u|callbacks;g_edx=0xEF000000u|callbacks;
 g_flag_k=FK_TEST;g_flag_a=result;g_flag_b=kind;g_flag_cf=0;
 g_st[callbacks&7u]+=0.5;g_st_i64[callbacks&7u]^=0x1133557799ll;
 g_mm[callbacks&7u]^=0xABCDEF0011223344ull;((uint32_t *)g_xmm)[callbacks&31u]^=0x11FF5522;
 g_fp_top=(g_fp_top+1)&7;g_fpu_cw^=0x400;g_mxcsr^=0x2000;void_fpu_cmp^=3;
 g_esp+=pop;
}
static void mode(void){callback(1,4);}static void read_object(void){callback(2,4);}
static void write_object(void){callback(3,8);}static void dynamic_cast_callback(void){callback(4,4);}
static void destroy_callback(void){callback(5,8);}
recomp_func_t void_resolve(uint32_t address) {
 switch(address){case 1:return mode;case 2:return read_object;case 3:return write_object;default:assert(0);return 0;}
}
#include "names.h"
#include "oracle.h"
void ORIGINAL_OBJECT(void){++original_calls;oracle_object();}
void ORIGINAL_TILE(void){++original_calls;oracle_tile();}
#include "actual.h"
static void setup(unsigned t,unsigned rd,unsigned sh,unsigned al,unsigned change,unsigned count) {
 tile=t;reading=rd;shape=sh;alias=al;mutation=change;memset(memory,0xCD,sizeof memory);
 g_eax=0xA1234567;g_ecx=ARCHIVE;g_edx=0xB456789A;g_ebx=0xC3456789;
 g_esp=STACK;g_ebp=0x567890AB;g_esi=0x11223344;g_edi=0x778899AA;
 g_flag_k=FK_ADD;g_flag_a=1;g_flag_b=17;g_flag_cf=1;
 g_backedges=3;g_cur_func=0x11111111;g_enter_idx=0;memset(g_enter_trace,0,sizeof g_enter_trace);
 for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=(double)i+0.25;g_st_i64_win[i]=0x1122334400000000ll+i;}
 for(unsigned i=0;i<8;i++)g_mm[i]=0xABCDEF0011223344ull+i;
 for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=0x12340000+i;
 g_fp_sp=120;g_fp_top=5;g_fpu_cw=0xB7F;g_mxcsr=0x3F80;void_fpu_cmp=0x41;
 MEM32(STACK)=0x91919191;MEM32(ARCHIVE)=VTABLE;
 for(unsigned off=0;off<=0x100;off+=0x100){MEM32(VTABLE+off+0x3C)=1;MEM32(VTABLE+off+0x38)=2;MEM32(VTABLE+off+0x34)=3;}
 MEM32(NEW)=BASEVT;MEM32(BASEVT-4)=(sh==3)?0:BASECOL;
 MEM32(BASECOL+4)=0;MEM32(BASECOL+12)=(sh==4)?0x31415926:(t?TILETD:TD);
 MEM32(NEW+32)=RAWVT;MEM32(RAWVT-4)=RAWCOL;MEM32(RAWCOL+4)=sh?32:0;
 new_object=sh==5?0:(sh?NEW+32:NEW);
 if(t) {
  MEM32(NEW+4)=NEWVB;MEM32(NEWVB+4)=64;MEM32(NEW+72)=count;
  MEM32(NEW+36)=NEWVB;MEM32(NEW+104)=count;
  MEM32(OLD+4)=OLDVB;MEM32(OLDVB+4)=64;MEM32(OLD+72)=count;
 } else {MEM32(NEW+4)=count;MEM32(NEW+36)=count;MEM32(OLD+4)=count;}
 slot=al==0?SLOT:al==1?(t?NEW+72:NEW+4):al==2?(t?OLD+72:OLD+4):STACK+32;
 MEM32(slot)=(count&0x80000000u)?0:((change&32)?new_object:OLD);MEM32(STACK+4)=slot;
 callbacks=events=yields=0;recomp_yield_hook=0;
}
'''
COMPARE=r'''
static int compare(unsigned t,unsigned rd,unsigned sh,unsigned al,unsigned change,unsigned count) {
 setup(t,rd,sh,al,change,count);if(t)oracle_tile();else oracle_object();
 memcpy(saved_memory,memory,sizeof memory);saved_final=capture();unsigned nevents=events;
 memcpy(saved_events,log_events,events*sizeof log_events[0]);
 setup(t,rd,sh,al,change,count);if(t)void_reference_native_tile();else void_reference_native_object();
 state result=capture();
 int bad=memcmp(memory,saved_memory,sizeof memory)||memcmp(&saved_final,&result,sizeof result)||!same_events(nevents);
 if(bad){fprintf(stderr,"REFERENCE DIFFERENTIAL FAIL case=%u tile=%u read=%u shape=%u alias=%u mutation=%u count=%08x events=%u/%u\n",case_number,t,rd,sh,al,change,count,nevents,events);
  for(unsigned i=0;i<8;i++)fprintf(stderr,"r%u %08x/%08x ",i,saved_final.regs[i],result.regs[i]);fputs("\n",stderr);
  for(unsigned i=0;i<nevents&&i<events;i++)if(!same_event(&saved_events[i],&log_events[i])){fprintf(stderr,"event%u kind%u/%u\n",i,saved_events[i].kind,log_events[i].kind);break;}
  return 1;}
 for(unsigned i=0;i<events;i++){free(saved_events[i].guest_memory);free(log_events[i].guest_memory);}return 0;
}
int main(int argc,char **argv) {
 unsigned counts[]={0,1,2,0xFFFFF,0x100000,0x100001,0x7FFFFFFF,0x80000000,0xFFFFFFFF};
 unsigned changes[]={0,1,2,4,8,16,3,7,15,31,32,33,63};
 if(argc==1)for(unsigned t=0;t<2;t++)for(unsigned rd=0;rd<2;rd++)for(unsigned sh=0;sh<6;sh++)
 for(unsigned al=0;al<4;al++)for(unsigned c=0;c<9;c++)for(unsigned p=0;p<sizeof changes/sizeof changes[0];p++){
  ++case_number;if(compare(t,rd,sh,al,changes[p],counts[c]))return 1;}
 remove("native-references");int native_mode=argc>1&&!strcmp(argv[1],"native");
 if(argc>1){FILE *f=fopen("native-references","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
 setup(0,0,0,0,0,2);logs=original_calls=0;void_reference_native_object_dispatch();assert(original_calls==(native_mode?0:1)&&logs==1);
 FILE *f=fopen("native-references","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
 setup(1,0,0,0,0,2);void_reference_native_tile_dispatch();assert(original_calls==(native_mode?0:2)&&logs==1);remove("native-references");
 printf("PASS %u reference cases; cached mode%d\n",case_number,native_mode);return 0;
}
'''

class ReferenceCandidate(unittest.TestCase):
 def check(self,edition,protocol=False,trace=True,mutant=None):
  facts=FACTS[edition];proof=json.loads(r'''{
  "toe": {
    "image_sha256": "6502a8c4cd0e03e9ce43b474bcb4a85acb8b8bf5050d56317e93c8f13fff50bd",
    "functions": {
      "00611AA0": {
        "unit": "game_0171.c",
        "length": 38,
        "sha256": "7df89f334ad2a6d12f86d178422e1739b12061b00c1f5b6eea6a081ddf613280",
        "bytes": "8b4c240485c9741b834104ff8b4104a9ffff0f00750dc7442404ffff0f00e90d472b00c20400",
        "direct_calls": [
          {
            "site": "00611ABE",
            "opcode": 233,
            "target": "008C61D0",
            "bytes": "e90d472b00"
          }
        ]
      },
      "0061F290": {
        "unit": "game_0173.c",
        "length": 18,
        "sha256": "2c0326b3b6e948c7913de646824b2ccd51fe61e4f1e236a6448ae078af9c6a60",
        "bytes": "85c9750333c0c38b41048b50048d440a04c3",
        "direct_calls": []
      },
      "00731290": {
        "unit": "game_0260.c",
        "length": 72,
        "sha256": "07ddbb4683cc1aa51eaab9b035a17ec129813eb416a38dd39bf99bb6e2d0118e",
        "bytes": "8b54240485d28b018911740f8b4a048b490483441108018d4c110485c074268b50048b4a0483440108ff8d4c01048b4104a9ffff0f00750dc7442404ffff0f00e9fb4e1900c20400",
        "direct_calls": [
          {
            "site": "007312D0",
            "opcode": 233,
            "target": "008C61D0",
            "bytes": "e9fb4e1900"
          }
        ]
      },
      "00C05B10": {
        "unit": "game_0627.c",
        "length": 69,
        "sha256": "df0ed75b620ffe19adfea6640b0d7d90e7e660551d61423a17c6562e11b2231f",
        "bytes": "85c9750533c0c204008b018b40fc8b500485d28bc1742b2bc28b108b52fc85d27409817a0cc08ff70074176a0068c08ff70068c072f2006a0051e8adbe100083c414c20400",
        "direct_calls": [
          {
            "site": "00C05B4A",
            "opcode": 232,
            "target": "00D119FC",
            "bytes": "e8adbe1000"
          }
        ]
      },
      "004FA280": {
        "unit": "game_0092.c",
        "length": 103,
        "sha256": "ee12bdbceee6a4a5a0dbd6ac19a1d052312acba9dbef61f8c0d45471f373a1f2",
        "bytes": "568bf18b06ff503c84c074498b168bceff523885c074248b088b49fc8b510485d274188bc82bca8b118b52fc85d2740b817a0cc072f20075028bc185c08b4c24088b1189017404834004015e89542404e9cb7711008b4c24088b118b06528bceff50345ec20400",
        "direct_calls": [
          {
            "site": "004FA2D0",
            "opcode": 233,
            "target": "00611AA0",
            "bytes": "e9cb771100"
          }
        ]
      },
      "00C05AC0": {
        "unit": "game_0627.c",
        "length": 69,
        "sha256": "2abbb0d85c96c6e6ceba2e0bbef630cbce49018f3a3376a13151b06957e5b39d",
        "bytes": "568bf18b06ff503c84c074208b168bceff52386a0033d28bc8e8320000008b4c240850e8a8b7b2ff5ec204008b4424088b08578b3ee89697a1ff508bceff57345f5ec20400",
        "direct_calls": [
          {
            "site": "00C05AD9",
            "opcode": 232,
            "target": "00C05B10",
            "bytes": "e832000000"
          },
          {
            "site": "00C05AE3",
            "opcode": 232,
            "target": "00731290",
            "bytes": "e8a8b7b2ff"
          },
          {
            "site": "00C05AF5",
            "opcode": 232,
            "target": "0061F290",
            "bytes": "e89697a1ff"
          }
        ]
      }
    }
  },
  "vanilla": {
    "image_sha256": "2b4e8bd32bd929e8caf1d53f74bc4aa6be56c362080549b9dc675d4e88289950",
    "functions": {
      "0065B5D0": {
        "unit": "game_0200.c",
        "length": 18,
        "sha256": "2c0326b3b6e948c7913de646824b2ccd51fe61e4f1e236a6448ae078af9c6a60",
        "bytes": "85c9750333c0c38b41048b50048d440a04c3",
        "direct_calls": []
      },
      "006CD9F0": {
        "unit": "game_0236.c",
        "length": 72,
        "sha256": "827bd923a3592dd7f387ceeccca6f13798839cf08749a38f2cf3b3188ebeca06",
        "bytes": "8b54240485d28b018911740f8b4a048b490483441108018d4c110485c074268b50048b4a0483440108ff8d4c01048b4104a9ffff0f00750dc7442404ffff0f00e91b2b4500c20400",
        "direct_calls": [
          {
            "site": "006CDA30",
            "opcode": 233,
            "target": "00B20550",
            "bytes": "e91b2b4500"
          }
        ]
      },
      "00961930": {
        "unit": "game_0437.c",
        "length": 38,
        "sha256": "67f999a795089e4a6fb8fa70d10bbc592c810ea10c1aec3150e74a79dc5d33b5",
        "bytes": "8b4c240485c9741b834104ff8b4104a9ffff0f00750dc7442404ffff0f00e9fdeb1b00c20400",
        "direct_calls": [
          {
            "site": "0096194E",
            "opcode": 233,
            "target": "00B20550",
            "bytes": "e9fdeb1b00"
          }
        ]
      },
      "00A44C30": {
        "unit": "game_0503.c",
        "length": 69,
        "sha256": "fee4c2e83deb20c33dbcb9a62d6fe98a3c1b3c5c8b044378bec3df521f7fce2e",
        "bytes": "85c9750533c0c204008b018b40fc8b500485d28bc1742b2bc28b108b52fc85d27409817a0c48ccf20074176a006848ccf20068046af0006a0051e82f8a1c0083c414c20400",
        "direct_calls": [
          {
            "site": "00A44C6A",
            "opcode": 232,
            "target": "00C0D69E",
            "bytes": "e82f8a1c00"
          }
        ]
      },
      "00459100": {
        "unit": "game_0037.c",
        "length": 103,
        "sha256": "ffea1e016f64e359645167feda3ff54b45b604cf6e71036d4c98580ed1a34456",
        "bytes": "568bf18b06ff503c84c074498b168bceff523885c074248b088b49fc8b510485d274188bc82bca8b118b52fc85d2740b817a0c046af00075028bc185c08b4c24088b1189017404834004015e89542404e9db8750008b4c24088b118b06528bceff50345ec20400",
        "direct_calls": [
          {
            "site": "00459150",
            "opcode": 233,
            "target": "00961930",
            "bytes": "e9db875000"
          }
        ]
      },
      "00A44BE0": {
        "unit": "game_0503.c",
        "length": 69,
        "sha256": "cc0420cc7e1e51fea8e9df6978cfc1f0251cfc324fff9582d74fe0f080bdc4af",
        "bytes": "568bf18b06ff503c84c074208b168bceff52386a0033d28bc8e8320000008b4c240850e8e88dc8ff5ec204008b4424088b08578b3ee8b669c1ff508bceff57345f5ec20400",
        "direct_calls": [
          {
            "site": "00A44BF9",
            "opcode": 232,
            "target": "00A44C30",
            "bytes": "e832000000"
          },
          {
            "site": "00A44C03",
            "opcode": 232,
            "target": "006CD9F0",
            "bytes": "e8e88dc8ff"
          },
          {
            "site": "00A44C15",
            "opcode": 232,
            "target": "0065B5D0",
            "bytes": "e8b669c1ff"
          }
        ]
      }
    }
  },
  "hof": {
    "image_sha256": "bad3b0c010b9d85193811bdf8ffa2afab30b865ea924c480ff7aac78a1e73140",
    "functions": {
      "00456050": {
        "unit": "game_0030.c",
        "length": 44,
        "sha256": "6674a10125b2dcad40a3e781f48171f6013c16ceb241e03e788f1381ecbbfafc",
        "bytes": "8bc185c07501c38b088b49fc8b490485c974188bd02bd18b0a8b49fc85c9740b81790cc047ed0075028bc2c3",
        "direct_calls": []
      },
      "004C04D0": {
        "unit": "game_0063.c",
        "length": 18,
        "sha256": "2c0326b3b6e948c7913de646824b2ccd51fe61e4f1e236a6448ae078af9c6a60",
        "bytes": "85c9750333c0c38b41048b50048d440a04c3",
        "direct_calls": []
      },
      "006AF170": {
        "unit": "game_0223.c",
        "length": 72,
        "sha256": "f33eaf373f17547bef58236af0c1191639bd94ff270ffea6e5df04cb7ebec538",
        "bytes": "8b54240485d28b018911740f8b4a048b490483441108018d4c110485c074268b50048b4a0483440108ff8d4c01048b4104a9ffff0f00750dc7442404ffff0f00e9ab2f3500c20400",
        "direct_calls": [
          {
            "site": "006AF1B0",
            "opcode": 233,
            "target": "00A02160",
            "bytes": "e9ab2f3500"
          }
        ]
      },
      "00756120": {
        "unit": "game_0278.c",
        "length": 38,
        "sha256": "688ae402efe45bb69d7ae6ae3bf62080add64fb1f0d5b4b15f7be7ec26184b93",
        "bytes": "8b4c240485c9741b834104ff8b4104a9ffff0f00750dc7442404ffff0f00e91dc02a00c20400",
        "direct_calls": [
          {
            "site": "0075613E",
            "opcode": 233,
            "target": "00A02160",
            "bytes": "e91dc02a00"
          }
        ]
      },
      "008078F0": {
        "unit": "game_0333.c",
        "length": 69,
        "sha256": "f7080f89cdae84d83e613b84ba2c07a8b5a336fdd52a1c16665ebfec883d8d19",
        "bytes": "85c9750533c0c204008b018b40fc8b500485d28bc1742b2bc28b108b52fc85d27409817a0c40feee0074176a006840feee0068c047ed006a0051e89f22400083c414c20400",
        "direct_calls": [
          {
            "site": "0080792A",
            "opcode": 232,
            "target": "00C09BCE",
            "bytes": "e89f224000"
          }
        ]
      },
      "0047B340": {
        "unit": "game_0042.c",
        "length": 72,
        "sha256": "ff3460f73fbabfd769f2cbfae6b0f156232480faec2767c95274580f1d3e2d99",
        "bytes": "568bf18b06ff503c84c0742a8b168bceff523833d28bc8e8f4acfdff85c08b4c24088b1189017404834004015e89542404e9aaad2d008b4c24088b118b06528bceff50345ec20400",
        "direct_calls": [
          {
            "site": "0047B357",
            "opcode": 232,
            "target": "00456050",
            "bytes": "e8f4acfdff"
          },
          {
            "site": "0047B371",
            "opcode": 233,
            "target": "00756120",
            "bytes": "e9aaad2d00"
          }
        ]
      },
      "008078A0": {
        "unit": "game_0333.c",
        "length": 69,
        "sha256": "be453cc8248b5899599976b145376c4ea00be944884545e4180342808e62894d",
        "bytes": "568bf18b06ff503c84c074208b168bceff52386a0033d28bc8e8320000008b4c240850e8a878eaff5ec204008b4424088b08578b3ee8f68bcbff508bceff57345f5ec20400",
        "direct_calls": [
          {
            "site": "008078B9",
            "opcode": 232,
            "target": "008078F0",
            "bytes": "e832000000"
          },
          {
            "site": "008078C3",
            "opcode": 232,
            "target": "006AF170",
            "bytes": "e8a878eaff"
          },
          {
            "site": "008078D5",
            "opcode": 232,
            "target": "004C04D0",
            "bytes": "e8f68bcbff"
          }
        ]
      }
    }
  }
}''');catalog={}
  for path in (generated_root(edition)/'game-x86').glob('game_*.c'):
   text=path.read_text()
   for va in (*facts[:6],*(['00456050'] if edition=='hof' else [])):
    if 'void sub_'+va+'(void) {' in text:catalog[va]=path.name
  pe=pefile.PE(str(generated_root(edition)/'input/H5_Game.exe'),fast_load=True)
  for i,name in ((8,b'.?AVCObjectBase@@\0'),(9,b'.?AVCHeroTraceTile@NWorld@@\0')):
   self.assertEqual(pe.get_data(int(facts[i],16)+8-pe.OPTIONAL_HEADER.ImageBase,len(name)),name)
  self.assertEqual(hashlib.sha256((generated_root(edition)/'input/H5_Game.exe').read_bytes()).hexdigest(),proof[edition]['image_sha256'])
  for va,row in proof[edition]['functions'].items():
   self.assertEqual(hashlib.sha256(pe.get_data(int(va,16)-pe.OPTIONAL_HEADER.ImageBase,row['length'])).hexdigest(),row['sha256'])
   for call in row['direct_calls']:
    instruction=pe.get_data(int(call['site'],16)-pe.OPTIONAL_HEADER.ImageBase,5)
    self.assertEqual(instruction.hex(),call['bytes'])
    self.assertEqual((int(call['site'],16)+5+int.from_bytes(instruction[1:],'little',signed=True))&0xFFFFFFFF,int(call['target'],16))
  oracles=[]
  for va,unit in catalog.items():
   source=transformed(edition,'sub_'+va,unit);plan=Plan(protocol_root(edition)/'x87.json',edition=edition)
   self.assertEqual(apply_x87(source.encode(),plan),source.encode());oracles.append(source)
  oracle='\n'.join(oracles)
  for i,va in enumerate(facts[:6]):oracle=oracle.replace('sub_'+va,('oracle_object','oracle_tile','oracle_cast','oracle_assign','oracle_release','oracle_base')[i])
  if edition=='hof':oracle=oracle.replace('sub_00456050','oracle_hof_base')
  oracle=oracle.replace('0x'+facts[8],'0x00032000').replace('0x'+facts[9],'0x00032040')
  decl='\n'.join('void '+s+'(void);' for s in re.findall(r'^void (oracle_\w+)\(void\)',oracle,re.M))+'\n'
  native=adapt((ROOT/'android/host/object_refs_native.c').read_text(),edition,fixture=True)
  if mutant:native=mutant(native)
  names=f'#define ORIGINAL_OBJECT sub_{facts[0]}\n#define ORIGINAL_TILE sub_{facts[1]}\n#define sub_{facts[6]} destroy_callback\n#define sub_{facts[7]} dynamic_cast_callback\n'
  prefix=PREFIX if trace else PREFIX.replace('#define RECOMP_TRACE','/* Disabled. */')
  # Declarations precede the independently extracted original bodies.
  text=prefix+HARNESS+EVENT_COMPARE+COMPARE
  suffix=('-protocol' if protocol else '')+('-notrace' if not trace else '')+('-mutant' if mutant else '')
  out=HERE/('probe-'+edition+suffix);out.mkdir(parents=True,exist_ok=True)
  files={'probe.c':text,'oracle.h':decl+oracle,'names.h':names,'actual.h':native,
   'native_mode.h':(ROOT/'android/host/native_mode.h').read_text(),
   'host.h':'#include "recomp_types.h"\n','recomp_types.h':pc_header((ROOT/'android/runtime/recomp_types.h').read_text())}
  for name,value in files.items():(out/name).write_text(value,encoding='utf-8')
  env,linker=environment('x64');flags=[CLANG,'/nologo','/W0','/O2','/std:c11','/D_CRT_SECURE_NO_WARNINGS','/clang:--target=x86_64-pc-windows-msvc','/clang:-fwrapv','/clang:-fno-strict-aliasing','/clang:-ffp-contract=off']
  if protocol:flags.append('/DRECOMP_PROTOCOL_CHECK')
  command([*flags,'/c','probe.c','/Foprobe.obj'],out,env);command([linker,'/nologo','probe.obj','/OUT:probe.exe','/STACK:1048576'],out,env)
  result=command([out/'probe.exe'],out,env,check=False)
  if mutant:
   self.assertNotEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('REFERENCE DIFFERENTIAL FAIL',result.stderr);return
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  mode=command([out/'probe.exe','native'],out,env,check=False);self.assertEqual(mode.returncode,0,mode.stdout+mode.stderr)
  for invalid in ('0','01','1\r\n','1\nextra','2'):
   result_invalid=command([out/'probe.exe',invalid],out,env,check=False);self.assertEqual(result_invalid.returncode,0,result_invalid.stdout+result_invalid.stderr)
  (out/'receipt.json').write_text(json.dumps({'edition':edition,'native_sha256':hashlib.sha256(native.encode()).hexdigest(),'oracle_sha256':hashlib.sha256(oracle.encode()).hexdigest(),'protocol':protocol,'trace':trace,'result':result.stdout,'device_tested':False},indent=2)+'\n')
  print(edition+suffix,result.stdout.strip())
 def test_three_editions(self):
  for edition in FACTS:
   with self.subTest(edition=edition):self.check(edition)
 def test_protocol(self):self.check('toe',protocol=True)
 def test_no_trace(self):self.check('toe',trace=False)
 def test_reject_count_masked_before_decrement(self):self.check('toe',mutant=lambda s:s.replace('BASE(ecx)->references--;','BASE(ecx)->references=(BASE(ecx)->references-1)&0xFFFFFu;'))
 def test_reject_static_cast_on_type_mismatch(self):self.check('toe',mutant=lambda s:s.replace('if(!compatible) {','if(0) {'))

if __name__=='__main__':unittest.main()
