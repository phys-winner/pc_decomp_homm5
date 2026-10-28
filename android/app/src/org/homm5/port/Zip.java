package org.homm5.port;

import java.io.Closeable;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.zip.CRC32;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

/** A ZIP archive read through its central directory, for the launcher's
 *  unpacking of the game (Unpacker): ZIP64 (the game is over 2 GB), names with
 *  either slash in UTF-8 or the DOS code page, and the methods archivers
 *  use for the game's files: stored, Deflate and Deflate64 (Windows
 *  Explorer's compressed folders write it for a file as large as
 *  Textures.vfs, and Android has no decoder of it). Plain Java over a
 *  FileChannel: tests/test_launcher_unpack.py runs it on the PC too. */
final class Zip implements Closeable {
    static final int STORED = 0, DEFLATE = 8, DEFLATE64 = 9;

    static final class Entry {
        final String name;   /* '/' between folders, a folder's ends with one */
        final int method, flags;
        final long crc, packedSize, size, header;
        final long time;     /* last modification, ms since 1970; 0 unknown */

        Entry(String name, int method, int flags, long crc, long packedSize, long size, long header, long time) {
            this.name = name;
            this.method = method;
            this.flags = flags;
            this.crc = crc;
            this.packedSize = packedSize;
            this.size = size;
            this.header = header;
            this.time = time;
        }

        boolean directory() { return name.endsWith("/"); }
        boolean encrypted() { return (flags & 1) != 0; }
    }

    private final FileChannel channel;
    private final long length;
    final List<Entry> entries;

    Zip(FileChannel channel) throws IOException {
        this.channel = channel;
        length = channel.size();
        entries = directory();
    }

    @Override public void close() throws IOException { channel.close(); }

    private ByteBuffer read(long at, int n) throws IOException {
        if (at < 0 || n < 0 || at + n > length) throw notZip();
        ByteBuffer b = ByteBuffer.allocate(n).order(ByteOrder.LITTLE_ENDIAN);
        while (b.hasRemaining())
            if (channel.read(b, at + b.position()) < 0) throw new EOFException();
        b.flip();
        return b;
    }

    private static Unpacker.Failure notZip() { return new Unpacker.Failure(Unpacker.NOT_ZIP, null); }

