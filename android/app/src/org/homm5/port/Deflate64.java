package org.homm5.port;

import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;

/** A Deflate64 decoder (ZIP method 9, "enhanced deflate"): Deflate with a
 *  64 KiB window, length code 285 meaning 3 plus 16 extra bits, and the
 *  distance codes 30 and 31. Windows Explorer packs a file this large as
 *  Textures.vfs so, and Android's zlib knows only Deflate. With deflate64
 *  false it decodes Deflate (the tests hold it against zlib). */
final class Deflate64 extends InputStream {
    private static final int WINDOW = 1 << 16, CHUNK = 1 << 20, MAX_MATCH = 3 + 0xFFFF;
    private static final int[] LENGTH_BASE = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
        67, 83, 99, 115, 131, 163, 195, 227, 258};
    private static final int[] LENGTH_EXTRA = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4,
        5, 5, 5, 5, 0};
    private static final int[] DISTANCE_BASE = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385,
        513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577, 32769, 49153};
    private static final int[] DISTANCE_EXTRA = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10,
        10, 11, 11, 12, 12, 13, 13, 14, 14};
    /* The order the code length code's lengths come in. */
    private static final int[] ORDER = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    private static final Huffman FIXED_LITERALS, FIXED_DISTANCES;

    static {
        int[] l = new int[288];
        Arrays.fill(l, 0, 144, 8);
        Arrays.fill(l, 144, 256, 9);
        Arrays.fill(l, 256, 280, 7);
        Arrays.fill(l, 280, 288, 8);
        int[] d = new int[32];
        Arrays.fill(d, 5);
        try {
            FIXED_LITERALS = new Huffman(l, l.length);
            FIXED_DISTANCES = new Huffman(d, d.length);
        } catch (IOException e) {
            throw new AssertionError(e);
        }
    }

    private final InputStream in;
    private final boolean deflate64;
    private final int window;
    private final byte[] input = new byte[1 << 16];
    private int inPos, inEnd;
    private boolean inEnded;
    private long bits;   /* read ahead, the next bit lowest */
    private int count;

    /* The window, then what is decoded: the reader takes [readPos, outPos);
     * a match always fits behind the chunk. */
    private final byte[] out = new byte[WINDOW + CHUNK + MAX_MATCH];
    private int outPos = WINDOW, readPos = WINDOW;
    private long produced;
    private boolean last, done;
    private int stored = -1;              /* bytes left of a stored block; -1: none */
    private Huffman literals, distances;  /* the codes of the block being decoded; null between blocks */

    Deflate64(InputStream in, boolean deflate64) {
        this.in = in;
        this.deflate64 = deflate64;
        window = deflate64 ? WINDOW : 1 << 15;
    }

    @Override public int read() throws IOException {
        byte[] one = new byte[1];
        return read(one, 0, 1) < 0 ? -1 : one[0] & 0xFF;
    }

    @Override public int read(byte[] b, int off, int len) throws IOException {
        if (len == 0) return 0;
        if (readPos == outPos) {
            if (done) return -1;
            fill();
            if (readPos == outPos) return -1;
        }
        int n = Math.min(len, outPos - readPos);
        System.arraycopy(out, readPos, b, off, n);
        readPos += n;
        return n;
    }

    @Override public void close() throws IOException { in.close(); }

    private static IOException bad(String what) { return new IOException("Deflate64: " + what); }

    /* ---------------------------------------------------------------- bits */

    private boolean more() throws IOException {
        if (inPos < inEnd) return true;
        if (inEnded) return false;
        int n = in.read(input, 0, input.length);
        if (n <= 0) {
            inEnded = true;
            return false;
        }
        inPos = 0;
        inEnd = n;
        return true;
    }

    /** Up to 64 bits ahead; fewer only at the end of the data. */
    private void refill() throws IOException {
        while (count <= 56 && more()) {
            bits |= (long) (input[inPos++] & 0xFF) << count;
            count += 8;
        }
    }

    private int take(int n) throws IOException {
        if (count < n) {
            refill();
            if (count < n) throw new EOFException("Deflate64: the data ends early");
        }
        int v = (int) bits & ((1 << n) - 1);
        bits >>>= n;
        count -= n;
        return v;
    }

    private int decode(Huffman h) throws IOException {
        if (count < 15) refill();
        int e = h.table[(int) bits & Huffman.MASK];
        if (e < 0) {
            e = -e;
            e = h.sub[(e >>> 4) + ((int) (bits >>> Huffman.PRIMARY) & ((1 << (e & 15)) - 1))];
        }
        int length = e & 15;
        if (length == 0) throw bad("a code that is not in the table");
        if (length > count) throw new EOFException("Deflate64: the data ends early");
        bits >>>= length;
        count -= length;
        return e >>> 4;
    }

    /* -------------------------------------------------------------- blocks */

    private void fill() throws IOException {
        if (outPos >= WINDOW + CHUNK) {   /* all of it was read: keep the window */
            System.arraycopy(out, outPos - WINDOW, out, 0, WINDOW);
            outPos = readPos = WINDOW;
        }
        int limit = WINDOW + CHUNK;
        while (outPos < limit && !done) {
            if (stored >= 0) {
                copyStored(limit);
            } else if (literals == null) {
                if (last) done = true;
                else header();
            } else {
                int symbol = decode(literals);
                if (symbol < 256) {
                    out[outPos++] = (byte) symbol;
                    ++produced;
                } else if (symbol == 256) {
                    literals = distances = null;
                } else {
                    match(symbol - 257);
                }
            }
        }
    }

    private void match(int code) throws IOException {
        if (code >= 29) throw bad("length code " + (code + 257));
        int length = deflate64 && code == 28 ? 3 + take(16)
            : LENGTH_BASE[code] + (LENGTH_EXTRA[code] > 0 ? take(LENGTH_EXTRA[code]) : 0);
        int d = decode(distances);
        if (d >= (deflate64 ? 32 : 30)) throw bad("distance code " + d);
        int distance = DISTANCE_BASE[d] + (DISTANCE_EXTRA[d] > 0 ? take(DISTANCE_EXTRA[d]) : 0);
        if (distance > produced || distance > window) throw bad("a distance before the data");
        int from = outPos - distance;
        if (distance >= length) {
            System.arraycopy(out, from, out, outPos, length);
        } else {
            for (int i = 0; i < length; ++i) out[outPos + i] = out[from + i];
        }
        outPos += length;
        produced += length;
    }

    private void header() throws IOException {
        last = take(1) == 1;
        int type = take(2);
        if (type == 0) {
            int skip = count & 7;   /* to the byte boundary */
            bits >>>= skip;
            count -= skip;
            int length = take(16), check = take(16);
            if ((length ^ 0xFFFF) != check) throw bad("a stored block's length");
            stored = length;
        } else if (type == 1) {
            literals = FIXED_LITERALS;
            distances = FIXED_DISTANCES;
        } else if (type == 2) {
            dynamic();
        } else {
            throw bad("block type 3");
        }
    }

    private void copyStored(int limit) throws IOException {
        if (stored == 0) {
            stored = -1;
            return;
        }
        int n = Math.min(stored, limit - outPos), k = 0;
        while (k < n && count >= 8) {   /* bytes read ahead come first */
            out[outPos + k++] = (byte) bits;
            bits >>>= 8;
            count -= 8;
        }
        while (k < n) {
            if (!more()) throw new EOFException("Deflate64: the data ends early");
            int c = Math.min(n - k, inEnd - inPos);
            System.arraycopy(input, inPos, out, outPos + k, c);
            inPos += c;
            k += c;
        }
        outPos += n;
        produced += n;
        stored -= n;
    }

    private void dynamic() throws IOException {
        int literalCount = take(5) + 257, distanceCount = take(5) + 1, lengthCount = take(4) + 4;
        if (literalCount > 286 || distanceCount > (deflate64 ? 32 : 30)) throw bad("too many codes");
        int[] lengthLengths = new int[19];
        for (int i = 0; i < lengthCount; ++i) lengthLengths[ORDER[i]] = take(3);
        Huffman lengthCode = new Huffman(lengthLengths, 19);
        int[] lengths = new int[literalCount + distanceCount];
        for (int i = 0; i < lengths.length;) {
            int symbol = decode(lengthCode);
            if (symbol < 16) {
                lengths[i++] = symbol;
                continue;
            }
            int value = 0, repeat;
            if (symbol == 16) {
                if (i == 0) throw bad("a repeat before any length");
                value = lengths[i - 1];
                repeat = 3 + take(2);
            } else {
                repeat = symbol == 17 ? 3 + take(3) : 11 + take(7);
            }
            if (i + repeat > lengths.length) throw bad("too many lengths");
            while (repeat-- > 0) lengths[i++] = value;
        }
        if (lengths[256] == 0) throw bad("no end of block");
        literals = new Huffman(Arrays.copyOfRange(lengths, 0, literalCount), literalCount);
        distances = new Huffman(Arrays.copyOfRange(lengths, literalCount, lengths.length), distanceCount);
    }

    /** Canonical codes looked up by their first PRIMARY bits; a longer code
     *  goes on in a table of its prefix. An entry is symbol << 4 | length
     *  (0: no code); a prefix's is -(start << 4 | its table's bits). */
    private static final class Huffman {
        static final int PRIMARY = 10, MASK = (1 << PRIMARY) - 1;
        final int[] table = new int[1 << PRIMARY];
        final int[] sub;

        Huffman(int[] lengths, int n) throws IOException {
            int[] counts = new int[16];
            for (int i = 0; i < n; ++i) ++counts[lengths[i]];
            counts[0] = 0;
            int left = 1;
            for (int len = 1; len <= 15; ++len) {
                left = (left << 1) - counts[len];
                if (left < 0) throw bad("an over-subscribed code");
            }
            int[] first = new int[16];
            for (int len = 1, code = 0; len <= 15; ++len) {
                code = (code + counts[len - 1]) << 1;
                first[len] = code;
            }
            /* The longest code through each prefix sizes its table. */
            int[] longest = new int[1 << PRIMARY];
            int[] next = first.clone();
            for (int s = 0; s < n; ++s) {
                int len = lengths[s];
                if (len > PRIMARY) {
                    int prefix = reverse(next[len]++, len) & MASK;
                    longest[prefix] = Math.max(longest[prefix], len);
                }
            }
            int total = 0;
            for (int prefix = 0; prefix <= MASK; ++prefix) {
                if (longest[prefix] == 0) continue;
                table[prefix] = -(total << 4 | (longest[prefix] - PRIMARY));
                total += 1 << (longest[prefix] - PRIMARY);
            }
            sub = new int[total];
            next = first.clone();
            for (int s = 0; s < n; ++s) {
                int len = lengths[s];
                if (len == 0) continue;
                int code = reverse(next[len]++, len);
                if (len <= PRIMARY) {
                    for (int k = code; k <= MASK; k += 1 << len) table[k] = s << 4 | len;
                } else {
                    int link = -table[code & MASK], start = link >>> 4, size = 1 << (link & 15);
                    for (int k = code >>> PRIMARY; k < size; k += 1 << (len - PRIMARY)) sub[start + k] = s << 4 | len;
                }
            }
        }

        private static int reverse(int code, int length) { return Integer.reverse(code) >>> (32 - length); }
    }
}
