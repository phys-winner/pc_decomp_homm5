/* Android only records bounded edits; the VM verifies the destination before insertion. */
#include "host.h"
#include "input.h"
#include "touch.h"

#define TEXT_OPS 64
#define TEXT_UNITS 256
#define TEXT_PREVIEW_UNITS 4096
typedef struct {
    uint32_t generation, key, count;
    uint16_t text[TEXT_UNITS];
} text_op;
static pthread_mutex_t text_lock = PTHREAD_MUTEX_INITIALIZER;
static text_op text_queue[TEXT_OPS];
static unsigned text_count;
static uint32_t text_generation = 1, text_field, text_epoch;
static int text_kind, text_allowed, text_notify;
static uint16_t text_preview[TEXT_PREVIEW_UNITS];
static uint32_t text_preview_generation, text_preview_count, text_preview_caret;
static int text_preview_valid;

#ifdef VOID_ANDROID_APP
void void_android_text_focus(int enabled, uint32_t generation);
void void_android_text_state(uint32_t generation, const uint16_t *text, uint32_t count, uint32_t caret);
#else
static void void_android_text_focus(int enabled, uint32_t generation) { (void)enabled; (void)generation; }
static void void_android_text_state(uint32_t generation, const uint16_t *text, uint32_t count, uint32_t caret)
{ (void)generation; (void)text; (void)count; (void)caret; }
#endif

static int text_readable(uint32_t address, uint32_t bytes, uint32_t alignment)
{
    return address && !(address & (alignment - 1)) && bytes <= UINT32_MAX - address &&
           void_vm_readable(address, bytes);
}

static int text_snapshot(uint32_t field, int kind, uint16_t *text, uint32_t *count, uint32_t *caret)
{
    uint32_t vector;
    int64_t position;
    if (kind == 1) {
        if (!text_readable(field, 0x13C, 4)) return 0;
        vector = field + 0x134;
        /* The line editor's visible caret is relative to its horizontal start. */
        position = (int64_t)(int32_t)MEM32(field + 0x130) + (int32_t)MEM32(field + 0x11C);
    } else if (kind == 2) {
        if (!text_readable(field, 0x124, 4)) return 0;
        uint32_t table = MEM32(field + 0xF8);
        if (!text_readable(table, 8, 4)) return 0;
        uint32_t getter = MEM32(table + 4);
        if (!getter || !void_dispatch_find(getter)) return 0;
        vector = void_call_guest_this(getter, field + 0xF8, 0, NULL);
        if (!text_readable(vector, 8, 4) || !text_readable(field + 0x120, 4, 4)) return 0;
        position = MEM32(field + 0x120);
    } else return 0;
    uint32_t begin = MEM32(vector), end = MEM32(vector + 4);
    if ((begin | end) & 1u || end < begin || end - begin > TEXT_PREVIEW_UNITS * 2u ||
        (end != begin && !text_readable(begin, end - begin, 2))) return 0;
    *count = (end - begin) / 2u;
    *caret = position < 0 ? 0 : position > *count ? *count : (uint32_t)position;
    if (*count) memcpy(text, GPTR(begin), *count * sizeof text[0]);
    return 1;
}

static int text_current(uint32_t field, int kind, uint32_t epoch, uint32_t generation)
{
    pthread_mutex_lock(&text_lock);
    int valid = text_allowed && text_generation == generation && text_field == field &&
                text_kind == kind && text_epoch == epoch;
    pthread_mutex_unlock(&text_lock);
    return valid;
}

static void text_publish(uint32_t field, int kind, uint32_t epoch, uint32_t generation)
{
    uint16_t text[TEXT_PREVIEW_UNITS];
    uint32_t count, caret;
    if (!field || !text_current(field, kind, epoch, generation) ||
        !text_snapshot(field, kind, text, &count, &caret)) return;
    if (text_preview_valid && text_preview_generation == generation && text_preview_count == count &&
        text_preview_caret == caret && !memcmp(text_preview, text, count * sizeof text[0])) return;
    uint32_t current = 0, current_epoch = 0;
    int current_kind = 0;
    if (!void_touch_text_focus(&current, &current_kind, &current_epoch) || current != field ||
        current_kind != kind || current_epoch != epoch) {
        void_touch_text_cancel();
        return;
    }
    if (!text_current(field, kind, epoch, generation)) return;
    memcpy(text_preview, text, count * sizeof text[0]);
    text_preview_generation = generation; text_preview_count = count; text_preview_caret = caret;
    text_preview_valid = 1;
    void_android_text_state(generation, text, count, caret);
}