    private List<Entry> directory() throws IOException {
        if (length < 22) throw notZip();
        /* The end record with the longest comment, and the ZIP64 locator before it. */
        int tail = (int) Math.min(length, 22 + 0xFFFF + 20);
        long tailAt = length - tail;
        ByteBuffer t = read(tailAt, tail);
        int end = -1;
        for (int i = tail - 22; i >= 0 && end < 0; --i)
            if (t.getInt(i) == 0x06054b50 && i + 22 + (t.getShort(i + 20) & 0xFFFF) <= tail) end = i;
        if (end < 0) throw notZip();
        long count = t.getShort(end + 10) & 0xFFFF;
        long size = t.getInt(end + 12) & 0xFFFFFFFFL, offset = t.getInt(end + 16) & 0xFFFFFFFFL;
        int disk = t.getShort(end + 4) & 0xFFFF, directoryDisk = t.getShort(end + 6) & 0xFFFF;
        long directoryEnd = tailAt + end;   /* where the directory ends: the end record or ZIP64's */
        if (end >= 20 && t.getInt(end - 20) == 0x07064b50) {
            if (t.getInt(end - 20 + 16) > 1) throw new Unpacker.Failure(Unpacker.SPLIT, null);
            /* The ZIP64 record is right before its locator unless it carries
             * extensible data; data before the archive moves it (below). */
            long at = tailAt + end - 20 - 56;
            if (at < 0 || read(at, 4).getInt(0) != 0x06064b50) at = t.getLong(end - 20 + 8);
            ByteBuffer z = read(at, 56);
            if (z.getInt(0) != 0x06064b50) throw notZip();
            disk = z.getInt(16);
            directoryDisk = z.getInt(20);
            count = z.getLong(32);
            size = z.getLong(40);
            offset = z.getLong(48);
            directoryEnd = at;
        }
        if (disk != 0 || directoryDisk != 0) throw new Unpacker.Failure(Unpacker.SPLIT, null);
        /* A self-extractor's program before the archive shifts every offset. */
        long shift = directoryEnd - (offset + size);
        if (shift < 0 || size > 64 << 20 || count > size / 46) throw notZip();
        ByteBuffer d = read(offset + shift, (int) size);
        List<Entry> list = new ArrayList<>((int) count);
        int p = 0;
        for (long i = 0; i < count; ++i) {
            if (p + 46 > d.limit() || d.getInt(p) != 0x02014b50) throw notZip();
            int flags = d.getShort(p + 8) & 0xFFFF, method = d.getShort(p + 10) & 0xFFFF;
            long time = dosTime(d.getShort(p + 14) & 0xFFFF, d.getShort(p + 12) & 0xFFFF);
            long crc = d.getInt(p + 16) & 0xFFFFFFFFL;
            long packed = d.getInt(p + 20) & 0xFFFFFFFFL, full = d.getInt(p + 24) & 0xFFFFFFFFL;
            int nameLength = d.getShort(p + 28) & 0xFFFF, extraLength = d.getShort(p + 30) & 0xFFFF;
            int commentLength = d.getShort(p + 32) & 0xFFFF;
            long startDisk = d.getShort(p + 34) & 0xFFFF, header = d.getInt(p + 42) & 0xFFFFFFFFL;
            int nameAt = p + 46, extraAt = nameAt + nameLength, extraEnd = extraAt + extraLength;
            int next = extraEnd + commentLength;
            if (next > d.limit()) throw notZip();
            byte[] raw = new byte[nameLength];
            d.position(nameAt);
            d.get(raw);
            String unicode = null;
            for (int e = extraAt; e + 4 <= extraEnd;) {
                int id = d.getShort(e) & 0xFFFF, n = d.getShort(e + 2) & 0xFFFF, v = e + 4;
                if (v + n > extraEnd) break;
                if (id == 0x0001) {
                    /* ZIP64: the values whose 32 bits are all ones, in this order. */
                    int q = v, qEnd = v + n;
                    if (full == 0xFFFFFFFFL && q + 8 <= qEnd) { full = d.getLong(q); q += 8; }
                    if (packed == 0xFFFFFFFFL && q + 8 <= qEnd) { packed = d.getLong(q); q += 8; }
                    if (header == 0xFFFFFFFFL && q + 8 <= qEnd) { header = d.getLong(q); q += 8; }
                    if (startDisk == 0xFFFF && q + 4 <= qEnd) startDisk = d.getInt(q) & 0xFFFFFFFFL;
                } else if (id == 0x5455 && n >= 5 && (d.get(v) & 1) != 0) {
                    /* Extended timestamp: modification time in UTC seconds. */
                    time = (d.getInt(v + 1) & 0xFFFFFFFFL) * 1000;
                } else if (id == 0x000A && n >= 32 && (d.getShort(v + 4) & 0xFFFF) == 1 && (d.getShort(v + 6) & 0xFFFF) >= 24) {
                    /* NTFS times (7-Zip, WinRAR): 100 ns since 1601. */
                    long ntfs = d.getLong(v + 8);
                    if (ntfs > 116444736000000000L) time = (ntfs - 116444736000000000L) / 10000;
                } else if (id == 0x7075 && n > 5 && d.get(v) == 1) {
                    /* Info-ZIP's UTF-8 name, valid while it matches the name's CRC. */
                    CRC32 c = new CRC32();
                    c.update(raw);
                    if ((d.getInt(v + 1) & 0xFFFFFFFFL) == c.getValue()) {
                        byte[] u = new byte[n - 5];
                        d.position(v + 5);
                        d.get(u);
                        unicode = new String(u, StandardCharsets.UTF_8);
                    }
                }
                e = v + n;
            }
            if (startDisk != 0) throw new Unpacker.Failure(Unpacker.SPLIT, null);
            if (packed < 0 || full < 0 || header < 0) throw notZip();
            String name = unicode != null ? unicode : decode(raw, (flags & 0x800) != 0, d.get(p + 5) & 0xFF);
            list.add(new Entry(name.replace('\\', '/'), method, flags, crc, packed, full, header + shift, time));
            p = next;
        }
        return Collections.unmodifiableList(list);
    }

    /* Names without the UTF-8 flag: Info-ZIP on Linux and macOS's Archive
     * Utility write UTF-8 all the same, Windows its OEM code page: 866 on the
     * Russian systems the supported game comes from, 437 on most others. */
    private static final Charset DOS = dosCharset();

    private static Charset dosCharset() {
        try {
            return Charset.forName("IBM437");
        } catch (RuntimeException e) {
            return StandardCharsets.ISO_8859_1;
        }
    }

