"""Run the actual touch adapter against guest-memory and engine-call spies."""
import unittest
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define ADDR(p) (memory + (uint32_t)(p))
#define MEM32(p) (*(uint32_t *)ADDR(p))
#define MEM8(p) (*(uint8_t *)ADDR(p))
#define MEMF(p) (*(float *)ADDR(p))
typedef void (*void_fn)(void);
static uint32_t mock_screen = 0x4000;
static int downs, ups, doubles, hovers, picks, commands, evaluations, releases, cancels, cameras;
static int ui_pans, last_camera_kind;
static int force_ui, busy, pick_available = 1, change_on_down;
static int inspections,inspection_changes_screen,held_details;
static int previews, placement_begins, placement_moves, placement_ends, placement_cancels, reserve_slot = -1;
static int double_object, same_selection, owned, town_visible, town_views, town_selections, ghost_views;
static int announcement_visible, announcement_probes, announcement_actions, announcement_changes_screen;
static int picked_active, cast_available, combat_shortcuts, shortcut_effect, clear_target_during_prepare, combat_pick_changes_screen;
static int context_ctors, context_dtors, cast_changes_screen;
static int book_type, book_picks, book_actions, book_wm_consumed, book_pick_changes_screen, book_pick_closes;
static int book_missing_picker, book_missing_action, book_probes, book_swipes;
static uint32_t book_descriptor, book_probe_descriptor, last_book_swipe;
static uint32_t atb_unit, atb_unit2;
static int atb_lookups, minimap_hit, hero_moving, hero_stops;
static int town_actions,town_blocked,town_busy;
static int town_portrait_hits,town_portrait_opens,town_portrait_changes_screen;
static uint32_t town_portrait_pick;
static int dnd_available,dnd_blank,dnd_overlay,dnd_child,dnd_invalid,dnd_probe_changes_screen,dnd_hidden;
static int dnd_probes,dnd_downs,dnd_ups,dnd_moves,dnd_doubles,dnd_cancels,dnd_pickups,dnd_drops,dnd_restores;
static float dnd_down_x,dnd_down_y;
static int mentor_selects,mentor_confirms,mentor_changes_screen,ui_overlay,ghost_selects,ghost_moves;
static int loading_stage,loading_cleanup,loading_queued,loading_no_command;
static float last_x, last_y;
static double g_st[8];
static int g_fp_top, list_available, mock_horizontal, scroll_sets, scroll_notifies;
static float scroll_value;
static double fp_pop_impl(double *st, int *depth) { double value=st[0]; memmove(st,st+1,7*sizeof *st); st[7]=0; --*depth; return value; }
static uint32_t g_eax, g_esp, g_edx, g_ecx;
typedef struct {uint32_t eax,esp,edx,ecx;} void_regs;
static void void_regs_save(void_regs *r){*r=(void_regs){g_eax,g_esp,g_edx,g_ecx};}
static void void_regs_load(const void_regs *r){g_eax=r->eax;g_esp=r->esp;g_edx=r->edx;g_ecx=r->ecx;}
static uint64_t mock_now_ns = 1000000000ull;
static int physical_seen;
static uint32_t physical_x=500, physical_y=250;
static uint64_t physical_moved_ns;
int void_input_pointer(uint32_t *x,uint32_t *y,uint64_t *moved) {
    *x=physical_x;*y=physical_y;*moved=physical_moved_ns;return physical_seen;
}
void void_input_screen_size(int *w,int *h) {*w=1280;*h=800;}
static int key_down[256];
void void_input_key(uint32_t vk,int down) {key_down[vk&255]=down;}
static float cursor_offset_x,cursor_offset_y;
static int show_touch_cursor;
float void_port_cursor_offset(int vertical) {return vertical?cursor_offset_y:cursor_offset_x;}
int void_port_touch_cursor(void) {return show_touch_cursor;}
enum { VOID_PERF_FILE_OPEN, VOID_PERF_FILE_MAP, VOID_PERF_FIND, VOID_PERF_FILE_READ, VOID_PERF_SHADER_COMPILE,
       VOID_PERF_PROGRAM_LINK, VOID_PERF_PROGRAM_CACHE, VOID_PERF_TEXTURE, VOID_PERF_COUNT };
