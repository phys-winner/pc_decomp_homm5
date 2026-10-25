/* Host input state shared by user32, DirectInput and the Android layer. */
#ifndef VOID_INPUT_H
#define VOID_INPUT_H
#include <stdint.h>

/* Screen ("desktop") size the guest sees. */
void void_input_screen_size(int *w, int *h);
void void_input_set_screen_size(int w, int h);
/* Cursor in screen coordinates. */
void void_input_cursor(uint32_t *x, uint32_t *y);
void void_input_set_cursor(int x, int y);
/* GetKeyState: bit 15 down, bit 0 toggled. */
int16_t void_input_key_state(uint32_t vk);
/* Character a WM_KEYDOWN of vk produces (TranslateMessage), 0 if none. */
uint32_t void_input_vk_char(uint32_t vk);
/* Called from message APIs: moves queued host events into guest queues. */
void void_input_pump(void);

/* Host side (any thread): record events from Android. */
void void_input_key(uint32_t vk, int down);
void void_input_mouse_move(int dx, int dy);
void void_input_mouse_warp(int x, int y);   /* cursor only: no DirectInput motion */
void void_input_mouse_button(int button, int down);
void void_input_mouse_wheel(int delta);
/* Last physical pointer position and age; untouched by guest SetCursorPos. */
int void_input_pointer(uint32_t *x, uint32_t *y, uint64_t *moved_ns);

/* DirectInput snapshots. */
void void_input_keyboard_snapshot(uint8_t keys[256]);
void void_input_mouse_snapshot(int32_t *dx, int32_t *dy, int32_t *dz, uint8_t buttons[8]);
/* Buffered DirectInput events: returns count copied (dwOfs, dwData, dwTimeStamp, dwSequence). */
typedef struct { uint32_t ofs, data, time, seq; } void_input_event;
int void_input_keyboard_events(void_input_event *out, int max, int peek);
int void_input_mouse_events(void_input_event *out, int max, int peek);
uint32_t void_vk_to_dik(uint32_t vk);

/* Scripted input from $VOID_INPUT or <data>/input.txt, if present (script.c). */
void void_input_script_start(void);

#endif