    /** host: the "made by" system; Windows archivers (MS-DOS/FAT 0, NTFS 11, VFAT 14) write the OEM
     *  code page, where Cyrillic CP866 bytes can also happen to form valid UTF-8. */
    static String decode(byte[] raw, boolean utf8, int host) {
        if (utf8) return new String(raw, StandardCharsets.UTF_8);
        String cyrillic = cp866(raw);
        if (cyrillic != null && (host == 0 || host == 11 || host == 14)) return cyrillic;
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(raw)).toString();
        } catch (CharacterCodingException e) {
            return cyrillic != null ? cyrillic : new String(raw, DOS);
        }
    }

    /** A name whose every byte above ASCII is a CP866 letter (А–я, Ё/ё, Є/є, Ї/ї, Ў/ў), else null. */
    static String cp866(byte[] raw) {
        StringBuilder out = new StringBuilder(raw.length);
        for (byte b : raw) {
            int c = b & 0xFF;
            if (c < 0x80) out.append((char) c);
            else if (c <= 0xAF) out.append((char) (0x0410 + c - 0x80));
            else if (c >= 0xE0 && c <= 0xEF) out.append((char) (0x0440 + c - 0xE0));
            else if (c >= 0xF0 && c <= 0xF7) out.append("ЁёЄєЇїЎў".charAt(c - 0xF0));
            else return null;
        }
        return out.toString();
    }

    /** An MS-DOS date and time (local time, two-second steps) in ms since 1970; 0 if invalid. */
    static long dosTime(int date, int time) {
        int year = 1980 + (date >> 9), month = (date >> 5) & 15, day = date & 31;
        int hour = time >> 11, minute = (time >> 5) & 63, second = (time & 31) * 2;
        if (month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return 0;
        java.util.Calendar calendar = new java.util.GregorianCalendar(year, month - 1, day, hour, minute, second);
        return calendar.getTimeInMillis();
    }

    static String methodName(int method) {
        switch (method) {
        case STORED: return "Stored";
        case DEFLATE: return "Deflate";
        case DEFLATE64: return "Deflate64";
        case 12: return "BZip2";
        case 14: return "LZMA";
        case 93: return "Zstandard";
        case 95: return "XZ";
        case 98: return "PPMd";
        case 99: return "AES";
        default: return "#" + method;
        }
    }

    static boolean supported(int method) { return method == STORED || method == DEFLATE || method == DEFLATE64; }

    /** The entry's bytes as they were before packing (the caller checks the CRC). */
    InputStream open(Entry e) throws IOException {
        if (e.encrypted()) throw new Unpacker.Failure(Unpacker.ENCRYPTED, e.name);
        if (!supported(e.method)) throw new Unpacker.Failure(Unpacker.METHOD, methodName(e.method));
        ByteBuffer h = read(e.header, 30);
        if (h.getInt(0) != 0x04034b50) throw new Unpacker.Failure(Unpacker.CORRUPT, e.name);
        long data = e.header + 30 + (h.getShort(26) & 0xFFFF) + (h.getShort(28) & 0xFFFF);
        if (data + e.packedSize > length) throw new Unpacker.Failure(Unpacker.CORRUPT, e.name);
        InputStream packed = new Range(data, e.packedSize);
        if (e.method == STORED) {
            if (e.packedSize != e.size) throw new Unpacker.Failure(Unpacker.CORRUPT, e.name);
            return packed;
        }
        return e.method == DEFLATE ? new Inflating(packed) : new Deflate64(packed, true);
    }

    /** Bytes [at, at + n) of the archive, read where they are (no shared position). */
    private final class Range extends InputStream {
        private long at;
        private final long end;

        Range(long at, long n) {
            this.at = at;
            end = at + n;
        }

        @Override public int read() throws IOException {
            byte[] one = new byte[1];
            return read(one, 0, 1) < 0 ? -1 : one[0] & 0xFF;
        }

        @Override public int read(byte[] b, int off, int len) throws IOException {
            if (len == 0) return 0;
            if (at >= end) return -1;
            int n = channel.read(ByteBuffer.wrap(b, off, (int) Math.min(len, end - at)), at);
            if (n < 0) throw new EOFException();
            at += n;
            return n;
        }
    }

    /** Deflate through the platform's zlib. */
    private static final class Inflating extends InputStream {
        private final InputStream in;
        private final Inflater inflater = new Inflater(true);
        private final byte[] buffer = new byte[1 << 16];
        private boolean padded;

        Inflating(InputStream in) { this.in = in; }

        @Override public int read() throws IOException {
            byte[] one = new byte[1];
            return read(one, 0, 1) < 0 ? -1 : one[0] & 0xFF;
        }

        @Override public int read(byte[] b, int off, int len) throws IOException {
            if (len == 0) return 0;
            try {
                for (;;) {
                    int n = inflater.inflate(b, off, len);
                    if (n > 0) return n;
                    if (inflater.finished()) return -1;
                    if (inflater.needsDictionary()) throw new IOException("a preset dictionary");
                    if (!inflater.needsInput()) continue;
                    int r = in.read(buffer, 0, buffer.length);
                    if (r > 0) {
                        inflater.setInput(buffer, 0, r);
                    } else if (!padded) {
                        /* zlib wants a byte past raw deflate data to see its end. */
                        padded = true;
                        inflater.setInput(new byte[1], 0, 1);
                    } else {
                        throw new EOFException("the packed data ends early");
                    }
                }
            } catch (DataFormatException x) {
                throw new IOException(x.getMessage());
            }
        }

        @Override public void close() { inflater.end(); }
    }
}
