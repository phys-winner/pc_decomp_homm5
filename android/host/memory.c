/* The guest address space: one 4 GiB reservation, a Win32-style page map
 * (64 KiB allocation granularity, reserve/commit, protection) and Win32 heaps
 * built on dlmalloc mspaces whose system memory comes from the same map.
 *
 * The guest's page stays 4 KiB on every kernel. With 16 KiB host pages
 * (Android 15+ devices) a host page holds four guest pages and gets the union
 * of their protections: guest accesses are checked against the guest map
 * (range_access) and a guest fault is fatal either way, so all that is lost
 * is the trap of a stray access next to a committed page. */
#define _GNU_SOURCE
#include "host.h"
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <sys/mman.h>

#define PAGES (1u << 20)               /* 4 GiB / 4 KiB */
#define GRANULES (1u << 16)            /* 4 GiB / 64 KiB */

enum { ST_FREE = 0, ST_RESERVE = 1, ST_COMMIT = 2 };
#define MEM_COMMIT_ 0x1000u
#define MEM_RESERVE_ 0x2000u
#define MEM_DECOMMIT_ 0x4000u
#define MEM_RELEASE_ 0x8000u
#define MEM_TOP_DOWN_ 0x100000u
#define MEM_PRIVATE_ 0x20000u
#define MEM_IMAGE_ 0x1000000u

#define PAGE_NOACCESS_ 0x01u
#define PAGE_READONLY_ 0x02u
#define PAGE_READWRITE_ 0x04u
#define PAGE_WRITECOPY_ 0x08u
#define PAGE_EXECUTE_ 0x10u
#define PAGE_EXECUTE_READ_ 0x20u
#define PAGE_EXECUTE_READWRITE_ 0x40u
#define PAGE_EXECUTE_WRITECOPY_ 0x80u
#define PAGE_GUARD_ 0x100u

static uint8_t page_state[PAGES];
static uint16_t page_protect[PAGES];   /* Win32 PAGE_* of committed pages */
static uint32_t page_alloc[PAGES];     /* allocation base (VA >> 12), 0 if free */
static uint16_t alloc_protect[PAGES];  /* initial protection, valid at the base */
static uint8_t granule_used[GRANULES];
static pthread_mutex_t vm_lock = PTHREAD_MUTEX_INITIALIZER;
static uint32_t host_pages = 1;        /* guest pages per host page: 1 (4 KiB) or 4 (16 KiB) */

