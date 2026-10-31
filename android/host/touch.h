#ifndef HOMM5_TOUCH_H
#define HOMM5_TOUCH_H

#include <stdint.h>

/* Shared with GameActivity: positions and deltas here are backbuffer pixels.
 * TOUCH_TILT carries a two-finger vertical "shove" in dy.
 * TOUCH_THREE_FINGER_TAP is one simultaneous, stationary three-contact chord.
 * TOUCH_SECOND_END, the resting second finger lifted while the first goes on;
 * TOUCH_FIRST_END, the first finger lifted while the second rests, followed by TOUCH_ABORT.
 * TOUCH_TWO_FINGER_TAP: two contacts within 120 ms, lifted within 300 ms, unmoved; it replaces
 * the TOUCH_TWO_FINGER_CANCEL of a resting pair and precedes TOUCH_END. */
enum {
    TOUCH_BEGIN, TOUCH_TAP, TOUCH_DOUBLE_TAP, TOUCH_PAN, TOUCH_TRANSFORM,
    TOUCH_HOLD_BEGIN, TOUCH_HOLD_DRAG, TOUCH_END, TOUCH_TWO_FINGER_BEGIN,
    TOUCH_TWO_FINGER_CANCEL, TOUCH_ABORT,
    TOUCH_SECOND_BEGIN, TOUCH_SECOND_TAP, TOUCH_SECOND_HOLD,
    TOUCH_THREE_FINGER_TAP, TOUCH_TILT, TOUCH_POINTER, TOUCH_PAD_CAMERA, TOUCH_POINTER_CLICK,
    TOUCH_SECOND_END, TOUCH_FIRST_END, TOUCH_TWO_FINGER_TAP
};
#define TOUCH_KIND_LAST TOUCH_TWO_FINGER_TAP
typedef struct {
    int kind;
    float x, y, dx, dy, scale, rotation;
} void_touch_event;

/* Android thread enqueues; only the guest window thread drains the queue. */
void void_touch_enqueue(const void_touch_event *event);
void void_touch_pump(void);
void void_touch_render_frame_pump(void);
void void_touch_engine_event(const void_touch_event *event);
int void_touch_engine_ready(int kind);
void void_touch_engine_init(void);
void void_touch_ui_pump(void);
void void_touch_frame_presented(void);
int void_touch_active_mode(void);

/* Android records 0.5..2.0; the guest window thread applies native UI relayout. */
void void_touch_set_scale(float scale);
void void_touch_scale_pump(void);
int void_touch_ui_pan(uint32_t screen, float dx, float dy);
void void_touch_set_render_scale(float scale);
void void_touch_render_pump(void);

/* Text operations retain the generation of the user-selected engine field. */
void void_touch_text_arm(void);
uint32_t void_touch_text_cancel(void);
int void_touch_text_enqueue(uint32_t generation, const uint16_t *text, uint32_t count);
int void_touch_text_key(uint32_t generation, uint32_t key, uint32_t count);
void void_touch_text_pump(void);
int void_touch_text_focus(uint32_t *field, int *kind, uint32_t *epoch);
void void_touch_text_dispatch(uint32_t field, int kind, int key, uint32_t value);

/* Camera implementation uses the engine's projection and clamped setter.
 * kind: 0 adventure, 1 combat, 2 town. */
int void_touch_camera(uint32_t screen, int kind, float x, float y,
                      float dx, float dy, float scale, float rotation);
/* Pitch by a vertical finger travel (pixels) within the engine's limits. */
int void_touch_camera_tilt(uint32_t screen, int kind, float dy);
/* The camera pose (ten CameraPos floats); set moves the operator's target. */
int void_touch_camera_pose(uint32_t screen, int kind, float pose[10], int set, int immediate);
void void_touch_camera_init(void);
void void_touch_combat_frame(uint32_t screen, float width, float height, float hud_top, float top, float bottom);
void void_touch_adventure_frame(uint32_t screen, float height, float top, float bottom);

/* port_settings.c: the port's console variables (game options pages). */
float void_port_camera_sensitivity(void);
/* Cursor offsets are fractions of the shorter backbuffer side. */
float void_port_cursor_offset(int vertical);
int void_port_touch_cursor(void);
void void_port_settings_pump(void);

#endif