static uint64_t void_perf_now_ns(void) { return mock_now_ns; }
static uint64_t void_perf_calls(int kind) { (void)kind; return 0; }
static void void_log(const char *format, ...) { (void)format; }
static int lifted_tracker_calls, lifted_timeout_calls, camera_pose_gets, camera_pose_sets, tilts;
static float last_pose_pitch, last_pose[10];
static int last_pose_kind;
void sub_008863A0_lifted(void) { ++lifted_tracker_calls; g_esp += 16; }
void sub_006B92E0_lifted(void) { ++lifted_timeout_calls; g_eax = 250; g_esp += 4; }
static int cursor_draws;
static int edit_kind, text_arms, text_cancelled;
static uint32_t focused_field;
static int text_chars,text_keys;
void void_touch_text_arm(void) {++text_arms;}
uint32_t void_touch_text_cancel(void) {return (uint32_t)++text_cancelled;}
static void_fn cursor_draw_hook;
static void mock_log(const char *format, ...) { (void)format; }
#define VLOG(...) mock_log(__VA_ARGS__)
static uint32_t void_galloc(uint32_t size) { assert(size <= 512); return 0x10000; }
static void void_gfree(uint32_t va) { (void)va; }
static int void_verbose = 0;
static int void_vm_readable(uint32_t p, uint32_t n) { return p >= 0x100 && (uint64_t)p+n <= sizeof memory; }
static int void_vm_writable(uint32_t p, uint32_t n) { return void_vm_readable(p,n); }
static void dummy(void) { g_eax=0x1234; g_esp+=4; }
static void original_draw(void) { ++cursor_draws; g_eax=0xD00D; g_esp+=8; }
static void_fn void_dispatch_find(uint32_t va) {
    if(va==0x7148E0)return NULL; /* Scenario row refresh has its own fixture. */
    if ((book_missing_picker && (va==0x683450 || va==0x67BAB0)) || (book_missing_action && va==0x493ED0)) return NULL;
    return va==0x836440 ? original_draw : va ? dummy : NULL;
}
static void void_dispatch_add(uint32_t va, void_fn fn) {
    assert(fn);if(va==0x836440)cursor_draw_hook=fn;else assert(va==0x835C90);
}
void void_touch_camera_init(void) {}
int void_touch_ui_pan(uint32_t screen,float dx,float dy) {assert(screen==0x4000 && isfinite(dx+dy));++ui_pans;return 1;}
static uint32_t void_call_guest(uint32_t va, int n, const uint32_t *args, int pops) {
    if (va == 0x8385A0) { assert(!n && pops); return mock_screen ? 0x7000 : 0; }
    if(va==0xAC3590) {assert(!n && pops && loading_stage==2);loading_stage=3;return loading_no_command ? 0 : 0x73000;}
    assert(va == 0xD119FC && n == 5 && !pops);
    if (args[2] == 0xF2DAF4) {
        if(args[3]==0xF34164) return minimap_hit && args[0]==0x6800 ? 0x6A00 : 0;   /* NUI::CAdvMinimap */
        if(args[3]==0xF786F0) return MEM32(args[0])==0xE85E94 ? args[0]-0x17C : 0;
        if(args[3]==0xF2DC80) return 0;   /* CWindowSlider: none here */
        if(args[3]==0xF2DA88) return args[0]==0x6044 ? 0x6000 : 0;
        if(args[0]==0x6810 || args[0]==0x6820 || args[0]==0x6900)return 0;
        assert(args[0] == 0x6800);
        if(args[3]==0xF7A234) return edit_kind==1 ? 0x30000 : 0;
        if(args[3]==0xF7AE0C) return edit_kind==2 ? 0x31000 : 0;
        assert(args[3] == 0xF44B08);
        return list_available ? 0xB000 : 0;
    }
    assert(args[0] == 0x7024);
    assert(args[1] == 0 && args[2] == 0xF272C0 && args[3] == 0xF323A8 && args[4] == 0);
    return mock_screen;
}
static uint32_t void_call_guest_this(uint32_t va, uint32_t self, int n, const uint32_t *args) {
    /* A held world object's details (UI root +70 at the published point, forced). */
    if(va==0x487A84) {
        assert(self==0x6000&&n==2&&args[1]==1);++held_details;
        assert(MEMF(0x101E0)==MEMF(args[0])&&MEMF(0x101E4)==MEMF(args[0]+4));return 0;
    }
    if(va==0x487A80) {
        assert(self==0x6000&&n==2&&args[1]==1);++inspections;
        assert(MEMF(0x101E0)==MEMF(args[0])&&MEMF(0x101E4)==MEMF(args[0]+4));
        if(inspection_changes_screen)mock_screen=0x5000;return 0;
    }
    if(va==0x6B2830) {
        assert(self==0x4000 && !n && !MEM32(0x41A4) && loading_stage==0);
        loading_stage=1;++loading_cleanup;return 0;
    }
    if(va==0x689390) {assert(self==1 && !n && loading_stage==1);loading_stage=2;return 0;}
    if(va==0x838C10) {assert(self==0x73000 && !n && loading_stage==3);loading_stage=4;++loading_queued;return 0;}
    if(va==0x48005C) {
        assert((self==0x6800 || self==0x6820) && n==1);
        if(MEM32(0x4000)==0xE4094C && MEMF(args[0])<700) return 0xCCDD00;
        if(MEM32(0x4000)==0xE2A64C) return 0xCCDD00u | (uint32_t)((town_portrait_hits & (self==0x6800 ? 1 : 2))!=0);
        return 0xCCDD01;
    }
    if(va==0x6C15D0) {
        assert(self==0x4000 && n==1 && MEMF(args[0])==731 && MEMF(args[0]+4)==333);
        assert(MEM32(0x47DC)==6 && !MEM32(0x47E8));++mentor_selects;MEM32(0x47E4)=23;
        if(mentor_changes_screen)mock_screen=0x5000;return 0xCCDD01;
    }
    if(va==0x6C0FB0) {assert(self==0x4000 && !n && MEM32(0x47E4)==23);++mentor_confirms;return 0;}
    if(va==0x78FDF0 || va==0x78FBC0) {
        assert(self==0x4000 && n==1);
        if(va==0x78FDF0){assert(args[0]==0x10140 && MEM32(args[0]+0x24)==(900u|(400u<<15)));++ghost_selects;}
        else {assert(MEMF(args[0])==771 && MEMF(args[0]+4)==341);++ghost_moves;}
        return 0;
    }
    if(va==0x813DE0) {
        assert(self==0x60000 && n==2 && args[1]==1);++dnd_probes;
        if(dnd_probe_changes_screen)mock_screen=0x5000;
        return dnd_blank || dnd_hidden ? 0 : 0x70000;   /* the probe wants a visible window */
    }
    if(va==0x470024) {assert(self==0x71000 && n==1);return dnd_blank ? 0 : dnd_hidden ? 0x6810 : 0x6800;}   /* slot map: nothing over a blank point; a hidden empty cell's icon */
    if(va==0x4700D8) {assert(self==0x6810 && !n);return 0x6800;}
    if(va==0x813BC0 || va==0x813C60 || va==0x813B20 || va==0x813D00 || va==0x813DA0) {
        assert(self==0x60000 && n==(va==0x813DA0 ? 0 : 1));
        uint32_t state=MEM32(0x60100);
        if(va==0x813BC0) {
            ++dnd_downs;assert(MEMF(args[0])==dnd_down_x && MEMF(args[0]+4)==dnd_down_y);
            if(state==0xE476F4)MEM32(0x60100)=0xE47728;
        } else if(va==0x813D00)++dnd_doubles;
        else if(va==0x813B20) {++dnd_moves;if(state==0xE47728){MEM32(0x60100)=0xE4775C;++dnd_pickups;}}
        else if(va==0x813DA0) {++dnd_cancels;if(state==0xE4775C)++dnd_restores;MEM32(0x60100)=0xE476F4;}
        else {
            ++dnd_ups;
            if(state==0xE47728){MEM32(0x60100)=0xE4775C;++dnd_pickups;}
            else if(state==0xE4775C){if(dnd_invalid)++dnd_restores;else ++dnd_drops;MEM32(0x60100)=0xE476F4;}
        }
        return 0xABC001;
    }
    if(va==0x614200 || va==0x6146C0 || va==0x460000) {
        assert(!n && self==(va==0x460000 ? 0x4E00u : 0x4000u));
        return 0xDEAD00u | (uint32_t)(va==0x460000 ? town_busy : town_blocked);
    }
    if(va==0x61B760) {
        assert(self==0x4000 && n==1 && args[0]==0x10000);
        assert(MEMF(args[0])==731 && MEMF(args[0]+4)==333);++town_actions;return 1;
    }
    if(va==0x619320) {
        assert(self==0x4000 && n==1 && args[0]==1 && !downs && !doubles && !ups);
        ++town_portrait_opens;if(town_portrait_changes_screen)mock_screen=0x5000;
        if(dnd_available)MEM32(0x60100)=0xE476F4;
        return 0;
    }
    if (va == 0xB29220) {
        assert(!n && self == 0x10000);
        MEMF(0x12000) = MEMF(self)*0.8f + 11; MEMF(0x12004) = MEMF(self+4)*0.8f + 13;
        return 0x12000;
    }
    if (va >= 0x410000 && va <= 0x410060) {
        assert(self == 0x6044 && n == 2);
        last_x = MEMF(args[0]); last_y = MEMF(args[0]+4);
        switch (va - 0x410000) {
        case 0x28: assert(args[1] == 1);
            if(ui_overlay)return 0x6900;
            if(town_portrait_pick)return town_portrait_pick;
            if(dnd_available)return dnd_blank ? 0 : dnd_overlay ? 0x6900 : dnd_child ? 0x6810 : 0x6800;
            return force_ui || (last_x >= 0 && last_x < 300) ? 0x6800 : 0;
        case 0x18: assert(args[1] == 1); ++downs; if(edit_kind)focused_field=edit_kind==1 ? 0x30000 : 0x31000; if (change_on_down) mock_screen = 0x5000; break;
        case 0x1C: assert(args[1] == 1); ++ups; break;
        case 0x20: assert(args[1] == 1); ++doubles; break;
        case 0x24: assert(args[1] == 0); ++hovers; break;
        default: assert(0);
        }
        return book_type ? 0xABCD00u | (uint32_t)book_wm_consumed : MEM32(0x4000)==0xE34674 ? 0xABCD01u : 0;
    }
    if (va==0x683450 || va==0x67BAB0) {
        assert(self==0x4000 && n==4 && args[0]==0x10000 && !args[1] && !args[2] && args[3]==1);
        if (MEMF(args[0])!=731 || MEMF(args[0]+4)!=333) {
            /* A bookmark probe around a tap that hit no part: within its reach, after the click. */
            float dx=MEMF(args[0])-731, dy=MEMF(args[0]+4)-333;
            assert(dx*dx+dy*dy<=46.0f*46.0f && downs+doubles==1 && ups==1 && book_picks==1);
            ++book_probes;return book_probe_descriptor;
        }
        assert(va==(book_type==1 ? 0x683450u : 0x67BAB0u));
        assert(downs+doubles==1 && ups==1); /* The window manager has already declined the click. */
        ++book_picks;if(book_pick_changes_screen)mock_screen=0x5000;
        if(book_pick_closes)MEM8(0x4000+(book_type==1 ? 0x1ED : 0x1D4))=1;
        return book_descriptor;
    }
    if (va==0x493ED0) {
        assert((self==book_descriptor+4 || self==book_probe_descriptor+4) && n==1 && !args[0]);
        assert(g_edx==MEM32(self-4+0x10));
        assert((MEM32(self)==0x41000 || MEM32(self)==0x41100) && MEM32(self+4)>MEM32(self));
        ++book_actions;return 0;
    }
    /* The books' page and bookmark message handlers (book_swipe): thiscall on the book, one argument. */
    if (va==0x686020 || va==0x686080 || va==0x6860C0 || va==0x6860E0 || va==0x67E2E0 || va==0x67E320 || va==0x67E2A0) {
        assert(self==0x4000 && n==1 && !args[0] && MEM32(0x4000)==(va>=0x680000 ? 0xE30EB4u : 0xE30CA4u));
        ++book_swipes;last_book_swipe=va;return 1;
    }
    if(va==0xA4DCB0) {assert(self==0x6000 && !n);return focused_field;}
    if(va==0xC3EF90 || va==0xC3EC00 || va==0xC89510 || va==0xC89570) {
        assert(self==(edit_kind==1 ? 0x30000u : 0x31000u) && n==1 && args[0]==0x10140);
        assert(MEM32(args[0]+36)==(va==0xC3EF90 || va==0xC89510 ? 0x42Fu : 8u));
        if(va==0xC3EF90 || va==0xC89510)++text_chars;else ++text_keys;return 1;
    }
    if (va == 0x420010) { assert(self==0xC0F8 && !n); g_st[0]=scroll_value; ++g_fp_top; return 0; }
    /* Original 491560 returns only AL; EAX keeps the settings pointer's upper bits. */
    if (va == 0x420018) { assert(self==0xC0F8 && !n); return 0x123400u | (uint32_t)mock_horizontal; }
    if (va == 0x42000C) {
        assert(self==0xC0F8 && n==1); float value; memcpy(&value,args,4);
        scroll_value=fmaxf(0,fminf(100,value)); ++scroll_sets; return 0;
    }
    if (va == 0x430000) {
        assert(self==0xB100 && n==2 && args[1]==0xC000);
        float value; memcpy(&value,args,4); assert(value==scroll_value); ++scroll_notifies; return 0;
    }
    if (va == 0x540DA0) { assert(self==0x4000 && !n); MEM32(0x42D4)=0; return 0; }
    /* The initiative bar's portrait lookup (combat screen +494): two portraits left of logical x 300. */
    if (va == 0x55DC40) {
        assert(self==0x8700 && n==1 && args[0]==0x10000); ++atb_lookups;
        return MEMF(args[0]) < 200 ? atb_unit : MEMF(args[0]) < 300 ? atb_unit2 : 0;
    }
    /* The adventure controller's hero-on-the-move mode and its cancel command. */
    if (va == 0x603370) { assert(self==0x8000 && n==1 && args[0]==3); return 0x123400u | (uint32_t)hero_moving; }
    if (va == 0x604D60) { assert(self==0x8000 && !n); ++hero_stops; return 0; }
    if (va == 0x667470) {
        assert(self==0x8600 && n==2 && args[0]==0x10000 && args[1]<=1);
        assert(MEMF(args[0])==731 && MEMF(args[0]+4)==333);
        if(args[1]) {
            if(announcement_visible) {++announcement_actions;if(announcement_changes_screen)mock_screen=0x5000;}
        } else ++announcement_probes;
        /* Native bools define AL only, even on the miss path. */
        return 0x123400u | (uint32_t)announcement_visible;
    }
    if (va == 0x550A70) { assert(self==0x100A0 && !n); ++context_ctors; memset(ADDR(self),0,156); return self; }
    if (va == 0x550EB0) { assert(self==0x42EC && n==1 && args[0]==0x100A0); memcpy(ADDR(self),ADDR(args[0]),156); return self; }
    if (va == 0x550B00) { assert(self==0x100A0 && !n); ++context_dtors; return 0; }
    if (va == 0x544230) {
        assert(self==0x4000 && n==2);
        assert((args[0]==0x42F4 && args[1]==0x42EC) || (args[0]==0x10008 && args[1]==0x10000));
        MEM32(args[0])=picked_active ? 0x8200 : 0;
        MEM32(args[0]+0x10)=17; MEM32(args[0]+0x14)=23;
        if(combat_pick_changes_screen)mock_screen=0x5000;
        ++picks; return 0;
    }
    if (va == 0x53E3D0) { assert(self==0x4000 && n==1 && args[0]==0x8200); return !busy; }
    if (va == 0x53FBE0) { assert(self==0x4000 && n==1 && args[0]==0x8200); return 0; }
    if (va == 0x83F2B0) { assert(self==0x4320 && n==1 && args[0]==0x42AC); MEM32(self)=MEM32(args[0]); return self; }
    if (va == 0x53EEE0) { assert(self==0x4000 && !n); return 0; }
    if (va == 0x548270) {
        assert(self==0x4000 && n==2 && args[0]==0x42EC && args[1]==0x42F4);
        assert(MEM32(0x432C)==17 && MEM32(0x4330)==23 && MEM32(0x4320)==0x8200);
        MEM32(0x433C)=0x8300;
        if(clear_target_during_prepare) MEM32(0x4394)=MEM32(0x4388)=MEM32(0x438C)=0;
        ++evaluations; return 0;
    }
    if (va == 0x545490) {
        assert(self==0x4000 && n==1 && args[0]==0x10140);
        uint32_t packed=MEM32(args[0]+0x24);
        assert((packed&0x7FFF)>=900 && ((packed>>15)&0x7FFF)>=400 && MEM32(0x433C)==0x8300);
        ++commands; MEM32(0x42E0)=0x200; return 0;
    }
    if (va == 0x5498C0) {
        assert(self==0x4000 && !n && (MEM32(0x433C)==0x8300 || MEM32(0x431C)==1)); ++previews; return 0;
    }
    if (va == 0x542A30) { assert(self==0x4000 && !n); ++cancels; MEM32(0x4394)=MEM32(0x4388)=MEM32(0x438C)=0; return 1; }
    if (va == 0x450000) { assert(self==0x8200 && !n); if(cast_changes_screen)mock_screen=0x5000; return (uint32_t)cast_available; }
    if (va == 0x545160) {
        assert(self==0x4000 && n==1 && args[0]==0 && MEM32(0x4320)==MEM32(0x42F4));
        assert(!(MEM32(0x4394)||MEM32(0x4388)||MEM32(0x438C)) && (MEM32(0x42E0)&0x188) && !MEM32(0x42D4));
        ++combat_shortcuts;
        if(shortcut_effect==1)MEM32(0x4394)=42;
        if(shortcut_effect==2)mock_screen=0x5000;
        return 0x123401;
    }
    if (va == 0x669430) { assert(self==0x4000 && !n); return 77; }
    if (va == 0x5767A0 || va == 0x5779D0 || va == 0x577DC0) {
        assert(self==0x8500 && n==(va==0x5767A0 ? 2 : 3));
        assert(args[0]==0x10000 && args[1]==0x10018 && MEM32(args[1])==17 && MEM32(args[1]+4)==23);
        if (n==3) assert(args[2]==77);
        if (va==0x5767A0) ++placement_moves;
        else if (va==0x5779D0) ++placement_begins;
        else ++placement_ends;
        return 0;
    }
    if (va == 0x54E030) { assert(self==0x10008 && !n); ++releases; return 0; }
    if (va == 0x576260) { assert(self==0x8500 && !n); ++placement_cancels; return 0; }
    /* The tactics reserve's slot hit test (PlacementBar), -1 for none. */
    if (va == 0x5764A0) { assert(self==0x8500 && n==1 && args[0]==0x10000); return (uint32_t)reserve_slot; }
    if (va == 0x603980) { assert(self == 0x8000 && !n); if(clear_target_during_prepare)MEM32(0x8044)=0; return busy; }
    if (va == 0x41A760) { assert(self==0x10014 && n==1 && args[0]==0x4750); return ((MEM32(self)^MEM32(args[0]))&0xFFFFFFu)==0; }
    if (va == 0x603360) { assert(self == 0x8000 && !n); return MEM32(0x8044)==0; }
    if (va == 0x603560) { assert(self == 0x8000 && !n); return double_object==4; }
    if (va == 0x59EAC0 || va == 0x59EAF0 || va == 0x59EB20 || va == 0x59EB60 || va == 0x433F40) {
        assert(self==0x10190 && n==1);
        assert(args[0]==(va==0x433F40 ? 0x1001Cu : va==0x59EB20 ? 0x20000u : 0x10018u));
        MEM32(self)=va==0x59EAC0 && double_object==1 ? 0x20000 :
                    va==0x59EAF0 && double_object==2 ? 0x21000 :
                    va==0x59EB20 && double_object==2 ? 0x20000 :
                    va==0x59EB60 && double_object==4 ? 0x23000 :
                    va==0x433F40 && double_object==3 ? 0x22000 : 0;
        return self;
    }
    if (va == 0x603860 || va == 0x6038A0) { assert(self==0x8000 && !n); return same_selection ? (va==0x603860 ? 0x20000 : 0x23000) : 0; }
    if (va == 0x433CF0) { assert(!n && (g_edx==0x20000 || g_edx==0x23000)); return self==g_edx; }
    if (va == 0x603580 || va == 0x6035A0) { assert(self==0x8000 && n==1 && args[0]==77); return va==0x6035A0 || owned; }
    if (va == 0x594E60) { assert(self==0x4000 && n==1 && args[0]==0x23000); ++ghost_views; return 0; }
    if (va == 0x604470 || va == 0x6047F0) {
        assert(self==0x8000 && n==1 && args[0]==0x22000);
        if (va==0x604470) ++town_selections; else ++town_views; return 0;
    }
    if (va == 0x58D5C0) { assert(self==0x4000 && !n); return 0x26000; }
    if (va >= 0x440000 && va <= 0x44001C) {
        if (va==0x440000) { assert(self==0x20044 && !n); return 0x24000; }
        if (va==0x440004) { assert(self==0x23000 && !n); return 0x25000; }
        if (va==0x440008) { assert(self==0x25000 && !n); return 0x24000; }
        if (va==0x44000C) { assert(self==0x24000 && !n); return 77; }
        if (va==0x440010) { assert(self==0x21000 && !n); return 0x20000; }
        if (va==0x440014) { assert(self==0x22000 && n==1 && args[0]==0x10194); MEM32(args[0])=(23u<<10)|17; return 0; }
        if (va==0x440018) { assert(self==0x22000 && !n); return 77; }
        assert(self==0x26000 && n==1 && args[0]==1); return 0x27000;
    }
    if (va == 0x5913B0) {
        assert(self == 0x4000 && n == 2 && args[0] == 0x10008 && args[1] == 0x10000);
        assert(MEM32(args[0]+0x10) == 0 && MEM32(args[0]+0x14) == 0);
        if (double_object==3) MEM32(args[0]+0x14)=0x18100;
        else if (double_object) MEM32(args[0]+0x10)=0x18000;
        ++picks; return pick_available;
    }
    if (va == 0x597360) { assert(self == 0x4000 && n == 1 && args[0] == 0x10008); ++commands; return 0; }
    if (va == 0x600E70) {
        assert(self == 0x8000 && n == 3 && args[0] == 0x10028 && args[1] == 0x10008 && args[2] == 0);
        assert(MEM32(args[0]+0xC) == 0xE739C && MEM8(args[0]+0x38) == 1);
        ++evaluations; return 0;
    }
    if (va == 0x5A0F40) { assert(self == 0x10028 && !n); return 0; }
    if (va == 0x59F450) { assert(self == 0x10008 && !n); ++releases; return 0; }
    if (va == 0x604E20) { assert(self == 0x8000 && !n); ++cancels; MEM32(0x8044)=0; return 1; }
    assert(0); return 0;
}
#include "touch.h"
int void_touch_camera_pose(uint32_t screen, int kind, float pose[10], int set, int immediate) {
    assert(screen == 0x4000 && (kind == 0 || kind == 1) && immediate == (set && kind == 0));
    if (set) { for(int i=0;i<10;++i)if(!isfinite(pose[i]))return 0; ++camera_pose_sets; last_pose_pitch = pose[1]; memcpy(last_pose,pose,sizeof last_pose);last_pose_kind=kind;return 1; }
    for (int i = 0; i < 10; ++i) pose[i] = (float)(i + 1);
    ++camera_pose_gets; return 1;
}
int void_touch_camera_tilt(uint32_t screen, int kind, float dy) {
    assert(screen == 0x4000 && (kind == 0 || kind == 1 || kind == 2) && isfinite(dy)); ++tilts; return 1;
}
int void_touch_camera(uint32_t screen, int combat, float x, float y, float dx, float dy, float scale, float rotation) {
    assert(screen == 0x4000 && (combat==0 || combat==1 || combat==2)); assert(isfinite(x+y+dx+dy+scale+rotation)); last_camera_kind=combat; ++cameras; return 1;
}
#include "touch_engine_actual.h"
static void settle(void) { mock_now_ns += 1000000000ull; void_touch_ui_pump(); }
static void reset(int kind) {
    cursor_offset_x=cursor_offset_y=0;show_touch_cursor=0;
    void_touch_engine_init(); mock_screen=0x4000; mock_now_ns+=10000000000ull;
    lifted_tracker_calls=lifted_timeout_calls=camera_pose_gets=camera_pose_sets=tilts=0;
    downs=ups=doubles=hovers=picks=commands=evaluations=releases=cancels=cameras=0;
    edit_kind=text_arms=text_cancelled=text_chars=text_keys=0;focused_field=0;
    MEM32(0x30000)=0xABCDE;MEM32(0x31000)=0xBCDEF;MEM8(0x30141)=0;
    ui_pans=last_camera_kind=0;force_ui=busy=change_on_down=0; pick_available=1;
    inspections=inspection_changes_screen=held_details=0;MEM32(0x6000)=0;
    previews=placement_begins=placement_moves=placement_ends=placement_cancels=0;reserve_slot=-1;
    double_object=town_views=town_selections=ghost_views=0; same_selection=owned=town_visible=1;
    announcement_visible=announcement_probes=announcement_actions=announcement_changes_screen=0;
    picked_active=cast_available=combat_shortcuts=shortcut_effect=clear_target_during_prepare=combat_pick_changes_screen=0;
    context_ctors=context_dtors=cast_changes_screen=0;
    book_type=book_picks=book_actions=book_wm_consumed=book_pick_changes_screen=book_pick_closes=0;
    book_missing_picker=book_missing_action=book_probes=book_swipes=0;book_descriptor=0x40000;
    book_probe_descriptor=last_book_swipe=0;
    atb_unit=atb_unit2=0;atb_lookups=minimap_hit=hero_moving=hero_stops=0;
    town_actions=town_blocked=town_busy=0;MEM32(0x414C)=MEM32(0x4150)=0;
    town_portrait_hits=town_portrait_opens=town_portrait_changes_screen=0;
    town_portrait_pick=0;MEM32(0x42A8)=0;MEM32(0x44E8)=MEM32(0x4600)=0;MEM32(0x41BC)=0;
    dnd_available=dnd_blank=dnd_overlay=dnd_child=dnd_invalid=dnd_probe_changes_screen=dnd_hidden=0;
    dnd_probes=dnd_downs=dnd_ups=dnd_moves=dnd_doubles=dnd_cancels=dnd_pickups=dnd_drops=dnd_restores=0;
    dnd_down_x=731;dnd_down_y=333;
    mentor_selects=mentor_confirms=mentor_changes_screen=ui_overlay=ghost_selects=ghost_moves=0;
    loading_stage=loading_cleanup=loading_queued=loading_no_command=0;
    list_available=mock_horizontal=scroll_sets=scroll_notifies=g_fp_top=0; scroll_value=50;
    MEM32(0xFE719C)=0x2000; MEM32(0x7004)=0x9100; MEM32(0x9104)=0x20;
    MEM32(0x4000)=kind==2 ? 0xE1DA84 : kind ? 0xE230E4 : 0xE2F64C; MEM32(0x5000)=0xE2F64C;
    MEM32(0x40A0)=MEM32(0x50A0)=0x6000; MEM32(0x45F4)=0x8000; MEM32(0x8044)=0; MEM32(0x40EC)=0;
    MEM32(0x6004)=0x9800; MEM32(0x9808)=0x40; MEM32(0x6044)=0x9900;
    for (unsigned i=0;i<=0x60;i+=4) MEM32(0x9900+i)=0x410000+i;
    MEM32(0x6800)=0xA000; MEM32(0xA0D8)=0;
    MEM32(0xB154)=0xC000; MEM32(0xC0F8)=0xD000;
    MEM32(0xD00C)=0x42000C; MEM32(0xD010)=0x420010; MEM32(0xD018)=0x420018;
    MEM32(0xB100)=0xE000; MEM32(0xE000)=0x430000;
    MEM32(0x42B4)=0x8100; MEM32(0x42AC)=0x8200; MEM32(0x8204)=0x9400; MEM32(0x9404)=0x20;
    MEM32(0x8200)=0x9500; MEM32(0x9574)=0x450000;
    MEM32(0x4488)=0x8500;
    MEM8(0x455C)=MEM8(0x45E8)=0; MEM32(0x4760)=0;
    MEM32(0x40B4)=1; MEM32(0x18004)=MEM32(0x18104)=0;
    MEM32(0x20004)=0x31000; MEM32(0x3100C)=0x40; MEM32(0x20044)=0x32000; MEM32(0x32000)=0x440000;
    MEM32(0x23000)=0x33000; MEM32(0x33000)=0x440004; MEM32(0x25000)=0x34000; MEM32(0x34004)=0x440008;
    MEM32(0x24000)=0x35000; MEM32(0x3502C)=0x44000C; MEM32(0x21000)=0x36000; MEM32(0x36000)=0x440010;
    MEM32(0x22000)=0x37000; MEM32(0x370C4)=0x440014; MEM32(0x370BC)=0x440018;
    MEM32(0x26000)=0x38000; MEM32(0x3819C)=0x44001C; MEM32(0x27020)=0x28000; MEM32(0x2805C)=0x29000;
    MEM8(0x29011)=1;
    MEM32(0x8228)=0; MEM32(0x42E0)=0x188; MEM32(0x42D4)=0; MEM32(0x4394)=MEM32(0x4388)=MEM32(0x438C)=0;
}
static void event(int kind, float x, float y) {
    void_touch_event e={kind,x,y,4,8,1.1f,0}; void_touch_engine_event(&e);
}
static void reset_book(int orcs) {
    reset(0);book_type=orcs ? 2 : 1;MEM32(0x4000)=orcs ? 0xE30CA4 : 0xE30EB4;
    uint32_t field=orcs ? 0x41A8 : 0x41B4, stride=orcs ? 40u : 36u;
    MEM32(field)=0x40000;MEM32(field+4)=0x40000+2*stride;
    MEM32(0x4000+(orcs ? 0x1C0 : 0x1CC))=0x42000;
    MEM8(0x41ED)=MEM8(0x41D4)=0;
    memset(ADDR(0x40000),0,80);MEM32(book_descriptor)=10;
    MEM32(book_descriptor+4)=0x41000;MEM32(book_descriptor+8)=0x4100C;
    MEM32(book_descriptor+12)=0x41010;MEM32(book_descriptor+16)=7;
    memcpy(ADDR(0x41000),"MB_CastSpell",12);
}
static void reset_dnd(void) {
    reset(0);dnd_available=1;MEM32(0x414C)=0x4F00;MEM32(0x4F00)=0x4F00;
    MEM32(0x4150)=0x60000;MEM32(0x60000)=0xE47794;MEM32(0x6000C)=0x60100;MEM32(0x60100)=0xE476F4;
    MEM32(0xE477B8)=0x813B20;MEM32(0xE477BC)=0x813BC0;MEM32(0xE477C0)=0x813C60;
    MEM32(0xE477C4)=0x813D00;MEM32(0xE477C8)=0x813DA0;
    MEM32(0x70010)=0x71000;MEM32(0x71000)=0x72000;MEM32(0x72024)=0x470024;
    MEM32(0x6900)=0xA100;MEM32(0xA1D8)=0;MEM32(0x6810)=0xA200;MEM32(0xA2D8)=0x4700D8;
}
static void reset_mentor(int mode) {
    reset(0);force_ui=1;MEM32(0x4000)=0xE3584C;MEM32(0x414C)=0x4F00;MEM32(0x4F00)=0x4F00;
    MEM32(0x47DC)=6;MEM32(0x47E8)=0;MEM8(0x44B8)=0;MEM32(0x41BC)=(uint32_t)mode;
    MEM32(0x45A0)=0x80000;MEM32(0x45A4)=0x80010;MEM32(0x80000)=0x6800;
    MEM32(0x45D4)=0x81000;MEM32(0x45D8)=0x81024;MEM32(0x81004)=0x6800;
    MEM32(0x45AC)=MEM32(0x45B0)=MEM32(0x81008)=MEM32(0x8100C)=0;
    MEM32(0x6800)=0xA000;MEM32(0xA05C)=0x48005C;
}
static void reset_town(void) {
    reset(0);MEM32(0x4000)=0xE2A64C;MEM32(0x414C)=0x4F00;MEM32(0x4F00)=0x4F00;
    MEM32(0x4294)=1;MEM8(0x429C)=MEM8(0x4478)=0;MEM32(0x43DC)=0x4E00;
    MEM32(0x4E00)=0x4D00;MEM32(0x4D48)=0x460000;
}
static void reset_ghost(void) {
    reset(0);force_ui=1;MEM32(0x4000)=0xE4094C;MEM32(0x414C)=0x4F00;MEM32(0x4F00)=0x4F00;
    MEM32(0x41D8)=0x82000;MEM32(0x41DC)=0x82024;MEM32(0x8201C)=MEM32(0x82020)=0x6800;
    MEM32(0x6800)=0xA000;MEM32(0xA05C)=0x48005C;
}
static void reset_town_portrait(void) {
    reset_dnd();MEM32(0x4000)=0xE2A64C;MEM32(0x4294)=1;MEM8(0x429C)=MEM8(0x4478)=0;
    MEM32(0x43DC)=0x4E00;MEM32(0x4E00)=0x4D00;MEM32(0x4D48)=0x460000;
    MEM32(0x42A0)=0x6800;MEM32(0x42A4)=0x6820;MEM32(0xA05C)=0x48005C;
    MEM32(0x6820)=0xA300;MEM32(0xA35C)=0x48005C;MEM32(0xA3D8)=0;
    town_portrait_hits=1;
}
static void reset_loading(void) {
    reset(0);force_ui=1;MEM32(0x4000)=0xE34674;MEM32(0x41A4)=5;
    MEM32(0x414C)=0x4F00;MEM32(0x4F00)=0x4F00;
}
int main(void) {
    uint32_t text_field,text_epoch;int text_kind;
    for(int world=1;world<=2;++world) {
        reset(world);event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
        assert(commands==1); /* No frame pump, timer or subsequent touch required. */
        event(TOUCH_END,900,400);event(TOUCH_ABORT,0,0);settle();assert(!gesture.active && commands==1);
    }
    reset_town_portrait();event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);
    assert(town_portrait_opens==1 && !doubles && !downs && !ups && !dnd_doubles && !dnd_downs && !dnd_ups);
    reset_town_portrait();town_portrait_hits=2;town_portrait_pick=0x6820;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(town_portrait_opens==1);
    reset_town_portrait();dnd_child=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(town_portrait_opens==1);
    reset_town_portrait();town_portrait_hits=0;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens && doubles==1);
    reset_town_portrait();dnd_overlay=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens);
    reset_town_portrait();town_blocked=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens);
    reset_town_portrait();MEM32(0x4294)=0;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens);
    reset_town_portrait();MEM8(0x429C)=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens);
    reset_town_portrait();MEM8(0x4478)=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens);
    reset_town_portrait();MEM32(0x4F00)=0x4F04;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens);
    reset_town_portrait();event(TOUCH_BEGIN,900,400);mock_screen=0x5000;event(TOUCH_DOUBLE_TAP,900,400);assert(!town_portrait_opens);
    reset_town_portrait();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(dnd_pickups==1 && MEM32(0x60100)==0xE4775C);downs=ups=doubles=0;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);
    assert(town_portrait_opens==1 && MEM32(0x60100)==0xE476F4 && !dnd_doubles && dnd_downs==1 && dnd_ups==1);
    reset_loading();event(TOUCH_BEGIN,900,400);assert(!loading_cleanup && MEM32(0x41A4)==5);
    event(TOUCH_TAP,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(loading_cleanup==1 && loading_queued==1 && loading_stage==4 && !MEM32(0x41A4) && downs==1 && ups==1);
    reset_loading();event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);assert(loading_queued==1);
    for(unsigned state=0;state<=6;++state) if(state!=5) {
        reset_loading();MEM32(0x41A4)=state;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!loading_cleanup && MEM32(0x41A4)==state);
    }
    reset_loading();event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);event(TOUCH_END,900,400);assert(!loading_cleanup);
    reset_loading();event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);event(TOUCH_END,950,410);assert(!loading_cleanup);
    reset_loading();event(TOUCH_BEGIN,900,400);event(TOUCH_ABORT,900,400);assert(!loading_cleanup);
    reset_loading();event(TOUCH_BEGIN,900,400);mock_screen=0x5000;event(TOUCH_TAP,900,400);assert(!loading_cleanup);
    reset_loading();MEM32(0x4F00)=0x4F04;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!loading_cleanup);
    reset_loading();MEM32(0x4000)=0xE2F64C;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!loading_cleanup);
    reset_loading();change_on_down=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!loading_cleanup);
    reset_loading();loading_no_command=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(loading_cleanup==1 && loading_stage==3 && !loading_queued);
    reset_mentor(3);event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(mentor_selects==1 && !mentor_confirms);
    reset_mentor(4);event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);
    assert(mentor_selects==1 && mentor_confirms==1);
    reset_mentor(3);event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);event(TOUCH_END,900,400);assert(!mentor_selects);
    reset_mentor(3);MEM32(0x47DC)=5;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!mentor_selects);
    reset_mentor(3);MEM32(0x47E8)=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!mentor_selects);
    reset_mentor(3);MEM32(0x4F00)=0x4F04;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!mentor_selects);
    reset_mentor(3);ui_overlay=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!mentor_selects);
    reset_mentor(3);mentor_changes_screen=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);
    assert(mentor_selects==1 && !mentor_confirms);
    reset_mentor(3);MEM32(0x45A4)=0x8000F;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!mentor_selects);
    reset_mentor(3);MEM32(0x45A4)=0x80000;MEM32(0x45AC)=0x83000;MEM32(0x45B0)=0x83008;
    MEM32(0x83000)=0;MEM32(0x83004)=0x6800;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(mentor_selects==1);
    reset_mentor(4);MEM32(0x81004)=0;MEM32(0x81008)=0x84000;MEM32(0x8100C)=0x84004;MEM32(0x84000)=0x6800;
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(mentor_selects==1);
    reset_ghost();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);assert(ghost_selects==1 && !ghost_moves);
    reset_ghost();event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);event(TOUCH_END,950,410);assert(ghost_moves==1 && !ghost_selects && !cameras);
    reset_ghost();event(TOUCH_BEGIN,500,400);event(TOUCH_PAN,950,410);event(TOUCH_END,950,410);assert(!ghost_moves && !ghost_selects && !cameras);
    reset_ghost();event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,500,410);event(TOUCH_END,500,410);assert(!ghost_moves && !ghost_selects && !downs && !ups && !cameras);
    reset_ghost();event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);event(TOUCH_END,900,400);assert(!ghost_selects && !ghost_moves);
    reset_ghost();ui_overlay=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!ghost_selects);
    reset_ghost();event(TOUCH_BEGIN,900,400);mock_screen=0x5000;event(TOUCH_TAP,900,400);assert(!ghost_selects);
    reset_ghost();MEM32(0x41DC)=0x82023;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!ghost_selects);
    reset_town();town_blocked=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!town_actions);
    reset_town();town_busy=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!town_actions);
    reset_town();MEM32(0x4294)=0;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!town_actions);
    reset_town();MEM8(0x429C)=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!town_actions);
    reset_town();MEM8(0x4478)=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!town_actions);
    reset_town();force_ui=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!town_actions);
    reset_town();event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);event(TOUCH_END,900,400);assert(!town_actions);
    reset_dnd();event(TOUCH_BEGIN,900,400);assert(gesture.dnd_claim && dnd_probes==1 && !dnd_downs && !dnd_pickups);
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(dnd_downs==1 && dnd_ups==1 && dnd_pickups==1 && !dnd_drops && drag_owner.helper==0x60000);
    void_touch_frame_presented();void_touch_ui_pump();g_esp=1000;touch_cursor_query();assert(MEMF(g_eax)==731);
    dnd_down_x=771;dnd_down_y=341;
    event(TOUCH_BEGIN,950,410);event(TOUCH_TAP,950,410);event(TOUCH_END,950,410);
    assert(dnd_downs==2 && dnd_ups==2 && dnd_drops==1 && !drag_owner.helper && !dnd_cancels);
    reset_dnd();dnd_child=1;event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);event(TOUCH_END,950,410);
    assert(dnd_downs==1 && dnd_moves==1 && dnd_ups==1 && dnd_drops==1 && !cameras && !dnd_cancels);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);event(TOUCH_ABORT,950,410);
    assert(dnd_downs==1 && !dnd_ups && dnd_cancels==1 && dnd_restores==1 && !dnd_drops);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);dnd_overlay=1;event(TOUCH_END,950,410);
    assert(!dnd_ups && dnd_cancels==1 && !dnd_drops);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);dnd_blank=dnd_invalid=1;event(TOUCH_END,950,410);
    assert(dnd_ups==1 && dnd_restores==1 && !dnd_drops && !dnd_cancels);
    /* An empty army cell hides its icon: the probe finds no visible slot, the held stack's own map does,
       and the picker falls through to the cell's container. The native drop takes it, as with a mouse. */
    /* The native pickup keeps its slot entry at helper +1C (the drop 0x00813950 clears it). */
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);MEM32(0x6001C)=0x70000;dnd_hidden=1;event(TOUCH_END,950,410);
    assert(dnd_ups==1 && dnd_drops==1 && !dnd_cancels);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    MEM32(0x6001C)=0x70000;dnd_hidden=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(dnd_pickups==1 && dnd_drops==1 && !dnd_cancels);
    /* Without the held entry the visible-slot probe is all there is: the hidden cell is refused. */
    reset_dnd();MEM32(0x6001C)=0;event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);dnd_hidden=1;event(TOUCH_END,950,410);
    assert(!dnd_ups && dnd_cancels==1 && !dnd_drops);
    reset_dnd();dnd_overlay=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!dnd_downs && !dnd_ups);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);void_touch_ui_pump();event(TOUCH_END,900,400);
    assert(!dnd_downs && !dnd_ups && !dnd_cancels && !dnd_pickups);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    dnd_blank=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TWO_FINGER_CANCEL,900,400);event(TOUCH_END,900,400);
    assert(dnd_cancels==1 && dnd_ups==1 && dnd_restores==1 && !dnd_drops);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);event(TOUCH_END,900,400);
    assert(!dnd_cancels && dnd_pickups==1 && dnd_ups==1 && dnd_held(0x60000));
    event(TOUCH_ABORT,900,400);assert(dnd_cancels==1 && !dnd_drops && !drag_owner.helper);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    dnd_overlay=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(dnd_cancels==1 && dnd_ups==1 && !dnd_drops);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    MEM32(0x4F00)=0x4F04;event(TOUCH_BEGIN,900,400);event(TOUCH_ABORT,900,400);
    assert(dnd_cancels==1 && dnd_ups==1 && !drag_owner.helper); /* Lifecycle abort is not blocked by pending UI. */
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    mock_screen=0x5000;void_touch_ui_pump();assert(!dnd_cancels && drag_owner.invalid);
    g_esp=1000;touch_cursor_query();assert(MEMF(g_eax)==-1); /* No held-item hover leaks into a new modal. */
    mock_screen=0x4000;void_touch_ui_pump();assert(dnd_cancels==1 && !drag_owner.helper);
    reset_dnd();event(TOUCH_BEGIN,900,400);MEM32(0x4150)=0x61000;event(TOUCH_TAP,900,400);
    assert(!dnd_downs && !dnd_ups && !dnd_cancels); /* Never call a replaced helper. */
    reset_dnd();dnd_probe_changes_screen=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
    assert(!dnd_downs && !dnd_ups && !dnd_cancels && !hovers);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);
    assert(dnd_doubles==1 && dnd_ups==1 && !dnd_downs && !dnd_drops);
    reset(0);MEM32(0x4000)=0xE2A64C;MEM32(0x414C)=0x4F00;MEM32(0x4F00)=0x4F00;
    MEM32(0x4294)=1;MEM8(0x429C)=MEM8(0x4478)=0;MEM32(0x43DC)=0x4E00;
    MEM32(0x4E00)=0x4D00;MEM32(0x4D48)=0x460000;
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(town_actions==1 && !commands && !cameras);
    /* Book controls are mesh parts: regular WM declines, native point pick resolves the action. */
    reset_book(0);event(TOUCH_BEGIN,900,400);void_touch_frame_presented();
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(book_picks==1 && book_actions==1 && !commands && !cameras);
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);assert(book_actions==1); /* No END/repeated-event commit. */
    reset_book(1);event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);
    assert(book_picks==1 && book_actions==1 && doubles==1 && !downs && !commands);
    /* The native descriptor supplies page/school/close actions and arguments, not an assumed spell index. */
    reset_book(0);memcpy(ADDR(0x40024),ADDR(0x40000),36);book_descriptor=0x40024;
    memcpy(ADDR(0x41000),"MB_Button_School",16);MEM32(book_descriptor+8)=0x41010;MEM32(book_descriptor+16)=3;
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(book_actions==1 && g_edx==3);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);
    void_touch_ui_pump();void_touch_ui_pump();g_esp=1000;touch_cursor_query();
    assert(MEMF(g_eax)==731 && MEMF(g_eax+4)==333 && gesture.held); /* Native tooltip sees the explicit point. */
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);g_esp=1000;touch_cursor_query();
    assert(!book_picks && !book_actions && !downs && !ups && MEMF(g_eax)==-1);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);event(TOUCH_TRANSFORM,950,410);
    event(TOUCH_TAP,900,400);event(TOUCH_END,950,410);
    assert(!book_picks && !book_actions && !downs && !ups && !cameras);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_TWO_FINGER_BEGIN,900,400);
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);assert(!book_picks && !book_actions && !cameras);
    reset_book(0);force_ui=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
    assert(downs==1 && ups==1 && !book_picks && !book_actions); /* An ordinary child owns its area. */
    reset_book(0);book_wm_consumed=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
    assert(downs==1 && ups==1 && !book_picks && !book_actions); /* AL-only consumption blocks 3D fallthrough. */
    reset_book(0);event(TOUCH_BEGIN,900,400);mock_screen=0x5000;
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);assert(!book_picks && !book_actions && !downs);
    reset_book(0);change_on_down=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
    assert(!book_picks && !book_actions && downs==1 && !ups);
    reset_book(0);book_pick_changes_screen=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
    assert(book_picks==1 && !book_actions);
    reset_book(0);event(TOUCH_BEGIN,900,400);MEM8(0x41ED)=1;
    event(TOUCH_TAP,900,400);assert(!book_picks && !book_actions); /* Closing can precede removal from the screen list. */
    reset_book(1);event(TOUCH_BEGIN,900,400);MEM8(0x41D4)=1;
    event(TOUCH_TAP,900,400);assert(!book_picks && !book_actions);
    reset_book(0);book_pick_closes=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
    assert(book_picks==1 && !book_actions);
    reset_book(0);book_descriptor=0;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);
    assert(book_picks==1 && book_probes==24 && !book_actions);   /* three rings of bookmark probes, none there */
    /* A tap beside a bookmark takes it: the nearest probe that hits a "MB_Button_School" part. */
    reset_book(0);book_descriptor=0;book_probe_descriptor=0x40024;memcpy(ADDR(0x40024),ADDR(0x40000),36);
    MEM32(0x40028)=0x41100;MEM32(0x4002C)=0x41110;MEM32(0x40034)=4;memcpy(ADDR(0x41100),"MB_Button_School",16);
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(book_picks==1 && book_probes==1 && book_actions==1 && g_edx==4);
    /* Any other part found beside the tap is no bookmark: nothing. */
    reset_book(0);book_descriptor=0;book_probe_descriptor=0x40000;
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(book_probes==24 && !book_actions);
    /* Swipes turn pages (left: next) and step bookmarks (up: the previous one); the orcish book has two pages and a tab. */
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,800,404);event(TOUCH_END,800,404);
    assert(book_swipes==1 && last_book_swipe==0x686020 && !book_picks && !book_actions && !downs && !ups);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,1000,396);event(TOUCH_END,1000,396);
    assert(book_swipes==1 && last_book_swipe==0x686080);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,904,300);event(TOUCH_END,904,300);
    assert(book_swipes==1 && last_book_swipe==0x6860C0);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,896,500);event(TOUCH_END,896,500);
    assert(book_swipes==1 && last_book_swipe==0x6860E0);
    reset_book(1);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,800,400);event(TOUCH_END,800,400);
    assert(book_swipes==1 && last_book_swipe==0x67E2E0);
    reset_book(1);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,1000,400);event(TOUCH_END,1000,400);
    assert(book_swipes==1 && last_book_swipe==0x67E320);
    reset_book(1);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,900,520);event(TOUCH_END,900,520);
    assert(book_swipes==1 && last_book_swipe==0x67E2A0);
    /* Short or diagonal travel, a held finger, a closing book or a start on a window: no swipe. */
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,860,404);event(TOUCH_END,860,404);assert(!book_swipes);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,800,330);event(TOUCH_END,800,330);assert(!book_swipes);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);event(TOUCH_HOLD_DRAG,800,400);
    event(TOUCH_END,800,400);assert(!book_swipes && !book_actions);
    reset_book(0);event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,800,400);MEM8(0x41ED)=1;event(TOUCH_END,800,400);assert(!book_swipes);
    reset_book(0);force_ui=1;event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,800,400);event(TOUCH_END,800,400);assert(!book_swipes);
    reset_book(0);book_descriptor+=4;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_actions);
    reset_book(0);book_descriptor=0x40048;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_actions);
    reset_book(0);MEM32(0x41B8)=0x3FFFF;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_actions);
    reset_book(0);MEM32(0x40008)=0x41081;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_actions);
    reset_book(0);MEM32(0x40004)=0x10FFFFC;MEM32(0x40008)=0x1100008;
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_actions);
    reset_book(0);MEM32(0x41CC)=0;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_picks && !book_actions);
    reset_book(0);book_missing_picker=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_picks && !book_actions);
    reset_book(0);book_missing_action=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);assert(!book_picks && !book_actions);
    reset(0);focused_field=0x30000;
    assert(!void_touch_text_focus(&text_field,&text_kind,&text_epoch) && !text_arms);
    edit_kind=1;event(TOUCH_BEGIN,100,200);assert(!void_touch_engine_ready(TOUCH_TAP));
    assert(void_touch_engine_ready(TOUCH_ABORT));void_touch_frame_presented();assert(void_touch_engine_ready(TOUCH_TAP));
    event(TOUCH_TAP,100,200);event(TOUCH_END,100,200);
    assert(!void_touch_engine_ready(TOUCH_BEGIN));void_touch_frame_presented();assert(void_touch_engine_ready(TOUCH_BEGIN));
    assert(text_arms==1 && void_touch_text_focus(&text_field,&text_kind,&text_epoch));
    assert(text_field==0x30000 && text_kind==1 && text_epoch);
    void_touch_text_dispatch(text_field,text_kind,0,0x42F);void_touch_text_dispatch(text_field,text_kind,1,8);
    assert(text_chars==1 && text_keys==1);
    MEM8(0x30141)=1;assert(!void_touch_text_focus(&text_field,&text_kind,&text_epoch));
    reset(0);edit_kind=2;event(TOUCH_BEGIN,100,200);event(TOUCH_TAP,100,200);
    assert(void_touch_text_focus(&text_field,&text_kind,&text_epoch) && text_field==0x31000 && text_kind==2);
    focused_field=0;assert(!void_touch_text_focus(&text_field,&text_kind,&text_epoch));
    reset(0); g_esp=1000; touch_cursor_query(); assert(g_eax==0x1234 && g_esp==1004 && !void_touch_active_mode());
    assert(cursor_draw_hook);g_esp=1000;cursor_draw_hook();assert(cursor_draws==1&&g_eax==0xD00D&&g_esp==1008);
    reset(0); event(TOUCH_BEGIN,100,200); assert(!downs && !ups && !commands);
    /* Touch suppresses only drawing, preserving cursor state, registers and renderer argument. */
    unsigned char cursor_before[88];memcpy(cursor_before,ADDR(0xFE6DA8),sizeof cursor_before);
    MEMF(0xFE6DA0)=321;MEMF(0xFE6DA4)=234;
    g_esp=1000;g_eax=0x11223344;g_edx=0x55667788;g_fp_top=2;g_st[0]=1.25;g_st[1]=-3.5;
    MEM32(1000)=0xABCDEF;MEM32(1004)=0xC0FFEE;cursor_draw_hook();
    assert(cursor_draws==1&&g_esp==1008&&g_eax==0x11223344&&g_edx==0x55667788);
    assert(g_fp_top==2&&g_st[0]==1.25&&g_st[1]==-3.5&&MEM32(1000)==0xABCDEF&&MEM32(1004)==0xC0FFEE);
    assert(MEMF(0xFE6DA0)==321&&MEMF(0xFE6DA4)==234&&!memcmp(cursor_before,ADDR(0xFE6DA8),sizeof cursor_before));
    g_fp_top=0;
    event(TOUCH_TAP,100,200); event(TOUCH_END,100,200); assert(downs==1 && ups==1 && !commands);
    assert(last_x==91 && last_y==173); void_touch_ui_pump(); assert(last_x==91 && gesture.retiring);
    g_esp=1000; touch_cursor_query(); assert(MEMF(g_eax)==91 && MEMF(g_eax+4)==173);
    void_touch_frame_presented(); void_touch_ui_pump(); assert(!gesture.retiring);
    assert(last_x==-1 && last_y==-1); /* Exit sentinel is not letterbox-scaled. */
    reset(0); event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200); event(TOUCH_END,100,200);
    event(TOUCH_ABORT,100,200); assert(!gesture.retiring && last_x==-1);
    reset(0); event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200); event(TOUCH_END,100,200);
    mock_screen=0x5000; void_touch_ui_pump(); g_esp=1000; touch_cursor_query(); assert(!gesture.retiring && MEMF(g_eax)==-1);
    reset(0); event(TOUCH_BEGIN,100,200); event(TOUCH_DOUBLE_TAP,100,200); event(TOUCH_END,100,200);
    assert(doubles==1 && ups==1 && !downs);
    reset(0); event(TOUCH_BEGIN,100,200); event(TOUCH_HOLD_BEGIN,100,200);
    int prior=hovers; void_touch_ui_pump(); void_touch_ui_pump(); assert(hovers==prior+2 && !downs);
    event(TOUCH_END,100,200); prior=hovers; void_touch_ui_pump(); assert(hovers==prior && !downs && !ups);
    reset(0); event(TOUCH_BEGIN,100,200); event(TOUCH_HOLD_BEGIN,100,200); mock_screen=0x5000;
    void_touch_ui_pump(); g_esp=1000; touch_cursor_query(); assert(MEMF(g_eax)==-1 && !gesture.active);
    reset(0); event(TOUCH_BEGIN,100,200); event(TOUCH_PAN,110,220); assert(downs==1 && !ups);
    event(TOUCH_ABORT,110,220); assert(ups==1 && last_x==-1 && !commands);
    /* Distinct X/Y deltas verify both orientations with nonzero garbage above AL. */
    reset(0); list_available=1; event(TOUCH_BEGIN,100,200); event(TOUCH_PAN,104,208);
    assert(!downs && !ups && scroll_sets==1 && scroll_notifies==1 && fabsf(scroll_value-43.6f)<0.001f && !g_fp_top);
    event(TOUCH_END,104,208); assert(!downs && !ups);
    /* A held list/button never acquires an inventory slot or clicks a row on movement. */
    reset(0); list_available=1; event(TOUCH_BEGIN,100,200); event(TOUCH_HOLD_BEGIN,100,200);
    event(TOUCH_HOLD_DRAG,102,202); event(TOUCH_END,102,202);
    assert(!dnd_downs && !dnd_moves && !dnd_pickups && !downs && !ups && !commands);
    reset(0); event(TOUCH_BEGIN,100,200); event(TOUCH_HOLD_BEGIN,100,200);
    event(TOUCH_HOLD_DRAG,102,202); event(TOUCH_END,102,202);
    assert(!dnd_downs && !dnd_moves && !dnd_pickups && !downs && !ups && !commands);
    reset_dnd(); dnd_overlay=1; event(TOUCH_BEGIN,900,400); assert(!gesture.dnd_claim);
    event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_HOLD_DRAG,902,402); event(TOUCH_END,902,402);
    assert(!dnd_downs && !dnd_moves && !dnd_pickups && !downs && !ups && !commands);
    reset(0); list_available=mock_horizontal=1; event(TOUCH_BEGIN,100,200); event(TOUCH_PAN,104,208);
    assert(fabsf(scroll_value-46.8f)<0.001f && scroll_notifies==1 && !g_fp_top);
    scroll_value=1; event(TOUCH_PAN,108,216); assert(scroll_value==0 && scroll_notifies==2);
    reset(0); change_on_down=1; event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200);
    assert(downs==1 && !ups); event(TOUCH_END,100,200); assert(!ups && !commands);
    reset(1); event(TOUCH_BEGIN,900,400); assert(!picks); event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    assert(picks==1 && commands==1);settle();
    assert(picks==1 && commands==1 && releases==1 && !downs && !cameras);
    event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400); event(TOUCH_END,900,400);
    assert(commands==2);settle();assert(commands==2); /* Fast second map tap commits movement once. */
    reset(1); event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200); event(TOUCH_END,100,200);
    assert(downs==1 && ups==1 && !picks && !commands); /* UI gets first refusal. */
    reset(1); event(TOUCH_BEGIN,900,400); force_ui=1; event(TOUCH_TAP,900,400); assert(!commands && !downs);
    reset(1); event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410); event(TOUCH_TRANSFORM,950,410);
    event(TOUCH_END,950,410); assert(cameras==2 && !commands && !picks);
    reset(1); event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_END,900,400);
    assert(!cancels && !commands && gesture.info);
    reset(1); MEM32(0x8044)=5; event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410);
    assert(evaluations==2 && !commands && !cameras); event(TOUCH_END,950,410);
    assert(commands==1 && picks==3 && releases==3);
    reset(1); MEM32(0x8044)=5; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    assert(commands==1 && evaluations==1);
    reset(1); MEM32(0x8044)=5; event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400);
    event(TOUCH_TRANSFORM,950,410); event(TOUCH_END,950,410); assert(cancels==1 && !commands && !cameras);
    reset(1); MEM32(0x8044)=5; event(TOUCH_BEGIN,900,400); event(TOUCH_ABORT,900,400); assert(cancels==1 && !commands);
    reset(1); MEM32(0x8044)=5; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_END,900,400);
    assert(cancels==1 && !commands && !cameras);
    reset(1); event(TOUCH_BEGIN,900,400); mock_screen=0x5000; event(TOUCH_TAP,900,400); assert(!commands && !picks);
    reset(1); busy=1; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); assert(!picks && !commands);
    reset(1); pick_available=0; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400);settle(); assert(picks==1 && releases==1 && !commands);
    reset(1); MEM32(0x40A0)=0; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); assert(!commands && !picks);
    reset(1); event(TOUCH_BEGIN,NAN,400); event(TOUCH_TAP,900,400); assert(!commands && !picks);
    reset(1); double_object=1; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400); event(TOUCH_END,900,400);
    settle();
    assert(MEM8(0x455C)==1 && picks==2 && releases==2 && commands==1);
    reset(1); double_object=2; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(MEM8(0x455C)==1 && releases==2 && commands==1);
    reset(1); double_object=1; same_selection=0; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(!MEM8(0x455C) && commands==1);
    reset(1); double_object=1; owned=0; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(!MEM8(0x455C));
    reset(1); double_object=1; busy=1; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(!MEM8(0x455C));
    reset(1); double_object=4; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(ghost_views==1 && !MEM8(0x455C) && releases==2 && commands==1);
    reset(1); double_object=3; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);
    settle();
    assert(town_views==1 && town_selections==1 && releases==2 && commands==1);
    reset(1); double_object=3; owned=0; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(town_views==1 && !town_selections);
    reset(1); double_object=3; MEM8(0x29011)=0; event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(!town_views);
    reset(2); MEM32(0x42D4)=3; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    assert(picks==2 && commands==1 && evaluations==2 && MEM32(0x42D4)==0);
    mock_now_ns+=100000000ull; void_touch_ui_pump(); assert(commands==1);
    mock_now_ns+=300000000ull; void_touch_ui_pump(); assert(picks==2 && commands==1 && evaluations==2);
    void_touch_ui_pump(); assert(commands==1);
    g_esp=1000; touch_cursor_query(); assert(g_eax==0x101E0 && g_esp==1004 && MEMF(g_eax)==-1 && void_touch_active_mode());
    reset(2); MEM32(0x4394)=42; event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410);
    assert(evaluations==2 && !commands); event(TOUCH_END,950,410); assert(commands==1 && evaluations==3);
    reset(2); MEM32(0x4394)=42; event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400); event(TOUCH_END,900,400);
    assert(cancels==1 && previews==2 && MEM32(0x431C)==1 && !commands);
    reset(2); MEM32(0x4394)=42; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_END,900,400);
    assert(!cancels && commands==1);
    reset(2); event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410); event(TOUCH_END,950,410);
    assert(!cameras && commands==1 && picks==3 && evaluations==3);
    reset(2); event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_HOLD_DRAG,950,410);
    event(TOUCH_END,950,410); assert(!cameras && !cancels && commands==1);
    /* A held creature is still aimed at: the release gives the order. */
    reset(2); picked_active=1; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_END,900,400);
    assert(commands==1 && !cancels && !gesture.active);
    /* ToE: a second finger by the aiming one shows the card of what it aims at at once (with the
       original's RightClickEnabled option), without waiting for the tooltip. Its tap keeps the card
       until the aiming finger lifts, with no order; later second-finger taps switch the card and the
       effects panel (each request steps the tooltip mode; two return to the card). */
    reset(2); picked_active=1; MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=1;
    event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_SECOND_BEGIN,1200,300);
    assert(gesture.card && gesture.held && !gesture.cancelled && !cancels && gesture.x==900 && gesture.y==400);
    assert(held_details==1 && gesture.card_mode==1);
    MEM32(0x6008)=0x115000; void_touch_ui_pump(); assert(held_details==1);
    void_touch_ui_pump(); assert(held_details==1);
    event(TOUCH_SECOND_TAP,1200,300); assert(held_details==1 && gesture.card && gesture.card_sticky && !cancels && !commands);
    event(TOUCH_SECOND_END,1200,300); assert(gesture.card && gesture.held && gesture.world_hover && !commands);
    event(TOUCH_SECOND_BEGIN,1200,300); assert(held_details==2 && gesture.card_mode==2);
    event(TOUCH_SECOND_TAP,1200,300); event(TOUCH_SECOND_END,1200,300); assert(gesture.card);
    event(TOUCH_SECOND_BEGIN,1200,300); assert(held_details==4 && gesture.card_mode==1);
    event(TOUCH_SECOND_TAP,1200,300); event(TOUCH_SECOND_END,1200,300);
    event(TOUCH_TAP,900,400); assert(!commands && gesture.card);   /* the first finger's release, reported as a tap */
    int card_hovers=hovers; event(TOUCH_END,900,400);
    assert(!commands && !cancels && !gesture.card && !gesture.active && hovers==card_hovers+1);
    MEM32(0x6008)=0;
    /* From a drag (no hold): the card comes and goes, the drag's own state returns. */
    reset(2); picked_active=1; MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=1;
    event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410); event(TOUCH_SECOND_BEGIN,1200,300);
    assert(gesture.card && gesture.held && gesture.world_hover);
    MEM32(0x6008)=0x115000; void_touch_ui_pump(); assert(held_details==1);
    event(TOUCH_HOLD_DRAG,960,420); assert(gesture.card && gesture.x==960);
    event(TOUCH_SECOND_HOLD,1200,300); event(TOUCH_SECOND_END,1200,300);
    assert(!gesture.card && !gesture.held && !gesture.world_hover && !commands);
    event(TOUCH_END,960,420); assert(commands==1 && !cancels); MEM32(0x6008)=0;
    /* The aiming finger lifted while the card rests: no order, the card stays until the second
       finger lifts, then the gesture is over and its abort is spent. */
    reset(2); picked_active=1; MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=1;
    event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_SECOND_BEGIN,1200,300);
    MEM32(0x6008)=0x115000; void_touch_ui_pump(); assert(held_details==1);
    card_hovers=hovers; event(TOUCH_FIRST_END,910,405);
    assert(!commands && gesture.active && gesture.card==2 && hovers==card_hovers && gesture.x==900);
    void_touch_ui_pump(); assert(hovers==card_hovers+1 && MEMF(0x101E0)!=-1 && held_details==1);
    event(TOUCH_SECOND_END,1200,300); assert(!commands && !gesture.active && !gesture.card && MEMF(0x101E0)==-1);
    event(TOUCH_ABORT,0,0); assert(!commands && !cancels); MEM32(0x6008)=0;
    /* A spell aim shows its target's card the same way and still casts, or stays armed. */
    reset(2); MEM32(0x4394)=42; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400);
    event(TOUCH_SECOND_BEGIN,1200,300); assert(gesture.card && !cancels);
    event(TOUCH_SECOND_HOLD,1200,300); event(TOUCH_SECOND_END,1200,300); event(TOUCH_END,900,400);
    assert(commands==1 && !cancels);
    reset(2); MEM32(0x4394)=42; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400);
    event(TOUCH_SECOND_BEGIN,1200,300); event(TOUCH_SECOND_TAP,1200,300); event(TOUCH_SECOND_END,1200,300);
    event(TOUCH_END,900,400); assert(!commands && !cancels);   /* a tapped card: no cast */
    reset(2); MEM32(0x4394)=42; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400);
    event(TOUCH_SECOND_BEGIN,1200,300); event(TOUCH_FIRST_END,900,400); event(TOUCH_SECOND_END,1200,300);
    event(TOUCH_ABORT,0,0); assert(!commands && !cancels && !gesture.active);
    /* The resting finger moved: the card holds the view still (no camera) and no order follows. */
    reset(2); picked_active=1; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400);
    event(TOUCH_SECOND_BEGIN,1200,300); event(TOUCH_TWO_FINGER_BEGIN,1050,350);
    assert(gesture.card && gesture.held && !gesture.panning);
    event(TOUCH_TRANSFORM,1060,360); event(TOUCH_TWO_FINGER_CANCEL,1060,360); event(TOUCH_END,1060,360);
    assert(!cameras && !commands && !gesture.card);
    /* Without the option, or under a modal combat window, no card. */
    reset(2); picked_active=1; MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=0;
    event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_SECOND_BEGIN,1200,300);
    MEM32(0x6008)=0x115000; void_touch_ui_pump(); assert(!held_details); event(TOUCH_SECOND_END,1200,300);
    event(TOUCH_END,900,400); assert(commands==1); MEM32(0x6008)=0;
    reset(2); picked_active=1; MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=1;
    event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); MEM32(0x42D4)=2; event(TOUCH_SECOND_BEGIN,1200,300);
    MEM32(0x6008)=0x115000; void_touch_ui_pump(); assert(!held_details); MEM32(0x42D4)=0;
    event(TOUCH_SECOND_END,1200,300); event(TOUCH_END,900,400); MEM32(0x6008)=0;
    /* Placement keeps the old second finger: it cancels; the first finger's lift ends it at once. */
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410);
    event(TOUCH_SECOND_BEGIN,1200,300); assert(!gesture.card && gesture.cancelled && placement_cancels==1);
    event(TOUCH_FIRST_END,950,410); assert(!gesture.active);
    event(TOUCH_SECOND_END,1200,300); event(TOUCH_ABORT,0,0); assert(!placement_ends && !commands);
    /* A held interface element lifted past a second finger ends then, as an abort always did. */
    reset(1);MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);event(TOUCH_SECOND_BEGIN,200,250);
    assert(gesture.second_info&&gesture.held&&gesture.active);
    event(TOUCH_FIRST_END,110,220);assert(!gesture.active&&!inspections&&!commands&&MEMF(0x101E0)==-1);
    event(TOUCH_SECOND_END,200,250);event(TOUCH_ABORT,0,0);assert(!inspections&&!commands);
    /* Map objects: a still hold shows their card, no order there. */
    reset(1); MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=1;
    event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); MEM32(0x6008)=0x115000; void_touch_ui_pump();
    assert(held_details==1); event(TOUCH_END,900,400); assert(!commands); MEM32(0x6008)=0; MEM8(0xF39CA0)=0;
    /* ToE initiative bar: a tap selects a portrait (clicked as before, then hovered between touches as by a
       resting mouse); the next tap on it shows its card at once (UI root +70) and holds it without a finger; each
       further tap switches card and effects once (one request; two back to the card, the tooltip steps through
       its short info); a hold or second finger on the open card changes nothing. */
    reset(2); MEM32(0x4494)=0x8700; atb_unit=0x8A00; atb_unit2=0x8B00;
    MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=1;
    event(TOUCH_BEGIN,100,700); event(TOUCH_TAP,100,700); event(TOUCH_END,100,700);
    assert(downs==1 && ups==1 && !held_details && atb.unit==0x8A00 && !atb.card && !commands);
    void_touch_frame_presented(); int atb_hovers=hovers; void_touch_ui_pump(); void_touch_ui_pump();
    assert(hovers==atb_hovers+2 && MEMF(0x101E0)==91 && MEMF(0x101E4)==573);
    event(TOUCH_BEGIN,104,704); assert(gesture.atb && gesture.x==100 && gesture.y==700);
    event(TOUCH_DOUBLE_TAP,104,704); event(TOUCH_END,104,704);
    assert(held_details==1 && atb.card && atb.mode==1 && downs==1 && !doubles && ups==1);
    lifted_timeout_calls=0; g_esp=0x20000; sub_006B92E0(); assert(lifted_timeout_calls==1);   /* held like a finger */
    void_touch_frame_presented(); void_touch_ui_pump(); assert(MEMF(0x101E0)==91 && MEMF(0x101E4)==573);
    event(TOUCH_BEGIN,98,698); event(TOUCH_TAP,98,698); event(TOUCH_END,98,698);
    assert(held_details==2 && atb.mode==2 && downs==1);   /* the effects */
    event(TOUCH_BEGIN,100,700); event(TOUCH_TAP,100,700); event(TOUCH_END,100,700);
    assert(held_details==4 && atb.mode==1 && downs==1);   /* the card again */
    MEM32(0x6008)=0x115000;
    event(TOUCH_BEGIN,100,700); event(TOUCH_HOLD_BEGIN,100,700); void_touch_ui_pump();
    event(TOUCH_SECOND_BEGIN,500,300); event(TOUCH_SECOND_TAP,500,300); event(TOUCH_SECOND_END,500,300);
    event(TOUCH_END,100,700); void_touch_frame_presented(); void_touch_ui_pump();
    assert(held_details==4 && atb.card && atb.mode==1 && !commands);
    /* A touch beside the open card only closes it: no click, no order, no held tooltip any more. */
    int atb_downs=downs; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    assert(!atb.unit && !atb.card && downs==atb_downs && held_details==4 && !commands && !picks);
    g_esp=0x20000; sub_006B92E0(); assert(g_eax==0x7FFFFFFF); MEM32(0x6008)=0;
    /* Another portrait while one is open or selected: that one is selected (and clicked); a tap on the field with a
       portrait only selected is an ordinary order; the bar moving under the selection ends it. */
    event(TOUCH_BEGIN,100,700); event(TOUCH_TAP,100,700); event(TOUCH_END,100,700);
    event(TOUCH_BEGIN,100,700); event(TOUCH_TAP,100,700); event(TOUCH_END,100,700); assert(atb.card && held_details==5);
    atb_downs=downs; event(TOUCH_BEGIN,300,700); event(TOUCH_TAP,300,700); event(TOUCH_END,300,700);
    assert(atb.unit==0x8B00 && !atb.card && downs==atb_downs+1 && held_details==5);
    picked_active=1; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    assert(!atb.unit && commands==1); picked_active=0;
    event(TOUCH_BEGIN,100,700); event(TOUCH_TAP,100,700); event(TOUCH_END,100,700); assert(atb.unit==0x8A00);
    atb_unit=0x8C00; void_touch_frame_presented(); void_touch_ui_pump(); assert(!atb.unit && MEMF(0x101E0)==-1);
    /* A held portrait's second-finger taps switch its card the same way, one switch a tap. */
    reset(2); MEM32(0x4494)=0x8700; atb_unit=0x8A00; MEM32(0x6000)=0x94000; MEM32(0x94070)=0x487A84; MEM8(0xF39CA0)=1;
    event(TOUCH_BEGIN,100,700); event(TOUCH_HOLD_BEGIN,100,700); MEM32(0x6008)=0x115000;
    event(TOUCH_SECOND_BEGIN,500,300); event(TOUCH_SECOND_TAP,500,300); event(TOUCH_SECOND_END,500,300);
    assert(held_details==1 && gesture.card_mode==1);
    event(TOUCH_SECOND_BEGIN,500,300); event(TOUCH_SECOND_TAP,500,300); event(TOUCH_SECOND_END,500,300);
    assert(held_details==2 && gesture.card_mode==2);
    event(TOUCH_SECOND_BEGIN,500,300); event(TOUCH_SECOND_TAP,500,300); event(TOUCH_SECOND_END,500,300);
    assert(held_details==4 && gesture.card_mode==1);
    event(TOUCH_END,100,700); assert(!commands); MEM32(0x6008)=0;
    /* ToE minimap: a tap clicks once no second tap can follow; a double tap toggles the object highlight (Alt held)
       without any click, so the camera stays; a touch elsewhere clicks a waiting tap at once; a two-finger tap on
       the minimap toggles too, while one on the map only cancels an aim or stops the hero. */
    reset(1); minimap_hit=1; MEM32(0x6A00)=0xE23B50;
    event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200); event(TOUCH_END,100,200);
    void_touch_frame_presented(); void_touch_ui_pump(); assert(!downs && !ups && !key_down[0x12]);
    event(TOUCH_BEGIN,100,200); event(TOUCH_DOUBLE_TAP,100,200); event(TOUCH_END,100,200);
    mock_now_ns+=500000000ull; void_touch_frame_presented(); void_touch_ui_pump();
    assert(key_down[0x12] && !downs && !ups && !doubles);
    event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200); event(TOUCH_END,100,200);
    void_touch_frame_presented(); void_touch_ui_pump(); assert(!downs);
    mock_now_ns+=500000000ull; void_touch_ui_pump(); assert(downs==1 && ups==1 && MEMF(0x101E0)==91);
    void_touch_frame_presented(); void_touch_ui_pump(); assert(MEMF(0x101E0)==-1);   /* the hover leaves */
    event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200); event(TOUCH_END,100,200);
    event(TOUCH_BEGIN,900,400); assert(downs==2 && ups==2); event(TOUCH_END,900,400);
    event(TOUCH_BEGIN,100,200); event(TOUCH_TAP,100,200); event(TOUCH_END,100,200);
    /* Another screen meanwhile: no click there, and the highlight leaves with its screen. */
    mock_screen=0x5000; mock_now_ns+=500000000ull; void_touch_ui_pump(); assert(downs==2 && !key_down[0x12]);
    mock_screen=0x4000;
    event(TOUCH_BEGIN,100,200); event(TOUCH_TWO_FINGER_BEGIN,110,210); event(TOUCH_TWO_FINGER_TAP,110,210);
    event(TOUCH_END,110,210); assert(key_down[0x12] && !commands && !cancels && downs==2);
    event(TOUCH_BEGIN,100,200); event(TOUCH_TWO_FINGER_BEGIN,110,210); event(TOUCH_TWO_FINGER_TAP,110,210);
    event(TOUCH_END,110,210); assert(!key_down[0x12] && downs==2);
    MEM32(0x6A00)=0; event(TOUCH_BEGIN,100,200); event(TOUCH_DOUBLE_TAP,100,200); event(TOUCH_END,100,200);
    assert(!key_down[0x12] && doubles==1);   /* another window's double tap stays its own */
    reset(1); event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,910,410); event(TOUCH_TWO_FINGER_TAP,910,410);
    event(TOUCH_END,910,410); assert(!key_down[0x12] && !hero_stops && !commands);
    reset(1); hero_moving=1; event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,910,410);
    event(TOUCH_TWO_FINGER_TAP,910,410); event(TOUCH_END,910,410); assert(!key_down[0x12] && hero_stops==1 && !commands);
    /* Two fingers on the battlefield are the camera and give no order. */
    reset(2); event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400); event(TOUCH_TRANSFORM,920,410);
    event(TOUCH_END,920,410); assert(cameras==1 && last_camera_kind==1 && !commands && !cancels);
    reset(2); event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400); event(TOUCH_TILT,920,410);
    event(TOUCH_END,920,410); assert(!cameras && tilts==1 && !commands);
    reset(1); event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400); event(TOUCH_TILT,920,410);
    event(TOUCH_END,920,410); assert(tilts==1 && !cameras && !commands);
    /* A three-finger chord restores the battle home without any preceding taps/order. */
    reset(2); event(TOUCH_BEGIN,900,400); assert(camera_pose_gets==1);
    event(TOUCH_TWO_FINGER_BEGIN,900,400); event(TOUCH_THREE_FINGER_TAP,900,400); event(TOUCH_END,900,400);
    mock_now_ns+=1000000000ull; void_touch_ui_pump();
    assert(camera_pose_sets==1 && last_pose_pitch==2 && !commands && !combat_shortcuts && camera_pose_gets==1);
    /* A later camera gesture never replays an already dispatched tap. */
    reset(2); event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    event(TOUCH_BEGIN,900,400); assert(commands==1); event(TOUCH_PAN,950,410); assert(commands==1);
    MEM32(0x42E0)=0x188; event(TOUCH_END,950,410); assert(commands==2);
    /* Adventure reset restores native default angles, keeping zoom and position. */
    reset(1); MEMF(0xF339F4)=-.8f; MEMF(0xF339F8)=.7f;
    event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400);
    event(TOUCH_THREE_FINGER_TAP,900,400); event(TOUCH_END,900,400);settle();
    assert(!commands && camera_pose_sets==1 && last_pose_kind==0 && last_pose[1]==-.8f && last_pose[2]==.7f);
    for(int i=0;i<10;++i)if(i!=1&&i!=2)assert(last_pose[i]==(float)(i+1));
    /* A chord on UI or in targeting mode is consumed without clicking/casting. */
    reset(1);event(TOUCH_BEGIN,100,200);event(TOUCH_TWO_FINGER_BEGIN,100,200);
    event(TOUCH_THREE_FINGER_TAP,100,200);event(TOUCH_END,100,200);
    assert(!downs && !ups && !camera_pose_sets && !commands);
    reset(2);MEM32(0x4394)=42;event(TOUCH_BEGIN,900,400);event(TOUCH_TWO_FINGER_BEGIN,900,400);
    event(TOUCH_THREE_FINGER_TAP,900,400);event(TOUCH_END,900,400);
    assert(cancels==1 && !camera_pose_sets && !commands);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410); event(TOUCH_END,950,410);
    assert(placement_begins==1 && placement_moves==1 && placement_ends==1 && releases==3 && !commands && !evaluations);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    assert(placement_begins==1 && placement_ends==1 && releases==2 && !commands);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400); event(TOUCH_END,900,400);
    assert(placement_begins==1 && placement_cancels==1 && !placement_ends && !commands);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); event(TOUCH_ABORT,900,400);
    assert(placement_cancels==1 && !placement_ends && !commands);
    reset(2); busy=1; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400); assert(!commands && !evaluations);
    reset(1); double_object=1; MEM32(0x4760)=1; MEM32(0x4750)=0xE739C; MEM32(0x4754)=0x18000; MEM32(0x4758)=0; MEM8(0x475C)=MEM8(0x475D)=0;
    event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(MEM32(0x4760)==2 && MEM8(0x45E8)==1);
    reset(1); double_object=1; MEM32(0x4760)=1; MEM32(0x4754)=0x18100;
    event(TOUCH_BEGIN,900,400); event(TOUCH_DOUBLE_TAP,900,400);settle(); assert(MEM32(0x4760)==1);
    reset(1); MEM32(0x8044)=5; event(TOUCH_BEGIN,900,400); event(TOUCH_HOLD_BEGIN,900,400); event(TOUCH_ABORT,900,400); assert(cancels==1 && !commands);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); event(TOUCH_TWO_FINGER_BEGIN,900,400); event(TOUCH_ABORT,900,400);
    assert(placement_cancels==1 && cancels==1 && !commands);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); force_ui=1; event(TOUCH_TAP,900,400); event(TOUCH_END,900,400);
    assert(placement_begins==1 && placement_cancels==1 && !placement_ends && !commands);
    /* The reserve (PlacementBar) is interface the placement controller owns: a stack is picked up
       from it and dropped back on the field, or dropped into it from the field. */
    reset(2); MEM32(0x42E0)=0x1000; force_ui=1; reserve_slot=3; event(TOUCH_BEGIN,900,400);
    assert(!gesture.ui && gesture.placement && placement_begins==1 && !downs);
    force_ui=0; reserve_slot=-1; event(TOUCH_PAN,950,410); event(TOUCH_END,950,410);
    assert(placement_moves==1 && placement_ends==1 && !placement_cancels && !commands && !downs && !ups);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); event(TOUCH_PAN,950,410);
    force_ui=1; reserve_slot=2; event(TOUCH_END,950,410);
    assert(placement_begins==1 && placement_ends==1 && !placement_cancels && !commands);
    reset(2); MEM32(0x42E0)=0x1000; event(TOUCH_BEGIN,900,400); force_ui=1; reserve_slot=0; event(TOUCH_TAP,900,400);
    assert(placement_begins==1 && placement_ends==1 && !placement_cancels && !commands);
    /* Other interface over the arena stays interface during placement. */
    reset(2); MEM32(0x42E0)=0x1000; force_ui=1; event(TOUCH_BEGIN,900,400); event(TOUCH_TAP,900,400);
    assert(gesture.ui || !gesture.active); assert(!placement_begins && !placement_ends && downs==1);

    /* Announcement ownership is native, includes a read-only probe, and consumes a whole gesture. */
    reset(1);MEM32(0x40EC)=0x8600;announcement_visible=1;
    event(TOUCH_BEGIN,900,400);assert(gesture.ui && gesture.announcement && announcement_probes==1);
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(announcement_actions==1 && !downs && !ups && !picks && !commands);
    reset(1);MEM32(0x40EC)=0x8600;
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    settle();
    assert(!gesture.announcement && !announcement_actions && commands==1 && releases==1); /* AL zero, dirty EAX. */
    reset(1);MEM32(0x40EC)=0x8600;announcement_visible=1;
    event(TOUCH_BEGIN,900,400);event(TOUCH_HOLD_BEGIN,900,400);void_touch_ui_pump();event(TOUCH_END,900,400);
    assert(!announcement_actions && !downs && !ups && !picks && !commands && !cancels);
    reset(1);MEM32(0x40EC)=0x8600;announcement_visible=1;
    event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,950,410);event(TOUCH_TWO_FINGER_BEGIN,900,400);
    event(TOUCH_TWO_FINGER_CANCEL,900,400);event(TOUCH_END,900,400);
    assert(!announcement_actions && !downs && !ups && !commands && !cameras && !cancels);
    reset(1);MEM32(0x40EC)=0x8600;announcement_visible=1;
    event(TOUCH_BEGIN,900,400);announcement_visible=0;event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(!announcement_actions && !downs && !commands && !picks); /* A vanished icon cannot click through. */
    reset(1);MEM32(0x40EC)=0x8600;event(TOUCH_BEGIN,900,400);announcement_visible=1;
    event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);assert(announcement_actions==1 && !commands && !picks);
    reset(1);MEM32(0x40EC)=0x8600;announcement_visible=announcement_changes_screen=1;
    event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    assert(announcement_actions==1 && !gesture.active && !downs && !ups && !commands);

    /* A cancelled native mode invalidates the gesture; arming during a gesture promotes it to aiming. */
    reset(1);MEM32(0x8044)=5;event(TOUCH_BEGIN,900,400);MEM32(0x8044)=0;
    event(TOUCH_PAN,950,410);event(TOUCH_END,950,410);
    assert(!commands && !cameras && !cancels && picks==1 && releases==1 && gesture.cancelled);
    reset(1);MEM32(0x8044)=5;event(TOUCH_BEGIN,900,400);MEM32(0x8044)=0;
    event(TOUCH_END,900,400);assert(!commands && !cancels && !gesture.active);
    reset(1);event(TOUCH_BEGIN,900,400);MEM32(0x8044)=5;
    event(TOUCH_PAN,950,410);assert(gesture.aiming && evaluations==1 && !cameras && !commands);
    event(TOUCH_END,950,410);assert(commands==1 && picks==2 && releases==2);
    reset(1);event(TOUCH_BEGIN,900,400);MEM32(0x8044)=5;
    event(TOUCH_TWO_FINGER_BEGIN,900,400);event(TOUCH_ABORT,900,400);assert(cancels==1 && !commands);
    reset(1);MEM32(0x8044)=5;event(TOUCH_BEGIN,900,400);clear_target_during_prepare=1;
    event(TOUCH_END,900,400);assert(!commands && releases==2 && gesture.cancelled);
    reset(2);MEM32(0x4394)=42;event(TOUCH_BEGIN,900,400);MEM32(0x4394)=0;
    event(TOUCH_PAN,950,410);event(TOUCH_END,950,410);
    assert(!commands && !cameras && !cancels && evaluations==1 && gesture.cancelled);
    reset(2);MEM32(0x4388)=0x8200;event(TOUCH_BEGIN,900,400);MEM32(0x4388)=0;
    event(TOUCH_END,900,400);assert(!commands && !cancels && !gesture.active);
    reset(2);event(TOUCH_BEGIN,900,400);MEM32(0x438C)=0x8200;   /* the cursor previews from the first touch */
    event(TOUCH_PAN,950,410);assert(gesture.aiming && evaluations==2 && !cameras);
    event(TOUCH_END,950,410);assert(commands==1 && evaluations==3);
    reset(2);event(TOUCH_BEGIN,900,400);MEM32(0x4394)=42;
    event(TOUCH_TWO_FINGER_BEGIN,900,400);event(TOUCH_ABORT,900,400);assert(cancels==1 && !commands);
    reset(2);MEM32(0x4394)=42;event(TOUCH_BEGIN,900,400);clear_target_during_prepare=1;
    event(TOUCH_END,900,400);assert(!commands && gesture.cancelled && context_ctors==context_dtors);
    reset(2);combat_pick_changes_screen=1;event(TOUCH_BEGIN,900,400);
    assert(picks==1 && !evaluations && !commands && !previews && context_ctors==context_dtors);
    event(TOUCH_END,900,400);settle();assert(!evaluations && !commands && !combat_shortcuts);

    /* An unarmed double-tap of the freshly picked active stack enters native
       Combat_Cast immediately; a later pump must never repeat it. */
    reset(2);picked_active=cast_available=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);
    assert(combat_shortcuts==1 && !commands);settle();
    assert(combat_shortcuts==1 && !commands && evaluations==2 && context_ctors==2 && context_dtors==2);
    reset(2);picked_active=cast_available=1;shortcut_effect=1;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);settle();
    assert(combat_shortcuts==1 && MEM32(0x4394)==42 && !commands && !cancels); /* The arming double itself cannot cast. */
    reset(2);picked_active=cast_available=1;shortcut_effect=2;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);settle();
    assert(combat_shortcuts==1 && !gesture.active && !commands && !downs && !ups);
    reset(2);cast_available=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);settle();
    assert(!combat_shortcuts && commands==1 && evaluations==3 && context_ctors==3 && context_dtors==3);
    reset(2);picked_active=1;event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);settle();
    assert(!combat_shortcuts && commands==1 && evaluations==3 && context_ctors==context_dtors);
    reset(2);picked_active=cast_available=1;MEM32(0x4394)=42;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);
    assert(!combat_shortcuts && commands==1 && evaluations==2); /* Armed doubles retain target release at once. */
    settle();assert(!combat_shortcuts && commands==1);
    reset(2);picked_active=cast_available=busy=1;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);settle();
    assert(!combat_shortcuts && !commands && context_ctors==context_dtors);
    reset(2);picked_active=cast_available=1;MEM32(0x42E0)=0;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);settle();
    assert(!combat_shortcuts && !commands && context_ctors==context_dtors);
    reset(2);picked_active=cast_available=1;event(TOUCH_BEGIN,900,400);force_ui=1;
    event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);assert(!combat_shortcuts && !commands && picks==1);
    settle();assert(!combat_shortcuts && !commands);
    reset(2);picked_active=cast_available=cast_changes_screen=1;
    event(TOUCH_BEGIN,900,400);event(TOUCH_DOUBLE_TAP,900,400);event(TOUCH_END,900,400);settle();
    assert(!combat_shortcuts && !commands && !gesture.active && context_ctors==context_dtors);
    reset_town();event(TOUCH_BEGIN,900,400);event(TOUCH_TRANSFORM,920,410);event(TOUCH_END,920,410);
    assert(cameras==1 && last_camera_kind==2 && !commands && !town_actions && !downs);
    reset_town();MEM32(0x4294)=0;event(TOUCH_BEGIN,900,400);event(TOUCH_PAN,920,410);
    assert(cameras==1 && last_camera_kind==2 && !commands && !town_actions); /* Native camera owns cinematic interruption/readiness. */
    reset(0);force_ui=1;event(TOUCH_BEGIN,900,400);event(TOUCH_TWO_FINGER_BEGIN,900,400);
    event(TOUCH_TRANSFORM,910,405);event(TOUCH_END,910,405);assert(ui_pans==1 && !downs && !ups && !cameras);
    reset_dnd();event(TOUCH_BEGIN,900,400);event(TOUCH_TAP,900,400);event(TOUCH_END,900,400);
    event(TOUCH_BEGIN,900,400);event(TOUCH_SECOND_BEGIN,920,400);event(TOUCH_TRANSFORM,920,410);
    assert(dnd_cancels==1 && !dnd_drops && ui_pans==1);
    reset(2);MEM32(0x4394)=42;event(TOUCH_BEGIN,900,400);mock_screen=0x5000;
    cancels=commands=context_ctors=context_dtors=0;
    event(TOUCH_SECOND_BEGIN,920,400);
    assert(!gesture.active && !cancels && !commands && !context_ctors && !context_dtors);
    assert(MEMF(0x101E0)==-1 && MEMF(0x101E4)==-1);
    reset(0); event(TOUCH_BEGIN,100,200); assert(void_touch_active_mode());
    MEM32(0x15000)=0; MEM32(0x15010)=0; g_ecx=0x15000; g_esp=2000; sub_008863A0();
    assert(!lifted_tracker_calls && g_esp==2016 && !MEM32(0x15010));
    g_esp=2000; sub_006B92E0(); assert(g_eax==0x7FFFFFFFu && g_esp==2004 && !lifted_timeout_calls);
    event(TOUCH_HOLD_BEGIN,100,200);
    g_ecx=0x15000; g_esp=2000; sub_008863A0(); assert(lifted_tracker_calls==1 && MEM32(0x15010)==0x3FFFFFFFu);
    g_esp=2000; sub_006B92E0(); assert(g_eax==250 && lifted_timeout_calls==1);
    event(TOUCH_END,100,200);
    MEM32(0x15000)=0x77000; MEM8(0x15018)=0; g_ecx=0x15000; g_esp=2000; sub_008863A0();
    assert(lifted_tracker_calls==2 && MEM8(0x15018)==1 && MEMF(0x15008)==-1 && MEMF(0x1500C)==-1);
    reset(1);MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);
    event(TOUCH_SECOND_BEGIN,200,250);assert(gesture.held&&!gesture.panning&&!inspections);
    event(TOUCH_SECOND_TAP,200,250);assert(inspections==1&&gesture.inspecting&&!downs&&!ups&&!commands);
    void_touch_ui_pump();assert(MEMF(0x101E0)==91&&MEMF(0x101E4)==173&&gesture.x==100&&gesture.y==200);
    event(TOUCH_SECOND_BEGIN,250,300);event(TOUCH_SECOND_HOLD,250,300);
    assert(inspections==2&&!downs&&!ups);void_touch_ui_pump();assert(MEMF(0x101E0)==91&&MEMF(0x101E4)==173);
    event(TOUCH_END,100,200);assert(!gesture.active&&MEMF(0x101E0)==-1&&!commands);
    reset(1);MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);event(TOUCH_SECOND_BEGIN,200,250);
    inspection_changes_screen=1;event(TOUCH_SECOND_TAP,200,250);assert(inspections==1&&!gesture.inspecting&&MEMF(0x101E0)==-1);
    reset(1);MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);event(TOUCH_SECOND_BEGIN,900,250);event(TOUCH_SECOND_TAP,900,250);
    assert(!inspections&&!commands&&!downs&&!ups); /* No click-through into the map. */
    reset(1);void_touch_event invalid_rotation={TOUCH_BEGIN,900,400,0,0,1,NAN};
    void_touch_engine_event(&invalid_rotation);assert(!gesture.active && !cameras);
    /* A physical pointer cancels a pending touch, restores native picking and expires at exactly 30s. */
    reset(0);event(TOUCH_BEGIN,100,200);assert(touch_mode);
    event(TOUCH_POINTER,0,0);assert(!touch_mode&&!gesture.active);
    physical_seen=1;physical_moved_ns=mock_now_ns;
    g_esp=1000;touch_cursor_query();assert(g_eax==0x1234&&g_esp==1004);
    assert(MEMF(0xFE6DA0)==500&&MEMF(0xFE6DA4)==250);
    int draws=cursor_draws;mock_now_ns=physical_moved_ns+29999999999ull;
    g_esp=1000;touch_cursor_draw();assert(cursor_draws==draws+1&&g_esp==1008);
    mock_now_ns++;g_eax=123;g_esp=1000;touch_cursor_draw();
    assert(cursor_draws==draws+1&&g_eax==123&&g_esp==1008);
    physical_moved_ns=++mock_now_ns;g_esp=1000;touch_cursor_draw();assert(cursor_draws==draws+2);
    event(TOUCH_BEGIN,100,200);g_esp=1000;touch_cursor_draw();assert(cursor_draws==draws+2&&touch_mode);
    reset(1);int camera_count=cameras;event(TOUCH_PAD_CAMERA,0,0);
    assert(cameras==camera_count&&!touch_mode);
    void_touch_event camera_event={TOUCH_PAD_CAMERA,0,0,0,.1f,1,.2f};
    void_touch_engine_event(&camera_event);assert(cameras==camera_count+1&&tilts&&!touch_mode);
    reset(0);edit_kind=1;event(TOUCH_POINTER_CLICK,100,200);
    assert(!text_arms&&!touch_mode);focused_field=0x30000;void_touch_frame_presented();void_touch_ui_pump();
    assert(text_arms==1&&!touch_mode&&void_touch_text_focus(&text_field,&text_kind,&text_epoch));
    assert(text_field==0x30000&&text_kind==1);
    puts("PASS native touch: UI ownership, book/town/mentor/ghost native actions, persistent inventory pickup/drop/cancel, hold-only tooltips and world information, immediate battlefield orders, three-finger camera home, direct world context and lifecycle guards");
    return 0;
}
'''


class TouchEngineTest(unittest.TestCase):
    def test_native_ui_and_world_ownership(self):
        source = (ROOT / "android/host/touch_engine.c").read_text(encoding="utf-8")
        source = source.replace('#include "host.h"', '').replace('#include "touch.h"', '')
        compile_probe("touch_engine", HARNESS, {
            "touch_engine_actual.h": source,
            "touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf-8"),
            "input.h": (ROOT / "android/host/input.h").read_text(encoding="utf-8"),
        })


if __name__ == "__main__":
    unittest.main()