int void_guest_reserve(void)
{
    long size = sysconf(_SC_PAGESIZE);
    if (size > (long)GUEST_PAGE && size <= (long)GUEST_GRANULARITY && !(size & (size - 1)))
        host_pages = (uint32_t)size / GUEST_PAGE;
    else if (size != (long)GUEST_PAGE) {
        void_log("[void] unsupported host page size %ld", size);
        return 0;
    }
    void *want = (void *)(uintptr_t)VOID_GUEST_BASE;
    void *got = mmap(want, VOID_GUEST_SPAN, PROT_NONE,
        MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (got == MAP_FAILED) {
        void_log("[void] guest window reservation failed: %s", strerror(errno));
        return 0;
    }
    if (got != want) {
        void_log("[void] guest window landed at %p instead of %p", got, want);
        munmap(got, VOID_GUEST_SPAN);
        return 0;
    }
    /* Null guard: the first 64 KiB are never allocatable, as on Windows. */
    granule_used[0] = 1;
    /* Synthetic thunk VAs: reserved, never accessible. */
    for (uint32_t g = GUEST_THUNK_BASE >> 16; g < (GUEST_THUNK_LIMIT >> 16); ++g) granule_used[g] = 1;
    /* Everything above the user top stays unavailable. */
    for (uint32_t g = GUEST_USER_TOP >> 16; g < GRANULES; ++g) granule_used[g] = 1;
    void_log("[void] guest window %p..%p reserved, host page %u KiB", want,
             (void *)((uintptr_t)want + VOID_GUEST_SPAN), host_pages * 4);
    return 1;
}

static int host_prot(uint32_t protect)
{
    if (protect & PAGE_GUARD_) return PROT_NONE;
    switch (protect & 0xFFu) {
    case PAGE_NOACCESS_: return PROT_NONE;
    case PAGE_READONLY_: case PAGE_EXECUTE_: case PAGE_EXECUTE_READ_: return PROT_READ;
    default: return PROT_READ | PROT_WRITE;
    }
}

static int valid_protect(uint32_t protect)
{
    switch (protect & ~PAGE_GUARD_ & 0xFFFu) {
    case PAGE_NOACCESS_: case PAGE_READONLY_: case PAGE_READWRITE_: case PAGE_WRITECOPY_:
    case PAGE_EXECUTE_: case PAGE_EXECUTE_READ_: case PAGE_EXECUTE_READWRITE_: case PAGE_EXECUTE_WRITECOPY_:
        return 1;
    default:
        return 0;
    }
}

static uint32_t find_free(uint32_t size, int top_down)
{
    uint32_t need = (size + GUEST_GRANULARITY - 1) / GUEST_GRANULARITY;
    if (!need) return 0;
    uint32_t limit = GUEST_USER_TOP >> 16;
    if (top_down) {
        uint32_t run = 0;
        for (uint32_t g = limit; g-- > 1;) {
            run = granule_used[g] ? 0 : run + 1;
            if (run == need) return g << 16;
        }
    } else {
        uint32_t run = 0;
        for (uint32_t g = 1; g < limit; ++g) {
            run = granule_used[g] ? 0 : run + 1;
            if (run == need) return (g - need + 1) << 16;
        }
    }
    return 0;
}

static void set_pages(uint32_t first, uint32_t count, uint8_t state, uint16_t protect, uint32_t base_page)
{
    for (uint32_t p = first; p < first + count; ++p) {
        page_state[p] = state;
        page_protect[p] = protect;
        page_alloc[p] = base_page;
    }
}

/* The host protection of the host page holding guest page p: the union of its guest
 * pages', where the pages [first, last] are about to get the host protection prot
 * (0: decommitted). */
static int host_page_prot(uint32_t p, uint32_t first, uint32_t last, int prot)
{
    int out = 0;
    for (uint32_t q = p - p % host_pages, end = q + host_pages; q < end; ++q) {
        if (q >= first && q <= last) out |= prot;
        else if (page_state[q] == ST_COMMIT) out |= host_prot(page_protect[q]);
    }
    return out;
}

/* Gives the host pages over the guest pages [first, last] their protection as if those
 * pages had prot (0: not committed), in runs of equal protection. Caller holds vm_lock
 * and updates the guest map after a success. */
static int host_protect(uint32_t first, uint32_t last, int prot)
{
    uint32_t from = first - first % host_pages, to = last + host_pages - 1 - last % host_pages;
    for (uint32_t run = from; run <= to;) {
        int want = host_page_prot(run, first, last, prot);
        uint32_t end = run + host_pages;
        while (end <= to && host_page_prot(end, first, last, prot) == want) end += host_pages;
        if (mprotect(GPTR(run << 12), (size_t)(end - run) << 12, want)) {
            void_log("[void] mprotect %08X+%08X failed: %s", run << 12, (end - run) << 12, strerror(errno));
            return 0;
        }
        run = end;
    }
    return 1;
}

static int commit_range(uint32_t address, uint32_t size, uint32_t protect)
{
    return host_protect(address >> 12, (uint32_t)(((uint64_t)address + size - 1) >> 12), host_prot(protect));
}

/* Whether the host page holding guest page p has committed guest pages outside [first, last]. */
static int host_page_shared(uint32_t p, uint32_t first, uint32_t last)
{
    for (uint32_t q = p - p % host_pages, end = q + host_pages; q < end; ++q)
        if ((q < first || q > last) && page_state[q] == ST_COMMIT) return 1;
    return 0;
}

/* Decommits the guest pages [first, last]: committed again they read as zero, as on
 * Windows. Whole host pages are dropped; guest pages sharing a host page with
 * committed ones are cleared. Caller holds vm_lock and updates the guest map. */
static void decommit_range(uint32_t first, uint32_t last)
{
    uint32_t from = first - first % host_pages, to = last + host_pages - 1 - last % host_pages;
    for (uint32_t run = from; run <= to;) {
        uint32_t end = run + host_pages;
        if (host_page_shared(run, first, last)) {
            mprotect(GPTR(run << 12), (size_t)host_pages << 12, PROT_READ | PROT_WRITE);
            for (uint32_t q = run; q < end; ++q)
                if (q >= first && q <= last && page_state[q] == ST_COMMIT) memset(GPTR(q << 12), 0, GUEST_PAGE);
        } else {
            while (end <= to && !host_page_shared(end, first, last)) end += host_pages;
            madvise(GPTR(run << 12), (size_t)(end - run) << 12, MADV_DONTNEED);
        }
        run = end;
    }
    host_protect(first, last, PROT_NONE);
}

/* Reserve [address, address+size) as one allocation. Caller holds vm_lock. */
static int reserve_exact(uint32_t address, uint32_t size, uint32_t protect)
{
    uint32_t g0 = address >> 16, g1 = (uint32_t)(((uint64_t)address + size + GUEST_GRANULARITY - 1) >> 16);
    if ((address & (GUEST_GRANULARITY - 1)) || g1 > (GUEST_USER_TOP >> 16) || g1 <= g0) return 0;
    for (uint32_t g = g0; g < g1; ++g) if (granule_used[g]) return 0;
    for (uint32_t g = g0; g < g1; ++g) granule_used[g] = 1;
    uint32_t pages = (size + GUEST_PAGE - 1) / GUEST_PAGE;
    set_pages(address >> 12, pages, ST_RESERVE, 0, address >> 12);
    alloc_protect[address >> 12] = (uint16_t)protect;
    return 1;
}

uint32_t void_vm_alloc(uint32_t address, uint32_t size, uint32_t type, uint32_t protect)
{
    if (!size || !(type & (MEM_COMMIT_ | MEM_RESERVE_)) || !valid_protect(protect)) {
        void_set_last_error(ERROR_INVALID_PARAMETER_);
        return 0;
    }
    pthread_mutex_lock(&vm_lock);
    uint32_t result = 0;
    if (type & MEM_RESERVE_) {
        uint32_t base = address & ~(GUEST_GRANULARITY - 1);
        uint32_t span = (uint32_t)((((uint64_t)address + size + GUEST_PAGE - 1) & ~(uint64_t)(GUEST_PAGE - 1)) - base);
        if (!address) {
            span = (size + GUEST_PAGE - 1) & ~(GUEST_PAGE - 1);
            base = find_free(span, (type & MEM_TOP_DOWN_) != 0);
            if (!base) { pthread_mutex_unlock(&vm_lock); void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_); return 0; }
        }
        if (!reserve_exact(base, span, protect)) {
            pthread_mutex_unlock(&vm_lock);
            void_set_last_error(ERROR_INVALID_ADDRESS_);
            return 0;
        }
        if (type & MEM_COMMIT_) {
            if (!commit_range(base, span, protect)) { pthread_mutex_unlock(&vm_lock); return 0; }
            set_pages(base >> 12, span >> 12, ST_COMMIT, (uint16_t)protect, base >> 12);
        }
        result = address ? address & ~(GUEST_PAGE - 1) : base;
        if (!address) result = base;
        else result = base;
    } else {
        /* Commit inside an existing reservation. */
        uint32_t first = address >> 12;
        uint32_t last = (uint32_t)(((uint64_t)address + size - 1) >> 12);
        for (uint32_t p = first; p <= last; ++p) {
            if (page_state[p] == ST_FREE) {
                pthread_mutex_unlock(&vm_lock);
                void_set_last_error(ERROR_INVALID_ADDRESS_);
                return 0;
            }
        }
        uint32_t start = first << 12, span = (last - first + 1) << 12;
        if (!commit_range(start, span, protect)) { pthread_mutex_unlock(&vm_lock); return 0; }
        for (uint32_t p = first; p <= last; ++p) { page_state[p] = ST_COMMIT; page_protect[p] = (uint16_t)protect; }
        result = start;
    }
    pthread_mutex_unlock(&vm_lock);
    return result;
}

