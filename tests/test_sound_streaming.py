"""Execute the real DirectSound cursors/mixer and Android AAudio output with spies."""
import unittest
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
from test_mmx_packed import CLANG


DS_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <errno.h>
static unsigned char memory[0x40000];
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM8(p) (*(uint8_t*)GPTR(p))
#define MEM16(p) (*(uint16_t*)GPTR(p))
#define MEM32(p) (*(uint32_t*)GPTR(p))
#define DS_OK 0u
#define DSERR_INVALIDCALL 0x88780032u
#define DSERR_INVALIDPARAM 0x80070057u
#define DSBCAPS_CTRL3D 0x10u
#define MIX_RATE 48000
#define MIX_CHUNK 480
#define MIX_CATCHUP 8
#define CLOCK_MONOTONIC 1
#define TIMER_ABSTIME 1
#define DSTRACE(...) ((void)0)
typedef struct {uint32_t guest;} void_com_object;
typedef int pthread_mutex_t;
static int mix_lock,lock_depth;
static int pthread_mutex_lock(int *p) {(void)p;assert(!lock_depth++);return 0;}
static int pthread_mutex_unlock(int *p) {(void)p;assert(!--lock_depth);return 0;}
#include "buffer_type.h"
static dsbuf_t buffer,*buffers;
static float listener_pos[3],listener_front[3]={0,0,1},listener_top[3]={0,1,0};
static float rolloff=1,distance_factor=1;
static int mixer_running,dstrace;
static uint32_t args[8];
#define ARG(i) args[i]
#define BUFF (&buffer)
#define COM_METHOD(prefix,name,count) static uint32_t prefix##_##name(void)
static unsigned notifications;
static void signal_event(uint32_t event) {assert(event==123);notifications++;}
static void void_log(const char *format,...) {(void)format;}
static int64_t now_ns,last_output_ns;
static unsigned sleeps,outputs;
static int simulate_lateness;
static unsigned priority_calls;
static void mixer_priority(void) {++priority_calls;}
static void mixer_cores(void) {}
static int clock_gettime(int clock,struct timespec *out) {
    assert(clock==CLOCK_MONOTONIC);out->tv_sec=(time_t)(now_ns/1000000000);
    out->tv_nsec=(long)(now_ns%1000000000);return 0;
}
static int clock_nanosleep(int clock,int flags,const struct timespec *target,void *remain) {
    assert(clock==CLOCK_MONOTONIC && flags==TIMER_ABSTIME && !remain);
    int64_t deadline=(int64_t)target->tv_sec*1000000000+target->tv_nsec;
    ++sleeps;
    if(simulate_lateness==1 && sleeps==1) {now_ns=5000000;return EINTR;}
    if(deadline>now_ns) now_ns=deadline;
    if(simulate_lateness==1 && sleeps==2) now_ns+=100000000;
    if(simulate_lateness==2) now_ns+=100000;
    return 0;
}
static uint32_t void_audio_output(const int16_t *frames,uint32_t count) {
    assert(!lock_depth && count==480 && outputs<4);
    if(outputs) assert(now_ns-last_output_ns>=10000000);
    assert(abs(frames[0]-(1000+(int)outputs*480))<=1);
    assert(frames[0]==frames[1]);
    last_output_ns=now_ns;
    if(++outputs==4) mixer_running=0;
    if(simulate_lateness==1 && outputs==2) now_ns+=45000000;
    return 0;
}
#include "sound_functions.h"
static void setup(void) {
    memset(memory,0,sizeof memory);memset(&buffer,0,sizeof buffer);
    buffer.data=0x10000;buffer.size=4096;buffer.channels=2;
    buffer.rate=buffer.frequency=48000;buffer.bits=16;buffer.block=4;
    buffer.playing=buffer.looping=1;buffers=&buffer;
    args[1]=0x100;args[2]=0x104;
}
static void cursor_contract(void) {
    setup();buffer.play_pos=4000;
    assert(dsb_GetCurrentPosition()==DS_OK && MEM32(0x100)==4000 && MEM32(0x104)==1824);
    args[1]=0xFFFFFFFFu;args[2]=3000;args[3]=0x108;args[4]=0x10C;
    args[5]=0x110;args[6]=0x114;args[7]=1;
    assert(dsb_Lock()==DS_OK);
    assert(MEM32(0x108)==buffer.data+1824 && MEM32(0x10C)==2272);
    assert(MEM32(0x110)==buffer.data && MEM32(0x114)==728);
    buffer.playing=0;
    assert(dsb_Lock()==DS_OK && MEM32(0x108)==buffer.data+4000 && MEM32(0x10C)==96);
    args[1]=0x100;args[2]=0x104;
    assert(dsb_GetCurrentPosition()==DS_OK && MEM32(0x104)==4000);
    buffer.playing=1;buffer.frequency=96000;
    assert(dsb_GetCurrentPosition()==DS_OK && MEM32(0x104)==3744);
    args[1]=4001;assert(dsb_SetCurrentPosition()==DS_OK && buffer.play_pos==4000 && !buffer.frac);
    args[1]=4097;assert(dsb_SetCurrentPosition()==DS_OK && buffer.play_pos==0);
    args[1]=4096;args[2]=4;args[7]=0;
    assert(dsb_Lock()==DSERR_INVALIDPARAM);
}
static void refill_and_timing(void) {
    setup();buffer.channels=1;buffer.block=2;buffer.size=1920*2;
    for(unsigned i=0;i<1920;i++) MEM16(buffer.data+2*i)=(uint16_t)(1000+i);
    buffer.notify_count=1;buffer.notify_offset[0]=960;buffer.notify_event[0]=123;
    now_ns=last_output_ns=0;sleeps=outputs=notifications=0;
    simulate_lateness=1;mixer_running=1;mixer_main(NULL);
    assert(outputs==4 && sleeps==5 && buffer.play_pos==0 && notifications==1);
    now_ns=last_output_ns=0;sleeps=outputs=0;
    simulate_lateness=2;mixer_running=1;mixer_main(NULL);
    assert(now_ns==40100000 && outputs==4 && sleeps==4 && buffer.play_pos==0);
    /* Refill the consumed half and verify the next ring cycle reads new PCM. */
    for(unsigned i=0;i<480;i++) MEM16(buffer.data+2*i)=6000;
    float mix[960];mix_chunk(mix,480);
    assert(fabsf(mix[0]-6000.0f/32768)<.000001f && buffer.play_pos==960);
    buffer.looping=0;buffer.play_pos=buffer.size-960;
    mix_chunk(mix,480);assert(!buffer.playing && !buffer.play_pos);
    assert(!lock_depth);
}
static void stale_ring_diagnostic(void) {
    setup();dstrace=1;buffer.channels=1;buffer.block=2;buffer.size=1920;
    float mix[960];
    /* Static looping assets must not be diagnosed as stale streams. */
    for(unsigned i=0;i<8;i++) mix_chunk(mix,480);
    assert(!buffer.unchanged_wraps && !buffer.live_unlocks);
    args[1]=0;args[2]=960;args[3]=0x108;args[4]=0x10C;
    args[5]=0;args[6]=0;args[7]=0;
    now_ns=100000000;assert(dsb_Lock()==DS_OK);
    args[1]=buffer.data;args[2]=960;args[3]=0;args[4]=0;
    now_ns=135000000;assert(dsb_Unlock()==DS_OK);
    assert(buffer.unlocks==1 && buffer.live_unlocks==1 && buffer.max_refill_ns==35000000);
    mix_chunk(mix,480);mix_chunk(mix,480); /* establish first full lap */
    assert(!buffer.unchanged_wraps);
    mix_chunk(mix,480);mix_chunk(mix,480);
    assert(buffer.unchanged_wraps==1); /* same PCM reused, no Unlock */
    now_ns=140000000;assert(dsb_Unlock()==DS_OK);
    mix_chunk(mix,480);mix_chunk(mix,480);
    assert(buffer.unchanged_wraps==1 && buffer.unlocks==2);
    args[1]=0;assert(dsb_SetCurrentPosition()==DS_OK);
    mix_chunk(mix,480);mix_chunk(mix,480);
    assert(buffer.unchanged_wraps==1); /* seeking starts a new observation */
    dstrace=0;assert(dsb_Unlock()==DS_OK);
    mix_chunk(mix,480);mix_chunk(mix,480);
    assert(buffer.unchanged_wraps==1 && buffer.unlocks==2 && !lock_depth);
}
int main(void) {
    cursor_contract();refill_and_timing();stale_ring_diagnostic();
    puts("PASS actual DirectSound: shared cursor, wrapped refill, frequency/stop, EINTR, late wake without catch-up burst, exact chunk progress");
    return 0;
}
'''

DS_REFILL_HARNESS = r'''
static int64_t output_at[64];
static unsigned output_count,stop_after;
static uint32_t script[16];
static unsigned script_count,script_index;
static uint32_t void_audio_output(const int16_t *frames,uint32_t count) {
    (void)frames;
    assert(!lock_depth && count==480 && output_count<64);
    output_at[output_count++]=now_ns;
    if(output_count==stop_after) mixer_running=0;
    return script_index<script_count?script[script_index++]:0;
}
#include "sound_functions.h"
static void setup(void) {
    memset(memory,0,sizeof memory);memset(&buffer,0,sizeof buffer);
    buffer.data=0x10000;buffer.size=4096;buffer.channels=2;
    buffer.rate=buffer.frequency=48000;buffer.bits=16;buffer.block=4;
    buffer.playing=buffer.looping=1;buffers=&buffer;
}
static void refill_catchup(void) {
    static const uint32_t replies[]={0,1500,1020,540,60,100000,100000,100000,100000,100000,100000,100000,100000,100000,0};
    setup();memcpy(script,replies,sizeof replies);script_count=sizeof replies/sizeof replies[0];script_index=0;
    now_ns=0;sleeps=0;output_count=0;simulate_lateness=0;stop_after=15;mixer_running=1;
    mixer_main(NULL);
    assert(output_count==15 && sleeps==4 && output_at[0]==10000000);
    for(unsigned i=1;i<5;i++) assert(output_at[i]==20000000);   /* shortfall mixed at once */
    for(unsigned i=5;i<14;i++) assert(output_at[i]==30000000);  /* at most MIX_CATCHUP extra chunks */
    assert(output_at[14]==40000000);                              /* the clock keeps its schedule */
    assert(buffer.play_pos==(15u*480u*4u)%4096u && !lock_depth);
}
static double tone_sinad(double freq) {
    const double pi=3.14159265358979323846;
    static float mix[960];
    setup();buffer.rate=buffer.frequency=44100;buffer.size=4410*4;   /* whole periods per lap */
    for(unsigned i=0;i<4410;i++) {
        int16_t v=(int16_t)floor(16384.0*sin(2*pi*freq*i/44100.0)+0.5);
        MEM16(buffer.data+4*i)=(uint16_t)v;MEM16(buffer.data+4*i+2)=(uint16_t)v;
    }
    double ss=0,sc=0,cc=0,ys=0,yc=0,yy=0;
    for(unsigned chunk=0;chunk<24;chunk++) {
        mix_chunk(mix,480);
        if(chunk<2) continue;   /* window filled from silence at the start */
        for(unsigned i=0;i<480;i++) {
            double position=(double)(chunk*480+i)*44100.0/48000.0;
            double w=2*pi*freq*position/44100.0,sw=sin(w),cw=cos(w),y=mix[2*i];
            assert(mix[2*i]==mix[2*i+1]);
            ss+=sw*sw;sc+=sw*cw;cc+=cw*cw;ys+=y*sw;yc+=y*cw;yy+=y*y;
        }
    }
    double det=ss*cc-sc*sc,a=(ys*cc-yc*sc)/det,b=(yc*ss-ys*sc)/det;
    double fit=a*a*ss+2*a*b*sc+b*b*cc,residual=yy-2*(a*ys+b*yc)+fit;
    assert(fabs(sqrt(a*a+b*b)-0.5)<0.01);   /* flat passband */
    return 10*log10(fit/residual);
}
static void refill_behind_cursor(void) {
    static float first[960],reference[960],mix[960];
    for(int run=0;run<2;run++) {
        setup();buffer.rate=buffer.frequency=44100;buffer.size=4096*4;
        for(unsigned i=0;i<4096;i++) {
            int16_t v=(int16_t)((int)(i*7919u%20000u)-10000);
            MEM16(buffer.data+4*i)=(uint16_t)v;MEM16(buffer.data+4*i+2)=(uint16_t)v;
        }
        mix_chunk(first,480);
        uint32_t play=buffer.play_pos/4;
        assert(play>=440 && play<=441);
        /* DirectSound lets the application refill everything behind the play cursor. */
        if(run) for(uint32_t i=play-32;i<play;i++) MEM16(buffer.data+4*i)=MEM16(buffer.data+4*i+2)=0x7FFF;
        mix_chunk(run?mix:reference,480);
    }
    assert(!memcmp(mix,reference,sizeof mix));
    args[1]=0;assert(dsb_SetCurrentPosition()==DS_OK && !buffer.rs_valid && !lock_depth);
}
int main(void) {
    refill_catchup();
    double s1=tone_sinad(1000),s5=tone_sinad(5000),s12=tone_sinad(12000);
    printf("44.1->48 kHz SINAD: 1 kHz %.1f dB, 5 kHz %.1f dB, 12 kHz %.1f dB\n",s1,s5,s12);
    assert(s1>=80 && s5>=80 && s12>=75);
    refill_behind_cursor();
    puts("PASS DirectSound refill: bounded immediate shortfall, schedule kept, band-limited 44.1 kHz, no re-read behind the cursor");
    return 0;
}
'''

AAUDIO_WANTED_MAIN = r'''
int main(void) {
    int16_t frames[960]={0};
    reset_script(frames);uint32_t wanted=void_audio_output(frames,480);
    assert(stream && stream->size==960 && stream->written==960 && !wanted);
    assert(stream->mode==AAUDIO_PERFORMANCE_MODE_NONE && selected_mode==AAUDIO_PERFORMANCE_MODE_NONE);   /* normal output by default */
    stream->read=600;reset_script(frames);wanted=void_audio_output(frames,480);
    assert(stream->written==1440 && wanted==120);   /* 960 - (1440 - 600) */
    stream->read=1440;reset_script(frames);wanted=void_audio_output(frames,480);
    assert(wanted==480);                            /* only this chunk is queued */
    stream->read=stream->written+576;reset_script(frames);wanted=void_audio_output(frames,480);
    assert(!wanted);                                /* inconsistent position: no refill */
    /* A partial write, a paused or a failed output asks for nothing. */
    stream->read=stream->written+480;
    reset_script(frames);memset(results,0,sizeof results);results[0]=100;result_count=128;
    wanted=void_audio_output(frames,480);
    assert(!wanted && audio_dropped_frames==380);
    audio_paused=1;reset_script(frames);assert(!void_audio_output(frames,480) && !stream);
    audio_paused=0;reset_script(frames);results[0]=-899;result_count=1;
    assert(!void_audio_output(frames,480) && !stream && !lock_depth);
    puts("PASS AAudio refill: normal output by default, shortfall below the buffer size; nothing when full, inconsistent, partial, paused or failed");
    return 0;
}
'''

AAUDIO_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#define CLOCK_MONOTONIC 1
#define AAUDIO_OK 0
#define AAUDIO_FORMAT_PCM_I16 1
#define AAUDIO_PERFORMANCE_MODE_NONE 10
#define AAUDIO_PERFORMANCE_MODE_LOW_LATENCY 12
#define __ATOMIC_RELAXED 0
#define __atomic_load_n(pointer,order) (*(pointer))
#define PTHREAD_MUTEX_INITIALIZER 0
typedef int pthread_mutex_t;
typedef int32_t aaudio_result_t;
typedef struct {int closed,started,paused,prefilled,mode,size,capacity,burst,xruns;int64_t written,read;} AAudioStream;
typedef struct {int unused;} AAudioStreamBuilder;
static int lock_depth,audio_paused,opens,closes,starts,stops,builder_deletes;
static uint64_t pause_generation;
static uint64_t void_audio_pause_state(void) { return pause_generation | (audio_paused ? 1u : 0u); }
static unsigned change_generation_after_write;
static unsigned prime_calls,change_generation_in_prime;
static int start_error,open_error,create_error,prime_result=480;
static int64_t now_ns;
static int32_t results[128];
static unsigned result_count,result_index,write_calls,accepted_count,logs,level_reports,fallback_reports;
static int selected_mode;
static int hardware_burst=96,hardware_capacity=1920,hardware_size=192;
static int requested_capacity,buffer_changes,buffer_error;
static int16_t accepted[16384];
static AAudioStream streams[16];
static AAudioStreamBuilder builder;
static const int16_t *chunk_base;
static uint32_t chunk_offset;
static int pthread_mutex_lock(int *p) {(void)p;assert(!lock_depth++);return 0;}
static int pthread_mutex_unlock(int *p) {(void)p;assert(!--lock_depth);return 0;}
static int clock_gettime(int clock,struct timespec *out) {
    assert(clock==CLOCK_MONOTONIC);out->tv_sec=(time_t)(now_ns/1000000000);
    out->tv_nsec=(long)(now_ns%1000000000);return 0;
}
static int usleep(unsigned us) {now_ns+=(int64_t)us*1000;return 0;}
static void void_log(const char *format,...) {
    if(!strncmp(format,"[audio] last 10 s:",18)) ++level_reports;
    if(strstr(format,"using normal output")) ++fallback_reports;
    ++logs;
}
static aaudio_result_t AAudio_createStreamBuilder(AAudioStreamBuilder **out) {
    assert(lock_depth==1);*out=&builder;return create_error;
}
static void AAudioStreamBuilder_setFormat(AAudioStreamBuilder *b,int format) {assert(b==&builder && format==1);}
static void AAudioStreamBuilder_setChannelCount(AAudioStreamBuilder *b,int channels) {assert(b==&builder && channels==2);}
static void AAudioStreamBuilder_setSampleRate(AAudioStreamBuilder *b,int rate) {assert(b==&builder && rate==48000);}
static void AAudioStreamBuilder_setPerformanceMode(AAudioStreamBuilder *b,int mode) {
    assert(b==&builder && (mode==12 || mode==10));selected_mode=mode;
}
static void AAudioStreamBuilder_setBufferCapacityInFrames(AAudioStreamBuilder *b,int frames) {
    assert(b==&builder);requested_capacity=frames;
}
static aaudio_result_t AAudioStreamBuilder_openStream(AAudioStreamBuilder *b,AAudioStream **out) {
    assert(lock_depth==1 && b==&builder && opens<16);
    if(open_error) return open_error;
    *out=&streams[opens++];(*out)->mode=selected_mode;
    (*out)->size=hardware_size;(*out)->capacity=hardware_capacity;(*out)->burst=hardware_burst;return 0;
}
static void AAudioStreamBuilder_delete(AAudioStreamBuilder *b) {assert(b==&builder);builder_deletes++;}
static aaudio_result_t AAudioStream_requestStart(AAudioStream *s) {
    assert(lock_depth==1 && s && !s->closed);starts++;
    if(start_error) return start_error;
    now_ns+=49000000; /* A slow device start must not consume a real PCM prefix. */
    s->started=1;s->paused=0;return 0;
}
static aaudio_result_t AAudioStream_close(AAudioStream *s) {
    assert(lock_depth==1 && s && !s->closed);s->closed=1;closes++;return 0;
}
static aaudio_result_t AAudioStream_requestStop(AAudioStream *s) {
    assert(lock_depth==1 && s && !s->closed);stops++;return 0;
}
static int32_t AAudioStream_getXRunCount(AAudioStream *s) {assert(s && !s->closed);return s->xruns;}
static int64_t AAudioStream_getFramesWritten(AAudioStream *s) {assert(s && !s->closed);return s->written;}
static int64_t AAudioStream_getFramesRead(AAudioStream *s) {assert(s && !s->closed);return s->read;}
static int32_t AAudioStream_getBufferSizeInFrames(AAudioStream *s) {assert(s && !s->closed);return s->size;}
static int32_t AAudioStream_getBufferCapacityInFrames(AAudioStream *s) {assert(s && !s->closed);return s->capacity;}
static int32_t AAudioStream_getFramesPerBurst(AAudioStream *s) {assert(s && !s->closed);return s->burst;}
static aaudio_result_t AAudioStream_setBufferSizeInFrames(AAudioStream *s,int frames) {
    assert(s && !s->closed && frames>0);++buffer_changes;
    if(buffer_error) return buffer_error;
    frames=(frames+s->burst-1)/s->burst*s->burst;
    s->size=frames<s->capacity?frames:s->capacity;return s->size;
}
static aaudio_result_t AAudioStream_write(AAudioStream *s,const void *data,int32_t frames,int64_t timeout) {
    assert(lock_depth==1 && s && !s->closed && !s->paused);
    assert(timeout>=0 && timeout<=20000000 && frames>0);
    assert(s->started ? timeout>0 : timeout==0);
    if(!s->started) {
        const int16_t *prime=data;
        for(int32_t i=0;i<frames*2;i++) assert(prime[i]==0);
        ++prime_calls;now_ns+=1000000;
        if(change_generation_in_prime) pause_generation+=4;
        int32_t result=prime_result<frames?prime_result:frames;
        if(result>0) {s->prefilled+=result;s->written+=result;}
        return result;
    }
    assert(data==chunk_base+chunk_offset*2);
    int32_t result=result_index<result_count?results[result_index++]:frames;
    ++write_calls;now_ns+=1000000;
    if(result>0) {
        assert(result<=frames && accepted_count+(unsigned)result*2<=16384);
        memcpy(accepted+accepted_count,data,(size_t)result*2*sizeof(int16_t));
        accepted_count+=(unsigned)result*2;chunk_offset+=(unsigned)result;s->written+=result;
    }
    if(change_generation_after_write==write_calls) pause_generation+=4;
    return result;
}
#include "android_audio.h"
static void reset_script(const int16_t *frames) {
    chunk_base=frames;chunk_offset=0;result_index=result_count=0;write_calls=accepted_count=0;
}
int main(void) {
    int16_t frames[960];for(int i=0;i<960;i++) frames[i]=(int16_t)(i-480);
    reset_script(frames);results[0]=100;results[1]=200;results[2]=180;result_count=3;prime_result=100;
    void_audio_output(frames,480);
    assert(opens==1 && starts==1 && builder_deletes==1 && write_calls==3);
    assert(prime_calls==1 && stream->prefilled==100);prime_result=480;
    assert(now_ns==53000000);
    assert(accepted_count==960 && !memcmp(accepted,frames,sizeof frames));
    assert(audio_short_writes==2 && !audio_dropped_frames && !audio_errors && !lock_depth);
    /* A zero timeout preserves the same pending suffix, then resumes exactly. */
    reset_script(frames);results[0]=123;results[1]=0;results[2]=357;result_count=3;
    void_audio_output(frames,480);
    assert(write_calls==3 && accepted_count==960 && !memcmp(accepted,frames,sizeof frames));
    /* Repeated timeouts are bounded, rather than spinning or replaying PCM. */
    reset_script(frames);memset(results,0,sizeof results);result_count=128;
    int64_t before=now_ns;void_audio_output(frames,480);
    assert(now_ns-before>=100000000 && now_ns-before<=101000000);
    assert(write_calls==50 && !accepted_count && audio_dropped_frames==480);
    /* A disconnect closes on this owner thread and the next chunk reopens. */
    reset_script(frames);results[0]=100;results[1]=-899;result_count=2;
    void_audio_output(frames,480);
    assert(!stream && closes==1 && audio_errors==1 && accepted_count==200);
    assert(audio_dropped_frames==860 && !memcmp(accepted,frames,400));
    reset_script(frames);void_audio_output(frames,480);
    assert(stream && opens==2 && accepted_count==960 && !memcmp(accepted,frames,sizeof frames));
    /* Background uses the existing mixer clock: no second 10ms sleep. */
    reset_script(frames);audio_paused=1;before=now_ns;void_audio_output(frames,480);
    assert(!stream && closes==2 && !write_calls && now_ns==before);
    void_audio_output(frames,480);assert(closes==2 && now_ns==before);
    audio_paused=0;void_audio_output(frames,480);
    assert(stream && opens==3 && starts==3 && accepted_count==960);
    /* Failed start, open and foreground reopen never cache an unusable stream. */
    pthread_mutex_lock(&audio_lock);audio_close_failed(-899);pthread_mutex_unlock(&audio_lock);start_error=-900;
    reset_script(frames);void_audio_output(frames,480);
    assert(!stream && closes==4 && !write_calls && !accepted_count);start_error=0;open_error=-901;
    reset_script(frames);void_audio_output(frames,480);assert(!stream && !write_calls);open_error=0;
    void_audio_output(frames,480);assert(stream && accepted_count==960);
    audio_paused=1;reset_script(frames);void_audio_output(frames,480);
    assert(!stream && !write_calls && !lock_depth);audio_paused=0;
    reset_script(frames);void_audio_output(frames,480);assert(stream && accepted_count==960);
    audio_paused=1;void_audio_output(frames,480);audio_paused=0;start_error=-903;
    reset_script(frames);void_audio_output(frames,480);assert(!stream && !write_calls && !accepted_count);
    start_error=0;create_error=-904;reset_script(frames);void_audio_output(frames,480);
    assert(!stream && !write_calls);create_error=0;
    /* A failed prefill must not start or cache a broken output stream. */
    reset_script(frames);prime_result=-905;int before_starts=starts;
    void_audio_output(frames,480);assert(!stream && !write_calls && starts==before_starts);prime_result=480;
    /* Attempted but unaccepted PCM must not advance the ten-second meter. */
    assert(!level_reports);
    for(int i=0;i<1000;i++) {
        reset_script(frames);memset(results,0,sizeof results);result_count=128;
        void_audio_output(frames,480);
    }
    assert(!level_reports);
    for(int i=0;i<1000;i++) {reset_script(frames);void_audio_output(frames,480);}
    assert(level_reports==1);
    assert(logs>0 && stops==closes && !lock_depth);
    puts("PASS actual AAudio: exact partial suffix, zero timeout, bounded failure, accepted-only samples, reconnect and foreground ownership");
    return 0;
}
'''