void void_touch_text_arm(void)
{
    pthread_mutex_lock(&text_lock);
    text_allowed = 1;
    text_count = 0;
    ++text_generation;
    text_notify = 1;
    pthread_mutex_unlock(&text_lock);
}

uint32_t void_touch_text_cancel(void)
{
    pthread_mutex_lock(&text_lock);
    text_allowed = 0;
    text_field = 0;
    text_count = 0;
    ++text_generation;
    text_notify = 1;
    uint32_t generation = text_generation;
    pthread_mutex_unlock(&text_lock);
    return generation;
}

static int text_append(const text_op *operation)
{
    pthread_mutex_lock(&text_lock);
    int accepted = text_allowed && text_field && operation->generation == text_generation && text_count < TEXT_OPS;
    if (accepted) text_queue[text_count++] = *operation;
    pthread_mutex_unlock(&text_lock);
    return accepted;
}

int void_touch_text_enqueue(uint32_t generation, const uint16_t *text, uint32_t count)
{
    if (!text || !count || count > TEXT_UNITS) return 0;
    text_op operation = { .generation = generation, .count = count };
    for (uint32_t i = 0; i < count; ++i) {
        uint8_t byte;
        if (text[i] < 32 || !void_u16_to_ansi(text[i], &byte)) return 0;
        operation.text[i] = void_ansi_to_u16(byte);
    }
    return text_append(&operation);
}

int void_touch_text_key(uint32_t generation, uint32_t key, uint32_t count)
{
    if ((key != 8 && key != 46 && key != 13) || !count || count > TEXT_UNITS) return 0;
    text_op operation = { .generation = generation, .key = key, .count = count };
    return text_append(&operation);
}

void void_touch_text_pump(void)
{
    pthread_mutex_lock(&text_lock);
    int allowed = text_allowed;
    pthread_mutex_unlock(&text_lock);
    uint32_t field = 0, epoch = 0;
    int kind = 0;
    if (allowed) void_touch_text_focus(&field, &kind, &epoch);
    pthread_mutex_lock(&text_lock);
    if (!text_allowed) field = 0;
    if (field != text_field || (field && (kind != text_kind || epoch != text_epoch))) {
        text_field = field; text_kind = kind; text_epoch = epoch;
        text_count = 0;
        ++text_generation;
        text_notify = 1;
    }
    text_op local[TEXT_OPS];
    unsigned count = text_count;
    memcpy(local, text_queue, count * sizeof local[0]);
    text_count = 0;
    uint32_t generation = text_generation;
    int notify = text_notify;
    text_notify = 0;
    pthread_mutex_unlock(&text_lock);
    if (notify) void_android_text_focus(field != 0, generation);
    for (unsigned i = 0; i < count; ++i) {
        for (uint32_t j = 0; j < local[i].count; ++j) {
            uint32_t current = 0, current_epoch = 0;
            int current_kind = 0;
            pthread_mutex_lock(&text_lock);
            int valid = text_allowed && text_generation == local[i].generation;
            pthread_mutex_unlock(&text_lock);
            if (!valid || !void_touch_text_focus(&current, &current_kind, &current_epoch) ||
                current != field || current_kind != kind || current_epoch != epoch) {
                void_touch_text_cancel();
                return;
            }
            if (local[i].key == 13) {
                void_input_key(13, 1);
                void_input_key(13, 0);
                void_touch_text_cancel();
                return;
            } else {
                void_touch_text_dispatch(field, kind, local[i].key != 0,
                                         local[i].key ? local[i].key : local[i].text[j]);
            }
        }
    }
    text_publish(field, kind, epoch, generation);
}