int void_vm_claim(uint32_t address, uint32_t size, uint32_t protect)
{
    pthread_mutex_lock(&vm_lock);
    uint32_t span = (size + GUEST_PAGE - 1) & ~(GUEST_PAGE - 1);
    int ok = reserve_exact(address, span, protect) && commit_range(address, span, protect);
    if (ok) set_pages(address >> 12, span >> 12, ST_COMMIT, (uint16_t)protect, address >> 12);
    pthread_mutex_unlock(&vm_lock);
    return ok;
}

int void_vm_free(uint32_t address, uint32_t size, uint32_t type)
{
    pthread_mutex_lock(&vm_lock);
    uint32_t page = address >> 12;
    if (type & MEM_RELEASE_) {
        if (size || (address & 0xFFFu) || page_state[page] == ST_FREE || page_alloc[page] != page) {
            pthread_mutex_unlock(&vm_lock);
            void_set_last_error(ERROR_INVALID_PARAMETER_);
            return 0;
        }
        uint32_t p = page;
        while (p < PAGES && page_state[p] != ST_FREE && page_alloc[p] == page) ++p;
        uint32_t span = (p - page) << 12;
        void *host = GPTR(address);
        mmap(host, span, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED | MAP_NORESERVE, -1, 0);
        set_pages(page, p - page, ST_FREE, 0, 0);
        uint32_t g1 = (uint32_t)(((uint64_t)address + span + GUEST_GRANULARITY - 1) >> 16);
        for (uint32_t g = address >> 16; g < g1; ++g) granule_used[g] = 0;
    } else if (type & MEM_DECOMMIT_) {
        uint32_t first = page;
        uint32_t last = size ? (uint32_t)(((uint64_t)address + size - 1) >> 12) : first;
        if (!size) {
            uint32_t base = page_alloc[page];
            first = base;
            last = base;
            while (last + 1 < PAGES && page_state[last + 1] != ST_FREE && page_alloc[last + 1] == base) ++last;
        }
        for (uint32_t p = first; p <= last; ++p) {
            if (page_state[p] == ST_FREE) { pthread_mutex_unlock(&vm_lock); void_set_last_error(ERROR_INVALID_ADDRESS_); return 0; }
        }
        decommit_range(first, last);
        for (uint32_t p = first; p <= last; ++p) { page_state[p] = ST_RESERVE; page_protect[p] = 0; }
    } else {
        pthread_mutex_unlock(&vm_lock);
        void_set_last_error(ERROR_INVALID_PARAMETER_);
        return 0;
    }
    pthread_mutex_unlock(&vm_lock);
    return 1;
}