def directsound_headers():
    source = (ROOT / "android/host/dsound.c").read_text(encoding="utf8")
    types = source[source.index("typedef struct dsbuf"):source.index("static pthread_mutex_t mix_lock")]
    functions = "\n".join(function(source, signature) for signature in (
        "static float sample_at(", "static double bessel_i0(", "static void rs_build(", "static float rs_source(",
        "static void rs_seek(", "static void rs_frame_at(", "static void notify_passed(", "static void mix_chunk(",
        "static void *mixer_main(", "static uint32_t buffer_write_cursor(", "COM_METHOD(dsb, GetCurrentPosition,",
        "COM_METHOD(dsb, Lock,", "COM_METHOD(dsb, SetCurrentPosition,", "COM_METHOD(dsb, Unlock,"))
    return {"buffer_type.h": types, "sound_functions.h": functions}


class SoundStreamingTest(unittest.TestCase):
    def test_aaudio_recovers_underruns_even_when_every_write_succeeds(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        globals_ = source[source.index("static AAudioStream *stream;"):source.index("static void audio_close_stream(")]
        functions = "\n".join(function(source, signature) for signature in (
            "static void audio_close_stream(", "static void audio_close_failed(",
            "static uint32_t audio_write_frames(", "uint32_t void_audio_output("))
        harness = AAUDIO_HARNESS[:AAUDIO_HARNESS.index("int main(void) {")] + r'''
int main(void) {
    audio_normal_output=0;   /* the low-latency recovery a build can start with */
    int16_t frames[960]={0};
    reset_script(frames);void_audio_output(frames,480);
    assert(requested_capacity==1920 && stream->size==960 && accepted_count==960);
    assert(buffer_changes==1 && !audio_normal_output && !audio_errors);
    for(int i=0;i<100;i++) {reset_script(frames);void_audio_output(frames,480);}
    assert(buffer_changes==1 && !audio_normal_output);
    /* Successful blocking writes can still leave gaps between chunks. */
    stream->xruns=1;reset_script(frames);void_audio_output(frames,480);assert(stream->size==1440);
    stream->xruns=2;reset_script(frames);void_audio_output(frames,480);assert(stream->size==1920);
    for(int i=3;i<=4;i++) {stream->xruns=i;reset_script(frames);void_audio_output(frames,480);assert(stream);}
    reset_script(frames);void_audio_output(frames,480); /* stable chunk resets failure streak */
    for(int i=5;i<=7;i++) {
        stream->xruns=i;reset_script(frames);void_audio_output(frames,480);
        assert(accepted_count==960 && !memcmp(accepted,frames,sizeof frames));
        assert((stream!=NULL)==(i<7));
    }
    assert(audio_normal_output && fallback_reports==1 && !audio_dropped_frames && !audio_short_writes);
    reset_script(frames);void_audio_output(frames,480);
    assert(stream && stream->mode==AAUDIO_PERFORMANCE_MODE_NONE && accepted_count==960);
    stream->xruns=100;reset_script(frames);void_audio_output(frames,480);assert(stream && fallback_reports==1);
    /* A new route reports its own burst/capacity, which may exceed our request. */
    pthread_mutex_lock(&audio_lock);audio_close_stream();pthread_mutex_unlock(&audio_lock);
    audio_normal_output=0;hardware_burst=512;hardware_size=512;hardware_capacity=2048;
    reset_script(frames);void_audio_output(frames,480);assert(stream->size==1024);
    stream->xruns=1;reset_script(frames);void_audio_output(frames,480);assert(stream->size==1536);
    stream->xruns=2;reset_script(frames);void_audio_output(frames,480);assert(stream->size==2048);
    /* Unavailable xrun counters do not trigger recovery. */
    stream->xruns=-1;
    for(int i=0;i<5;i++) {reset_script(frames);void_audio_output(frames,480);assert(stream);}
    /* Rejected tuning leaves a usable stream; sustained gaps still recover. */
    pthread_mutex_lock(&audio_lock);audio_close_stream();pthread_mutex_unlock(&audio_lock);
    hardware_burst=96;hardware_size=192;hardware_capacity=768;buffer_error=-899;
    reset_script(frames);void_audio_output(frames,480);assert(stream && stream->size==192);
    for(int i=1;i<=3;i++) {
        stream->xruns=i;reset_script(frames);void_audio_output(frames,480);
        assert((stream!=NULL)==(i<3));
    }
    assert(audio_normal_output && fallback_reports==2 && !audio_dropped_frames && !audio_short_writes);
    assert(!lock_depth);
    puts("PASS AAudio underruns: chunk-sized buffer, device burst rounding, bounded growth, successful-write recovery and sticky fallback");
    return 0;
}
'''
        compile_probe("aaudio-underrun-recovery", harness, {"android_audio.h": globals_ + functions})

    def test_aaudio_zero_progress_falls_back_once_without_replaying_pcm(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        globals_ = source[source.index("static AAudioStream *stream;"):source.index("static void audio_close_stream(")]
        functions = "\n".join(function(source, signature) for signature in (
            "static void audio_close_stream(", "static void audio_close_failed(",
            "static uint32_t audio_write_frames(", "uint32_t void_audio_output("))
        harness = AAUDIO_HARNESS[:AAUDIO_HARNESS.index("int main(void) {")] + r'''
static void zero_chunk(const int16_t *frames) {
    reset_script(frames);memset(results,0,sizeof results);result_count=128;
    void_audio_output(frames,480);
}
int main(void) {
    audio_normal_output=0;   /* the low-latency recovery a build can start with */
    int16_t old[960],fresh[960];
    for(int i=0;i<960;i++) {old[i]=(int16_t)(i-480);fresh[i]=(int16_t)(12000+i);}
    reset_script(old);void_audio_output(old,480);
    assert(opens==1 && stream->mode==12 && accepted_count==960);
    int64_t before=now_ns;zero_chunk(old);zero_chunk(old);
    assert(now_ns-before==200000000 && opens==1 && !closes && !fallback_reports);
    /* Any accepted prefix breaks a run of zero-progress deadlines. */
    reset_script(old);memset(results,0,sizeof results);results[0]=100;result_count=128;
    void_audio_output(old,480);assert(accepted_count==200 && !closes && !fallback_reports);
    zero_chunk(old);zero_chunk(old);assert(!closes && !fallback_reports);
    /* Background and a whole hidden lifecycle cycle each reset the run. */
    audio_paused=1;pause_generation+=2;reset_script(old);void_audio_output(old,480);
    assert(!stream && closes==1 && !write_calls);
    audio_paused=0;pause_generation+=2;reset_script(old);void_audio_output(old,480);
    zero_chunk(old);zero_chunk(old);pause_generation+=4;zero_chunk(old);
    assert(opens==3 && closes==2 && stream->mode==12 && !fallback_reports);
    zero_chunk(old);assert(closes==2 && !fallback_reports);
    reset_script(old);void_audio_output(old,480);assert(accepted_count==960);
    /* The third complete 100ms deadline closes the stalled LL stream once. */
    zero_chunk(old);zero_chunk(old);assert(stream && !fallback_reports);
    zero_chunk(old);assert(!stream && closes==3 && fallback_reports==1 && audio_errors==1);
    reset_script(fresh);void_audio_output(fresh,480);
    assert(opens==4 && stream->mode==10 && accepted_count==960);
    assert(!memcmp(accepted,fresh,sizeof fresh));
    /* Normal output never returns to the broken MMAP path, even on resume. */
    zero_chunk(fresh);zero_chunk(fresh);zero_chunk(fresh);
    assert(opens==4 && closes==3 && fallback_reports==1);
    audio_paused=1;pause_generation+=2;reset_script(fresh);void_audio_output(fresh,480);
    audio_paused=0;pause_generation+=2;void_audio_output(fresh,480);
    assert(opens==5 && stream->mode==10 && accepted_count==960);
    reset_script(fresh);results[0]=-899;result_count=1;void_audio_output(fresh,480);
    assert(!stream && fallback_reports==1);
    reset_script(fresh);void_audio_output(fresh,480);
    assert(opens==6 && stream->mode==10 && accepted_count==960 && !lock_depth);
    puts("PASS stalled AAudio: three zero deadlines only, partial/epoch reset, one normal fallback, fresh PCM and sticky mode on reconnect");
    return 0;
}
'''
        compile_probe("aaudio-zero-progress-recovery", harness, {"android_audio.h": globals_ + functions})

    def test_aaudio_discards_previous_foreground_generation(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        globals_ = source[source.index("static AAudioStream *stream;"):source.index("static void audio_close_stream(")]
        functions = "\n".join(function(source, signature) for signature in (
            "static void audio_close_stream(", "static void audio_close_failed(",
            "static uint32_t audio_write_frames(", "uint32_t void_audio_output("))
        harness = AAUDIO_HARNESS[:AAUDIO_HARNESS.index("int main(void) {")] + r'''
int main(void) {
    int16_t frames[960];for(int i=0;i<960;i++) frames[i]=(int16_t)(i-480);
    reset_script(frames);void_audio_output(frames,480);
    assert(opens==1 && closes==0 && accepted_count==960);
    /* Pausing must discard the hardware queue before returning to foreground. */
    audio_paused=1;pause_generation+=2;reset_script(frames);
    void_audio_output(frames,480);
    assert(!stream && streams[0].closed && closes==1 && !write_calls && !audio_errors);
    void_audio_output(frames,480);assert(opens==1 && closes==1 && !write_calls);
    audio_paused=0;pause_generation+=2;
    void_audio_output(frames,480);assert(opens==2 && stream==&streams[1] && accepted_count==960);
    /* A whole pause/resume can happen while the mixer thread is descheduled. */
    pause_generation+=4;reset_script(frames);void_audio_output(frames,480);
    assert(opens==3 && closes==2 && streams[1].closed && accepted_count==960);
    /* A partial write cannot retry pre-pause PCM after a hidden pause/resume. */
    reset_script(frames);results[0]=100;result_count=1;change_generation_after_write=1;
    uint64_t dropped=audio_dropped_frames;void_audio_output(frames,480);
    assert(write_calls==1 && accepted_count==200 && audio_dropped_frames==dropped);
    assert(!memcmp(accepted,frames,400));change_generation_after_write=0;
    reset_script(frames);void_audio_output(frames,480);
    assert(opens==4 && closes==3 && streams[2].closed && accepted_count==960);
    /* A background transition during initial prefill must not start old PCM. */
    pause_generation+=4;reset_script(frames);prime_result=128;
    change_generation_in_prime=1;int before_starts=starts;
    void_audio_output(frames,480);
    assert(!stream && opens==5 && closes==5 && starts==before_starts && audio_dropped_frames==dropped);
    change_generation_in_prime=0;prime_result=480;reset_script(frames);void_audio_output(frames,480);
    assert(opens==6 && stream->prefilled==480 && accepted_count==960);
    assert(!audio_errors && !lock_depth && stops==closes);
    puts("PASS foreground epochs: observed pause discards queue, hidden pause/resume reopens, partial PCM never crosses epochs");
    return 0;
}
'''
        compile_probe("aaudio-foreground-generation", harness, {"android_audio.h": globals_ + functions})

    def test_pause_generation_keeps_short_and_duplicate_transitions(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        functions = "\n".join(function(source, signature) for signature in (
            "uint64_t void_audio_pause_state(",
            "JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativePause("))
        harness = r'''
#include <assert.h>
#include <stdint.h>
#define JNIEXPORT
#define JNICALL
typedef void JNIEnv;
typedef void *jobject;
typedef unsigned char jboolean;
static int audio_paused;
static uint64_t audio_pause_state;
#include "pause_functions.h"
int main(void) {
    assert(void_audio_pause_state() == 0);
    for (unsigned i = 0; i < 10000; ++i) {
        uint64_t before = void_audio_pause_state();
        Java_org_homm5_port_GameActivity_nativePause(0,0,0);
        assert(void_audio_pause_state() == before);
        Java_org_homm5_port_GameActivity_nativePause(0,0,1);
        uint64_t paused = void_audio_pause_state();
        assert(paused == before + 3 && audio_paused == 1);
        Java_org_homm5_port_GameActivity_nativePause(0,0,1);
        assert(void_audio_pause_state() == paused);
        Java_org_homm5_port_GameActivity_nativePause(0,0,0);
        assert(void_audio_pause_state() == before + 4 && audio_paused == 0);
    }
    return 0;
}
'''
        compile_probe("audio-pause-generation", harness, {"pause_functions.h": functions},
                      compiler_override=CLANG, extra_flags=("/clang:--target=x86_64-pc-windows-msvc",))

    def test_directsound_cursor_refill_and_late_worker(self):
        compile_probe("sound-streaming", DS_HARNESS, directsound_headers())

    def test_directsound_refill_catchup_and_bandlimited_resampling(self):
        harness = DS_HARNESS[:DS_HARNESS.index("static uint32_t void_audio_output(")] + DS_REFILL_HARNESS
        compile_probe("sound-refill-resample", harness, directsound_headers())

    def test_aaudio_reports_queue_shortfall(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        globals_ = source[source.index("static AAudioStream *stream;"):source.index("static void audio_close_stream(")]
        functions = "\n".join(function(source, signature) for signature in (
            "static void audio_close_stream(", "static void audio_close_failed(",
            "static uint32_t audio_write_frames(", "uint32_t void_audio_output("))
        harness = AAUDIO_HARNESS[:AAUDIO_HARNESS.index("int main(void) {")] + AAUDIO_WANTED_MAIN
        compile_probe("aaudio-queue-shortfall", harness, {"android_audio.h": globals_ + functions})

    def test_aaudio_partial_writes_and_lifecycle(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        globals_ = source[source.index("static AAudioStream *stream;"):source.index("static void audio_close_stream(")]
        functions = "\n".join(function(source, signature) for signature in (
            "static void audio_close_stream(", "static void audio_close_failed(",
            "static uint32_t audio_write_frames(", "uint32_t void_audio_output("))
        compile_probe("aaudio-streaming", AAUDIO_HARNESS, {"android_audio.h": globals_ + functions})


if __name__ == "__main__":
    unittest.main()
