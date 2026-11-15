/* The deflate engine behind zlib_native.c's deflate hooks: zlib 1.3.1's deflate,
 * trees, adler32, crc32 and zutil from the official 1.3.1 release (reference/zlib),
 * built here with the z_ prefix so nothing clashes with the NDK's libz.
 *
 * The guest's zlib1.dll is zlib 1.2.3 (its longest_match in assembly). For the
 * parameters the game passes, 1.3.1 writes the same bytes (tests/
 * test_deflate_native.py runs both on the real save payloads and on synthetic
 * streams, every call compared). One rule differs and is put back here: 1.2.3
 * classifies data_type only on a non-empty block, from the literals 0..8 and
 * 14..31 (set_data_type); 1.3.1 asks detect_data_type, which tolerates 7, 8,
 * 11, 12, 26 and 27 and also decides on an empty block. The block flush is
 * wrapped so the stream's data_type follows 1.2.3. Two more 1.2.3 habits are
 * kept so every call returns what 1.2.3 returns, not only the same stream:
 * flush_pending hands out whole bytes only (1.3.1 first moves the complete
 * bytes of the bit buffer out, _tr_flush_bits, so a call could end a byte
 * ahead), and a raw stream starts with last_flush Z_NO_FLUSH (1.3.1: -2, so
 * a first empty Z_NO_FLUSH call was no Z_BUF_ERROR). */
#define Z_PREFIX
#include "../../reference/zlib/zutil.h"
#include "../../reference/zlib/deflate.h"
#include "zlib_deflate_native.h"

/* trees.c's block flush keeps its body under another name; deflate.c reaches it
 * through the wrapper below. */
#undef _tr_flush_block
#define _tr_flush_block h5z_tr_flush_block
#undef _tr_flush_bits
#define _tr_flush_bits h5z_tr_flush_bits
#include "../../reference/zlib/trees.c"
#undef _tr_flush_block
#define _tr_flush_block z__tr_flush_block
#undef _tr_flush_bits
#define _tr_flush_bits z__tr_flush_bits

/* flush_pending's bit-buffer flush: zlib 1.2.3 had none (see above). */
void ZLIB_INTERNAL _tr_flush_bits(deflate_state *s) { (void)s; }

void ZLIB_INTERNAL _tr_flush_block(deflate_state *s, charf *buf, ulg stored_len, int last)
{
    if (s->level > 0 && s->strm->data_type == Z_UNKNOWN) {
        if (stored_len > 0) {
            /* zlib 1.2.3 set_data_type: any literal 0..8 or 14..31 means binary. */
            int n;
            for (n = 0; n < 9; n++)
                if (s->dyn_ltree[n].Freq != 0) break;
            if (n == 9)
                for (n = 14; n < 32; n++)
                    if (s->dyn_ltree[n].Freq != 0) break;
            s->strm->data_type = n == 32 ? Z_TEXT : Z_BINARY;
        } else {
            /* 1.2.3 leaves an empty block unclassified. */
            s->strm->data_type = Z_TEXT;
            h5z_tr_flush_block(s, buf, stored_len, last);
            s->strm->data_type = Z_UNKNOWN;
            return;
        }
    }
    h5z_tr_flush_block(s, buf, stored_len, last);
}

#include "../../reference/zlib/deflate.c"
#include "../../reference/zlib/adler32.c"
#include "../../reference/zlib/crc32.c"
#undef GZIP   /* zutil.c's gzguts.h has its own */
#include "../../reference/zlib/zutil.c"

struct h5z_stream { z_stream z; };

int h5z_deflate_init(h5z_stream **out, int level, int method, int window_bits, int mem_level, int strategy)
{
    h5z_stream *s = (h5z_stream *)calloc(1, sizeof *s);
    if (!s) return Z_MEM_ERROR;
    int result = deflateInit2(&s->z, level, method, window_bits, mem_level, strategy);
    if (result != Z_OK) { free(s); return result; }
    if (((deflate_state *)s->z.state)->wrap == 0) ((deflate_state *)s->z.state)->last_flush = Z_NO_FLUSH;
    *out = s;
    return Z_OK;
}

int h5z_deflate(h5z_stream *s, h5z_io *io, int flush)
{
    z_stream *z = &s->z;
    z->next_in = (z_const Bytef *)io->next_in;
    z->avail_in = io->avail_in;
    z->total_in = io->total_in;
    z->next_out = io->next_out;
    z->avail_out = io->avail_out;
    z->total_out = io->total_out;
    z->adler = io->adler;
    z->data_type = io->data_type;
    z->msg = Z_NULL;
    int result = deflate(z, flush);
    io->next_in = z->next_in;
    io->avail_in = z->avail_in;
    io->total_in = (uint32_t)z->total_in;
    io->next_out = z->next_out;
    io->avail_out = z->avail_out;
    io->total_out = (uint32_t)z->total_out;
    io->adler = (uint32_t)z->adler;
    io->data_type = z->data_type;
    io->message = -1;
    for (int i = 0; i < 10; i++)
        if (z->msg && z->msg == (char *)z_errmsg[i]) io->message = i;
    return result;
}

int h5z_deflate_end(h5z_stream *s)
{
    /* zlib 1.2.3 starts a raw stream busy (deflateReset), 1.3.1 waits for the first
     * deflate call: ended before that, 1.2.3 reports Z_DATA_ERROR. */
    const int unstarted_raw = s->z.state && ((deflate_state *)s->z.state)->wrap == 0 &&
                              ((deflate_state *)s->z.state)->status == INIT_STATE;
    int result = deflateEnd(&s->z);
    free(s);
    return unstarted_raw && result == Z_OK ? Z_DATA_ERROR : result;
}