int void_vm_protect(uint32_t address, uint32_t size, uint32_t protect, uint32_t *old)
{
    if (!size || !valid_protect(protect)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    pthread_mutex_lock(&vm_lock);
    uint32_t first = address >> 12, last = (uint32_t)(((uint64_t)address + size - 1) >> 12);
    for (uint32_t p = first; p <= last; ++p) {
        if (page_state[p] != ST_COMMIT) { pthread_mutex_unlock(&vm_lock); void_set_last_error(ERROR_INVALID_ADDRESS_); return 0; }
    }
    if (old) *old = page_protect[first];
    if (!host_protect(first, last, host_prot(protect))) {
        pthread_mutex_unlock(&vm_lock);
        void_set_last_error(ERROR_INVALID_PARAMETER_);
        return 0;
    }
    for (uint32_t p = first; p <= last; ++p) page_protect[p] = (uint16_t)protect;
    pthread_mutex_unlock(&vm_lock);
    return 1;
}

uint32_t void_vm_query(uint32_t address, uint32_t info)
{
    pthread_mutex_lock(&vm_lock);
    uint32_t page = address >> 12;
    uint8_t state = page_state[page];
    uint32_t base_page = page_alloc[page];
    uint16_t protect = page_protect[page];
    uint32_t p = page;
    while (p < PAGES && page_state[p] == state && page_alloc[p] == base_page && page_protect[p] == protect) ++p;
    uint32_t region = (p - page) << 12;
    if (state == ST_FREE) {
        /* A free region extends to the next allocated page. */
        p = page;
        while (p < PAGES && page_state[p] == ST_FREE) ++p;
        region = (p - page) << 12;
    }
    MEM32(info + 0) = page << 12;                                    /* BaseAddress */
    MEM32(info + 4) = state == ST_FREE ? 0 : base_page << 12;        /* AllocationBase */
    MEM32(info + 8) = state == ST_FREE ? 0 : alloc_protect[base_page]; /* AllocationProtect */
    MEM32(info + 12) = region;                                       /* RegionSize */
    MEM32(info + 16) = state == ST_FREE ? 0x10000u : state == ST_RESERVE ? MEM_RESERVE_ : MEM_COMMIT_;
    MEM32(info + 20) = state == ST_COMMIT ? protect : 0;             /* Protect */
    MEM32(info + 24) = state == ST_FREE ? 0 : MEM_PRIVATE_;          /* Type */
    pthread_mutex_unlock(&vm_lock);
    return 28;
}

/* MapViewOfFile: a fresh reservation with the file mapped over it. */
uint32_t void_vm_map_file(int fd, uint64_t offset, uint32_t size, int writable, int shared)
{
    if (!size) return 0;
    /* Win32 views start at a multiple of the 64 KiB granularity, so of any host page too. */
    if (offset % ((uint64_t)host_pages * GUEST_PAGE)) {
        void_log("[void] mmap view at unaligned offset %llX", (unsigned long long)offset);
        void_set_last_error(ERROR_INVALID_PARAMETER_);
        return 0;
    }
    pthread_mutex_lock(&vm_lock);
    uint32_t span = (size + GUEST_PAGE - 1) & ~(GUEST_PAGE - 1);
    uint32_t base = find_free(span, 0);
    if (!base || !reserve_exact(base, span, writable ? PAGE_READWRITE_ : PAGE_READONLY_)) {
        pthread_mutex_unlock(&vm_lock);
        void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_);
        return 0;
    }
    int prot = PROT_READ | (writable ? PROT_WRITE : 0);
    void *host = mmap(GPTR(base), span, prot, (shared ? MAP_SHARED : MAP_PRIVATE) | MAP_FIXED, fd, (off_t)offset);
    if (host == MAP_FAILED) {
        int e = errno;
        set_pages(base >> 12, span >> 12, ST_FREE, 0, 0);
        uint32_t g1 = (uint32_t)(((uint64_t)base + span + GUEST_GRANULARITY - 1) >> 16);
        for (uint32_t g = base >> 16; g < g1; ++g) granule_used[g] = 0;
        pthread_mutex_unlock(&vm_lock);
        void_log("[void] mmap view failed: %s", strerror(e));
        void_set_last_error(ERROR_ACCESS_DENIED_);
        return 0;
    }
    set_pages(base >> 12, span >> 12, ST_COMMIT, (uint16_t)(writable ? PAGE_READWRITE_ : PAGE_READONLY_), base >> 12);
    pthread_mutex_unlock(&vm_lock);
    return base;
}

int void_vm_unmap_file(uint32_t address)
{
    return void_vm_free(address & ~(GUEST_PAGE - 1), 0, MEM_RELEASE_);
}

static int range_access(uint32_t address, uint32_t size, int write)
{
    if (!size) return 1;
    uint64_t end = (uint64_t)address + size;
    if (end > 0x100000000ull) return 0;
    for (uint32_t p = address >> 12; p <= (uint32_t)((end - 1) >> 12); ++p) {
        if (page_state[p] != ST_COMMIT) return 0;
        int prot = host_prot(page_protect[p]);
        if (!(prot & PROT_READ) || (write && !(prot & PROT_WRITE))) return 0;
    }
    return 1;
}

int void_vm_readable(uint32_t address, uint32_t size) { return range_access(address, size, 0); }
int void_vm_writable(uint32_t address, uint32_t size) { return range_access(address, size, 1); }

/* Debugging (script "memfind"): every committed, readable guest address
 * holding the pattern, up to max hits. Patterns crossing a page into an
 * unreadable one are missed. */
int void_vm_find(const uint8_t *pattern, uint32_t length, uint32_t *hits, int max)
{
    int found = 0;
    if (!length) return 0;
    for (uint32_t page = 0; page < PAGES && found < max; ++page) {
        if (page_state[page] != ST_COMMIT || !(host_prot(page_protect[page]) & PROT_READ)) continue;
        uint32_t base = page << 12;
        const uint8_t *bytes = (const uint8_t *)GPTR(base);
        uint32_t span = 4096;
        if (page + 1 < PAGES && page_state[page + 1] == ST_COMMIT && (host_prot(page_protect[page + 1]) & PROT_READ))
            span += length - 1;
        for (uint32_t i = 0; i + length <= span && found < max; ++i)
            if (bytes[i] == pattern[0] && !memcmp(bytes + i, pattern, length)) hits[found++] = base + i;
    }
    return found;
}

/* Debugging: every committed writable guest page (the heaps, the images'
 * data) to a file, as records of {base, size, bytes}; the size in MiB. */
int void_vm_dump(const char *path)
{
    FILE *out = fopen(path, "wb");
    if (!out) return -1;
    uint64_t total = 0;
    pthread_mutex_lock(&vm_lock);
    for (uint32_t page = 0; page < PAGES;) {
        if (page_state[page] != ST_COMMIT || !(host_prot(page_protect[page]) & PROT_WRITE)) { ++page; continue; }
        uint32_t first = page;
        while (page < PAGES && page_state[page] == ST_COMMIT && (host_prot(page_protect[page]) & PROT_WRITE)) ++page;
        uint32_t record[2] = {first << 12, (page - first) << 12};
        fwrite(record, sizeof record, 1, out);
        fwrite(GPTR(record[0]), 1, record[1], out);
        total += record[1];
    }
    pthread_mutex_unlock(&vm_lock);
    fclose(out);
    return (int)(total >> 20);
}

/* ---------------------------------------------------------------- heaps */
#define ONLY_MSPACES 1
#define MSPACES 1
#define HAVE_MORECORE 0
#define HAVE_MMAP 1
#define HAVE_MREMAP 0
#define USE_LOCKS 1
#define DEFAULT_GRANULARITY (256u * 1024u)
#define DEFAULT_MMAP_THRESHOLD (4u * 1024u * 1024u)
#define MALLOC_INSPECT_ALL 0
#define NO_MALLINFO 1
#define NO_MALLOC_STATS 1
#define LACKS_SCHED_H 0
static void *guest_sys_alloc(size_t size);
static int guest_sys_free(void *p, size_t size);
#define MMAP(s) guest_sys_alloc(s)
#define DIRECT_MMAP(s) guest_sys_alloc(s)
#define MUNMAP(a, s) guest_sys_free((a), (s))
#define PROCEED_ON_ERROR 0
#define ABORT void_fatal("dlmalloc detected heap corruption")
#include "../../reference/dlmalloc/malloc.c"

static void *guest_sys_alloc(size_t size)
{
    if (size > 0x7FFF0000u) return (void *)MFAIL;
    uint32_t va = void_vm_alloc(0, (uint32_t)size, MEM_RESERVE_ | MEM_COMMIT_, PAGE_READWRITE_);
    return va ? GPTR(va) : (void *)MFAIL;
}

static int guest_sys_free(void *p, size_t size)
{
    (void)size;
    return void_vm_free(GVA(p), 0, MEM_RELEASE_) ? 0 : -1;
}

/* A heap handle is the guest VA of a small descriptor, so it looks like the
 * pointer-valued HANDLE Windows returns. */
#define MAX_HEAPS 256
#define BLOCK_MAGIC 0x48454150u      /* 'HEAP' */
typedef struct { uint32_t handle; mspace space; } heap_t;
static heap_t heaps[MAX_HEAPS];
static int heap_count;
static uint32_t process_heap;
static pthread_mutex_t heap_lock = PTHREAD_MUTEX_INITIALIZER;

static heap_t *heap_find(uint32_t handle)
{
    for (int i = 0; i < heap_count; ++i) if (heaps[i].handle == handle && heaps[i].space) return &heaps[i];
    return NULL;
}

uint32_t void_heap_create(uint32_t initial, uint32_t maximum)
{
    (void)initial; (void)maximum;
    pthread_mutex_lock(&heap_lock);
    if (heap_count >= MAX_HEAPS) { pthread_mutex_unlock(&heap_lock); return 0; }
    mspace space = create_mspace(0, 1);
    if (!space) { pthread_mutex_unlock(&heap_lock); return 0; }
    /* The descriptor lives in the new heap itself: a real, readable address. */
    void *descriptor = mspace_calloc(space, 1, 64);
    heap_t *h = &heaps[heap_count++];
    h->space = space;
    h->handle = GVA(descriptor);
    MEM32(h->handle) = 0xEEFFEEFFu;   /* the Windows heap signature field */
    pthread_mutex_unlock(&heap_lock);
    return h->handle;
}

int void_heap_destroy(uint32_t handle)
{
    pthread_mutex_lock(&heap_lock);
    heap_t *h = heap_find(handle);
    if (!h || handle == process_heap) { pthread_mutex_unlock(&heap_lock); return 0; }
    destroy_mspace(h->space);
    h->space = NULL;
    pthread_mutex_unlock(&heap_lock);
    return 1;
}

uint32_t void_process_heap(void)
{
    if (!process_heap) process_heap = void_heap_create(0, 0);
    return process_heap;
}

uint32_t void_heap_alloc(uint32_t handle, uint32_t size, int zero)
{
    heap_t *h = heap_find(handle);
    if (!h || size > 0x7FF00000u) return 0;
    uint8_t *p = (uint8_t *)(zero ? mspace_calloc(h->space, 1, (size_t)size + 8) : mspace_malloc(h->space, (size_t)size + 8));
    if (!p) return 0;
    uint32_t block = GVA(p) + 8;
    MEM32(block - 8) = size;
    MEM32(block - 4) = BLOCK_MAGIC ^ handle;
    return block;
}

static int block_valid(uint32_t handle, uint32_t block)
{
    return block >= 0x10008u && (block & 7u) == 0 && void_vm_readable(block - 8, 8) &&
        MEM32(block - 4) == (BLOCK_MAGIC ^ handle);
}

int void_heap_free(uint32_t handle, uint32_t block)
{
    if (!block) return 1;
    heap_t *h = heap_find(handle);
    if (!h || !block_valid(handle, block)) {
        void_log("[void] HeapFree(%08X, %08X): not a block of this heap (caller %08X)", handle, block, g_cur_func);
        return 0;
    }
    MEM32(block - 4) = 0;
    mspace_free(h->space, GPTR(block - 8));
    return 1;
}

uint32_t void_heap_size(uint32_t handle, uint32_t block)
{
    if (!heap_find(handle) || !block_valid(handle, block)) return 0xFFFFFFFFu;
    return MEM32(block - 8);
}

uint32_t void_heap_realloc(uint32_t handle, uint32_t block, uint32_t size, int zero, int in_place_only)
{
    heap_t *h = heap_find(handle);
    if (!h || !block_valid(handle, block) || size > 0x7FF00000u) return 0;
    uint32_t old = MEM32(block - 8);
    uint8_t *p;
    if (in_place_only) {
        p = (uint8_t *)mspace_realloc_in_place(h->space, GPTR(block - 8), (size_t)size + 8);
        if (!p) return 0;
    } else {
        p = (uint8_t *)mspace_realloc(h->space, GPTR(block - 8), (size_t)size + 8);
        if (!p) return 0;
    }
    uint32_t moved = GVA(p) + 8;
    MEM32(moved - 8) = size;
    MEM32(moved - 4) = BLOCK_MAGIC ^ handle;
    if (zero && size > old) memset(GPTR(moved + old), 0, size - old);
    return moved;
}

uint32_t void_galloc(uint32_t size) { return void_heap_alloc(void_process_heap(), size, 1); }
void void_gfree(uint32_t va) { if (va) void_heap_free(void_process_heap(), va); }

uint32_t void_gstrdup(const char *s)
{
    size_t n = strlen(s) + 1;
    uint32_t va = void_galloc((uint32_t)n);
    if (va) memcpy(GPTR(va), s, n);
    return va;
}
