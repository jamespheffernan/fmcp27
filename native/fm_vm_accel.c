/*
 * fm_vm_accel: in-process accelerator for fmdb's FastVM (fm_live_mcp/fmdb/fastvm.py).
 *
 * Loaded into the Python process with ctypes. It never touches the game: it only
 * manages host memory that backs a Unicorn instance and serves Unicorn's hot
 * callbacks without entering Python.
 *
 * Model (Unicorn virtual-TLB mode, one physical mapping per pool, never remapped):
 *   - code pool: the plugin __TEXT range, slot = (vaddr - text_lo) / 4096, filled
 *     lazily from the verified on-disk image by Python; read+execute.
 *   - data pool: copied live pages, slot allocated on first touch, found through an
 *     open-addressing hash of the virtual page number; read-only in the TLB until
 *     the first store of a call, which saves the original page (copy-on-write) and
 *     grants write access. fm_accel_restore() puts every saved page back.
 *   - private ranges (stack, heap, TLS, static, trap): identity mapped.
 * A TLB miss the pools cannot answer calls the Python `fault` callback, which
 * either adds the page (and returns true) or records why the call must stop.
 * The block hook counts instructions against the budget and checks the deadline.
 *
 * External calls. Python registers every import name with an id and an action. The
 * models that only return a constant or check the stack probe run here (ACT_*); the
 * rest are handed to Python. A call reaches an import either through a plugin stub
 * (code hook on the stub range) or through a bound live address: the fetch of a bound
 * address is answered with a page of `ret` instructions and the block hook, which sees
 * the exact address, applies the model before that `ret` runs. Every handled call is
 * appended to ext_log so Python can keep its per-call list and counters.
 *
 * Write access granted by the copy-on-write path stays in the TLB for up to
 * STICKY_PAGES pages; those pages are put back from their saved copy before every call.
 * Past that the set is cleared and the TLB flushed.
 *
 * Read tracking (version 2, optional). fm_accel_mem_read is a UC_HOOK_MEM_READ callback; while
 * tracking is on it marks, per copied live page, which 8-byte words emulated loads touched
 * (512 bits per page). fm_accel_peek marks the words Python-side models read. The on-demand
 * snapshot records these words as the read set of the cells it memoises, so a cell is
 * recomputed exactly when a word it read has changed (fm_live_mcp/fmdb/ondemand.py).
 * A word the call itself stored in full (fm_accel_mem_write, a UC_HOOK_MEM_WRITE callback, or a
 * copy-on-write poke) is left out of that call's read set, whether the store came before the
 * read (the value came from the call) or after it (reference counts, locks, the game's pooled
 * allocator free lists, lazily filled caches: bookkeeping a getter overwrites and the reader
 * discards). Reads and writes are collected per call and folded into the block's set when the
 * next call starts (fm_accel_restore) or the set is taken (fm_accel_touch_dump).
 * fm_accel_words_hash hashes the marked words of pages, for recording and for checking.
 */
#include <mach/mach_time.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

typedef struct uc_struct uc_engine;
typedef struct {
    uint64_t paddr;
    int perms;
} tlb_entry;

enum { MEM_READ = 16, MEM_WRITE = 17, MEM_FETCH = 18 };
enum { P_R = 1, P_W = 2, P_X = 4 };
enum { WHY_UNMAPPED = 0, WHY_FETCH_PROT = 1, WHY_WRITE_CODE = 2, WHY_WRITE_PROT = 3 };
enum { STOP_NONE = 0, STOP_BUDGET = 1, STOP_TIMEOUT = 2, STOP_STACK_PROBE = 3, STOP_NON_PLUGIN = 4 };
enum { ACT_PYTHON = 0, ACT_RETURN_0 = 1, ACT_RETURN_1 = 2, ACT_STACK_PROBE = 3 };
enum { PEEK_OK = 0, PEEK_MISSING = 1, PEEK_CODE = 2 };

#define PAGE 4096ull
#define VPAGE_MASK (~(PAGE - 1))
#define MAX_RANGES 8
#define EMPTY UINT64_MAX
#define TOUCH_WORDS 8u       /* 4096 / 8 words per page, 64 per mask */
#define DEADLINE_EVERY 1023u
#define STICKY_PAGES 16u
#define EXT_LOG_MAX 4096u
#define MAX_IMPORTS 4096u
#define IMPORT_HASH 16384u

typedef bool (*fault_fn)(uint64_t vaddr, int access, int why);
typedef void (*stub_fn)(uint64_t address);
typedef int (*emu_start_fn)(uc_engine *, uint64_t, uint64_t, uint64_t, size_t);
typedef int (*emu_stop_fn)(uc_engine *);
typedef int (*reg_write_batch_fn)(uc_engine *, int const *, void *const *, int);
typedef int (*reg_read_batch_fn)(uc_engine *, int const *, void **, int);
typedef int (*ctl_fn)(uc_engine *, int, ...);
typedef int (*reg_write_fn)(uc_engine *, int, const void *);

typedef struct {
    uint64_t lo, hi;
    uint64_t perms;
    uint8_t *host;
} range_t;

/* The first block is read and written from Python through ctypes: keep in sync with
 * fastvm._State. */
typedef struct {
    uint64_t icount, budget;
    uint64_t timeout_ticks, deadline;
    uint64_t stop;
    uint64_t pc, lr, sp, x0;
    uint64_t fills, faults, new_pages, tlb_flushes, blocks;
    uint64_t data_used, data_slots, ndirty;
    uint64_t miss_addr;
    uint64_t ext_n, pending_id, stop_addr;
    /* private from here */
    uc_engine *uc;
    emu_start_fn emu_start;
    emu_stop_fn emu_stop;
    reg_write_batch_fn reg_write_batch;
    reg_read_batch_fn reg_read_batch;
    ctl_fn ctl;
    reg_write_fn reg_write;
    int tlb_flush_code;
    int regs[34];        /* x0..x30, sp, tpidr_el0, tpidrro_el0 */
    int out_regs[4];     /* pc, lr, sp, x0 */
    fault_fn fault;
    uint64_t text_lo, text_size, code_phys, data_phys;
    uint8_t *code, *code_present;
    uint8_t *data, *save;
    uint64_t *slot_vpage;
    uint8_t *slot_dirty;
    uint32_t *dirty_list;
    uint64_t *keys;
    uint32_t *vals;
    uint64_t mask;
    range_t ranges[MAX_RANGES];
    int nranges;
    /* externals */
    stub_fn py_stub;
    uint64_t stub_lo, stub_n, pad_phys, probe_limit;
    uint16_t *stub_id;
    uint8_t *pad;
    uint8_t act[MAX_IMPORTS];
    uint64_t import_addr[IMPORT_HASH];
    uint16_t import_id[IMPORT_HASH];
    uint64_t pad_page[IMPORT_HASH];
    uint16_t ext_log[EXT_LOG_MAX];
    int reg_x0, reg_x9, reg_pc, reg_lr;
    int touched;        /* emulated code or a copy-on-write poke ran since the last restore */
    /* read tracking */
    int track;
    uint64_t *slot_touch;       /* per data slot: TOUCH_WORDS masks, bit k = 8-byte word k was read */
    uint8_t *slot_touched;      /* per data slot: on touch_list */
    uint64_t *slot_rcall;       /* per data slot: words read by the current call */
    uint8_t *slot_rcalled;      /* per data slot: on rcall_list */
    uint32_t *rcall_list;
    uint64_t nrcall;
    uint64_t *slot_wrote;       /* per data slot: words stored in full by the current call */
    uint8_t *slot_written;      /* per data slot: on wrote_list */
    uint32_t *wrote_list;
    uint64_t nwrote;
    uint32_t *touch_list;       /* slots with a non-zero mask, in first-touch order */
    uint64_t ntouch;
} accel_t;

static void *reserve(size_t size) {
    void *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    return p == MAP_FAILED ? NULL : p;
}

static inline uint64_t hash_page(uint64_t vpage) {
    vpage *= 0x9E3779B97F4A7C15ull;
    return vpage ^ (vpage >> 29);
}

static inline int64_t lookup(const accel_t *a, uint64_t vpage) {
    uint64_t i = hash_page(vpage) & a->mask;
    for (;;) {
        uint64_t k = a->keys[i];
        if (k == vpage) return a->vals[i];
        if (k == EMPTY) return -1;
        i = (i + 1) & a->mask;
    }
}

static void flush_tlb(accel_t *a) {
    a->ctl(a->uc, a->tlb_flush_code);
    a->tlb_flushes++;
}

accel_t *fm_accel_new(uc_engine *uc, void *const *fns, const int *regs, const int *out_regs, int tlb_flush_code,
                      uint64_t text_lo, uint64_t text_size, uint64_t code_phys, uint64_t data_phys,
                      uint64_t data_slots, fault_fn fault) {
    accel_t *a = calloc(1, sizeof(*a));
    if (!a) return NULL;
    a->uc = uc;
    a->emu_start = (emu_start_fn)fns[0];
    a->emu_stop = (emu_stop_fn)fns[1];
    a->reg_write_batch = (reg_write_batch_fn)fns[2];
    a->reg_read_batch = (reg_read_batch_fn)fns[3];
    a->ctl = (ctl_fn)fns[4];
    a->reg_write = (reg_write_fn)fns[5];
    a->tlb_flush_code = tlb_flush_code;
    memcpy(a->regs, regs, sizeof(a->regs));
    memcpy(a->out_regs, out_regs, sizeof(a->out_regs));
    a->fault = fault;
    a->text_lo = text_lo;
    a->text_size = (text_size + PAGE - 1) & VPAGE_MASK;
    a->code_phys = code_phys;
    a->data_phys = data_phys;
    a->data_slots = data_slots;
    uint64_t cap = 1;
    while (cap < data_slots * 2) cap <<= 1;
    a->mask = cap - 1;
    a->code = reserve(a->text_size);
    a->code_present = calloc(a->text_size / PAGE, 1);
    a->data = reserve(data_slots * PAGE);
    a->save = reserve(data_slots * PAGE);
    a->slot_vpage = malloc(data_slots * sizeof(uint64_t));
    a->slot_dirty = calloc(data_slots, 1);
    a->dirty_list = malloc(data_slots * sizeof(uint32_t));
    a->keys = malloc(cap * sizeof(uint64_t));
    a->vals = malloc(cap * sizeof(uint32_t));
    a->slot_touch = calloc(data_slots * TOUCH_WORDS, sizeof(uint64_t));
    a->slot_touched = calloc(data_slots, 1);
    a->slot_rcall = calloc(data_slots * TOUCH_WORDS, sizeof(uint64_t));
    a->slot_rcalled = calloc(data_slots, 1);
    a->rcall_list = malloc(data_slots * sizeof(uint32_t));
    a->slot_wrote = calloc(data_slots * TOUCH_WORDS, sizeof(uint64_t));
    a->slot_written = calloc(data_slots, 1);
    a->wrote_list = malloc(data_slots * sizeof(uint32_t));
    a->touch_list = malloc(data_slots * sizeof(uint32_t));
    if (!a->code || !a->code_present || !a->data || !a->save || !a->slot_vpage || !a->slot_dirty ||
        !a->dirty_list || !a->keys || !a->vals || !a->slot_touch || !a->slot_touched || !a->touch_list ||
        !a->slot_wrote || !a->slot_written || !a->wrote_list || !a->slot_rcall || !a->slot_rcalled ||
        !a->rcall_list)
        return NULL;
    memset(a->keys, 0xFF, cap * sizeof(uint64_t));
    return a;
}

void fm_accel_free(accel_t *a) {
    if (!a) return;
    munmap(a->code, a->text_size);
    munmap(a->data, a->data_slots * PAGE);
    munmap(a->save, a->data_slots * PAGE);
    for (int i = 0; i < a->nranges; i++)
        if (a->ranges[i].host) munmap(a->ranges[i].host, a->ranges[i].hi - a->ranges[i].lo);
    free(a->code_present);
    free(a->slot_vpage);
    free(a->slot_dirty);
    free(a->dirty_list);
    free(a->keys);
    free(a->vals);
    free(a->slot_touch);
    free(a->slot_touched);
    free(a->slot_wrote);
    free(a->slot_rcall);
    free(a->slot_rcalled);
    free(a->rcall_list);
    free(a->slot_written);
    free(a->wrote_list);
    free(a->touch_list);
    free(a);
}

uint8_t *fm_accel_code_host(accel_t *a) { return a->code; }
uint8_t *fm_accel_data_host(accel_t *a) { return a->data; }

/* A private identity range backed by host memory this library owns. */
uint8_t *fm_accel_add_range(accel_t *a, uint64_t lo, uint64_t size, int perms) {
    if (a->nranges >= MAX_RANGES) return NULL;
    uint8_t *host = reserve(size);
    if (!host) return NULL;
    range_t *r = &a->ranges[a->nranges++];
    r->lo = lo;
    r->hi = lo + size;
    r->perms = (uint64_t)perms;
    r->host = host;
    return host;
}

void fm_accel_add_code(accel_t *a, uint64_t vaddr, const uint8_t *bytes) {
    uint64_t off = (vaddr - a->text_lo) & VPAGE_MASK;
    memcpy(a->code + off, bytes, PAGE);
    a->code_present[off / PAGE] = 1;
}

/* Returns the slot, -1 when the pool is full, -2 when the page is already present. */
int64_t fm_accel_add_data(accel_t *a, uint64_t vaddr, const uint8_t *bytes) {
    uint64_t vpage = vaddr / PAGE;
    if (lookup(a, vpage) >= 0) return -2;
    if (a->data_used >= a->data_slots) return -1;
    uint64_t slot = a->data_used++;
    memcpy(a->data + slot * PAGE, bytes, PAGE);
    a->slot_vpage[slot] = vpage;
    a->slot_dirty[slot] = 0;
    if (a->slot_touched[slot]) {      /* a slot reused after reset_data: its marks were cleared there */
        a->slot_touched[slot] = 0;
        memset(a->slot_touch + slot * TOUCH_WORDS, 0, TOUCH_WORDS * sizeof(uint64_t));
    }
    uint64_t i = hash_page(vpage) & a->mask;
    while (a->keys[i] != EMPTY) i = (i + 1) & a->mask;
    a->keys[i] = vpage;
    a->vals[i] = (uint32_t)slot;
    a->new_pages++;
    return (int64_t)slot;
}

/* 0 absent, 1 data, 2 code (present), 3 private. */
int fm_accel_has(const accel_t *a, uint64_t vaddr) {
    if (vaddr - a->text_lo < a->text_size) return a->code_present[(vaddr - a->text_lo) / PAGE] ? 2 : 0;
    for (int i = 0; i < a->nranges; i++)
        if (vaddr >= a->ranges[i].lo && vaddr < a->ranges[i].hi) return 3;
    return lookup(a, vaddr / PAGE) >= 0 ? 1 : 0;
}

static inline void cow(accel_t *a, uint64_t slot) {
    if (a->slot_dirty[slot]) return;
    memcpy(a->save + a->ndirty * PAGE, a->data + slot * PAGE, PAGE);
    a->dirty_list[a->ndirty++] = (uint32_t)slot;
    a->slot_dirty[slot] = 1;
}

void fm_accel_touch_clear(accel_t *a);

/* End of a call: its reads, less the words it stored in full, join the block's read set. */
static void touch_settle(accel_t *a) {
    for (uint64_t i = 0; i < a->nrcall; i++) {
        uint32_t slot = a->rcall_list[i];
        uint64_t *rcall = a->slot_rcall + (uint64_t)slot * TOUCH_WORDS;
        const uint64_t *wrote = a->slot_wrote + (uint64_t)slot * TOUCH_WORDS;
        uint64_t *mask = a->slot_touch + (uint64_t)slot * TOUCH_WORDS;
        uint64_t any = 0;
        for (unsigned m = 0; m < TOUCH_WORDS; m++) {
            uint64_t bits = rcall[m] & ~wrote[m];
            mask[m] |= bits;
            any |= bits;
            rcall[m] = 0;
        }
        a->slot_rcalled[slot] = 0;
        if (any && !a->slot_touched[slot]) {
            a->slot_touched[slot] = 1;
            a->touch_list[a->ntouch++] = slot;
        }
    }
    a->nrcall = 0;
    for (uint64_t i = 0; i < a->nwrote; i++) {
        uint32_t slot = a->wrote_list[i];
        a->slot_written[slot] = 0;
        memset(a->slot_wrote + (uint64_t)slot * TOUCH_WORDS, 0, TOUCH_WORDS * sizeof(uint64_t));
    }
    a->nwrote = 0;
}

/* Undo every store of the previous call. Up to STICKY_PAGES pages keep their write access
 * (and their saved copy); beyond that the set is cleared and the TLB flushed. */
void fm_accel_restore(accel_t *a) {
    if (a->nrcall || a->nwrote) touch_settle(a);       /* the previous call is over */
    if (!a->ndirty || !a->touched) return;
    a->touched = 0;
    for (uint64_t i = 0; i < a->ndirty; i++)
        memcpy(a->data + (uint64_t)a->dirty_list[i] * PAGE, a->save + i * PAGE, PAGE);
    if (a->ndirty <= STICKY_PAGES) return;
    for (uint64_t i = 0; i < a->ndirty; i++) a->slot_dirty[a->dirty_list[i]] = 0;
    a->ndirty = 0;
    flush_tlb(a);
}

/* Forget every copied live page (the code pool and the private ranges stay). */
void fm_accel_reset_data(accel_t *a) {
    for (uint64_t i = 0; i < a->ndirty; i++) a->slot_dirty[a->dirty_list[i]] = 0;
    a->ndirty = 0;
    a->data_used = 0;
    fm_accel_touch_clear(a);
    memset(a->keys, 0xFF, (a->mask + 1) * sizeof(uint64_t));
    flush_tlb(a);
}

/* ---- read tracking ---- */
static inline void mark_slot(accel_t *a, uint64_t slot, uint64_t first, uint64_t last) {
    uint64_t *rcall = a->slot_rcall + slot * TOUCH_WORDS;
    if (!a->slot_rcalled[slot]) {
        a->slot_rcalled[slot] = 1;
        a->rcall_list[a->nrcall++] = (uint32_t)slot;
    }
    for (uint64_t w = first >> 3; w <= last >> 3; w++) rcall[w >> 6] |= 1ull << (w & 63);
}

/* Words of [first, last] (offsets in the slot's page) that a store covers in full. */
static inline void mark_wrote(accel_t *a, uint64_t slot, uint64_t first, uint64_t last) {
    uint64_t lo = (first + 7) >> 3, end = (last + 1) >> 3;      /* words [lo, end) are covered */
    if (lo >= end) return;
    if (!a->slot_written[slot]) {
        a->slot_written[slot] = 1;
        a->wrote_list[a->nwrote++] = (uint32_t)slot;
    }
    uint64_t *wrote = a->slot_wrote + slot * TOUCH_WORDS;
    for (uint64_t w = lo; w < end; w++) wrote[w >> 6] |= 1ull << (w & 63);
}

/* Mark the words of [addr, addr + size) (guest virtual) on copied live pages. */
static inline void mark_read(accel_t *a, uint64_t addr, uint64_t size) {
    if (!size) return;
    uint64_t last = addr + size - 1;
    for (uint64_t page = addr / PAGE; page <= last / PAGE; page++) {
        int64_t slot = lookup(a, page);
        if (slot < 0) continue;      /* code pool, private range or absent: not live data */
        mark_slot(a, (uint64_t)slot, page == addr / PAGE ? (addr & (PAGE - 1)) : 0,
                  page == last / PAGE ? (last & (PAGE - 1)) : PAGE - 1);
    }
}

/* UC_HOOK_MEM_READ. In virtual-TLB mode Unicorn reports the translated ("physical") address:
 * a load from a copied live page arrives as data_phys + slot * PAGE + offset. A load that
 * crosses into the next guest page continues on that page's own slot. */
void fm_accel_mem_read(uc_engine *uc, int type, uint64_t address, int size, int64_t value, void *user) {
    (void)uc;
    (void)type;
    (void)value;
    accel_t *a = user;
    if (!a->track || size <= 0) return;
    uint64_t off = address - a->data_phys;
    if (off >= a->data_used * PAGE) return;      /* code pool or private range */
    uint64_t slot = off / PAGE, first = off & (PAGE - 1), last = first + (uint64_t)size - 1;
    if (last < PAGE) {
        mark_slot(a, slot, first, last);
        return;
    }
    mark_slot(a, slot, first, PAGE - 1);
    mark_read(a, (a->slot_vpage[slot] + 1) * PAGE, last - PAGE + 1);
}

/* UC_HOOK_MEM_WRITE: the same address convention as fm_accel_mem_read. A store that crosses a
 * page is counted on its first page only (the rest stays "not written": conservative). */
void fm_accel_mem_write(uc_engine *uc, int type, uint64_t address, int size, int64_t value, void *user) {
    (void)uc;
    (void)type;
    (void)value;
    accel_t *a = user;
    if (!a->track || size <= 0) return;
    uint64_t off = address - a->data_phys;
    if (off >= a->data_used * PAGE) return;
    uint64_t first = off & (PAGE - 1), last = first + (uint64_t)size - 1;
    mark_wrote(a, off / PAGE, first, last < PAGE ? last : PAGE - 1);
}

int fm_accel_version(void) { return 2; }
unsigned fm_accel_touch_words(void) { return TOUCH_WORDS; }

/* Turn marking on or off; returns the previous state. */
int fm_accel_track(accel_t *a, int on) {
    int was = a->track;
    a->track = on;
    return was;
}

void fm_accel_touch_clear(accel_t *a) {
    touch_settle(a);
    for (uint64_t i = 0; i < a->ntouch; i++) {
        uint32_t slot = a->touch_list[i];
        a->slot_touched[slot] = 0;
        memset(a->slot_touch + (uint64_t)slot * TOUCH_WORDS, 0, TOUCH_WORDS * sizeof(uint64_t));
    }
    a->ntouch = 0;
}

/* Fold the last call in; the number of pages in the block's read set. */
uint64_t fm_accel_touch_count(accel_t *a) {
    touch_settle(a);
    return a->ntouch;
}

/* Write up to `max` records of 1 + TOUCH_WORDS u64 (page address, then the word masks);
 * returns the number of records. */
uint64_t fm_accel_touch_dump(const accel_t *a, uint64_t *out, uint64_t max) {
    uint64_t n = a->ntouch < max ? a->ntouch : max;
    for (uint64_t i = 0; i < n; i++) {
        uint32_t slot = a->touch_list[i];
        uint64_t *rec = out + i * (1 + TOUCH_WORDS);
        rec[0] = a->slot_vpage[slot] * PAGE;
        memcpy(rec + 1, a->slot_touch + (uint64_t)slot * TOUCH_WORDS, TOUCH_WORDS * sizeof(uint64_t));
    }
    return n;
}

/* out[i] = hash of the marked 8-byte words of the 4 KiB page at buf + offsets[i], for n records
 * of 1 + TOUCH_WORDS u64 as fm_accel_touch_dump writes them (the page address is not hashed).
 * An offset of UINT64_MAX (page not available) gives 0. No accel_t: usable on any buffer. */
void fm_accel_words_hash(const uint8_t *buf, const uint64_t *offsets, const uint64_t *records, uint64_t n,
                         uint64_t *out) {
    for (uint64_t i = 0; i < n; i++) {
        if (offsets[i] == UINT64_MAX) {
            out[i] = 0;
            continue;
        }
        const uint8_t *page = buf + offsets[i];
        const uint64_t *mask = records + i * (1 + TOUCH_WORDS) + 1;
        uint64_t h = 0x9E3779B97F4A7C15ull;
        for (unsigned m = 0; m < TOUCH_WORDS; m++) {
            uint64_t bits = mask[m];
            while (bits) {
                unsigned k = (unsigned)__builtin_ctzll(bits);
                bits &= bits - 1;
                uint64_t word;
                memcpy(&word, page + ((uint64_t)m * 64 + k) * 8, 8);
                h ^= word + 0x9E3779B97F4A7C15ull + (h << 6) + (h >> 2);
                h *= 0xFF51AFD7ED558CCDull;
                h ^= h >> 33;
            }
        }
        out[i] = h | 1;       /* never 0: 0 means "page not available" */
    }
}

static uint8_t *host_of(accel_t *a, uint64_t vaddr, int *kind) {
    if (vaddr - a->text_lo < a->text_size) {
        *kind = 2;
        return a->code_present[(vaddr - a->text_lo) / PAGE] ? a->code + (vaddr - a->text_lo) : NULL;
    }
    for (int i = 0; i < a->nranges; i++)
        if (vaddr >= a->ranges[i].lo && vaddr < a->ranges[i].hi) {
            *kind = 3;
            return a->ranges[i].host + (vaddr - a->ranges[i].lo);
        }
    *kind = 1;
    int64_t slot = lookup(a, vaddr / PAGE);
    return slot < 0 ? NULL : a->data + (uint64_t)slot * PAGE + (vaddr & (PAGE - 1));
}

/* Copy guest memory out. PEEK_MISSING leaves the first absent address in miss_addr. */
int fm_accel_peek(accel_t *a, uint64_t vaddr, uint8_t *dst, uint64_t length) {
    while (length) {
        int kind;
        uint8_t *host = host_of(a, vaddr, &kind);
        if (!host) {
            a->miss_addr = vaddr;
            return PEEK_MISSING;
        }
        uint64_t n = PAGE - (vaddr & (PAGE - 1));
        if (n > length) n = length;
        memcpy(dst, host, n);
        if (a->track && kind == 1) mark_read(a, vaddr, n);
        dst += n;
        vaddr += n;
        length -= n;
    }
    return PEEK_OK;
}

/* Copy into guest memory. With copy_on_write, data pages are saved first (undone by
 * fm_accel_restore); without it the bytes stay for the session (overlays). Code is refused. */
int fm_accel_poke(accel_t *a, uint64_t vaddr, const uint8_t *src, uint64_t length, int copy_on_write) {
    uint64_t at = vaddr, left = length;
    while (left) {         /* check first: a refused poke changes nothing */
        int kind;
        uint8_t *host = host_of(a, at, &kind);
        if (kind == 2) {
            a->miss_addr = at;
            return PEEK_CODE;
        }
        if (!host) {
            a->miss_addr = at;
            return PEEK_MISSING;
        }
        uint64_t n = PAGE - (at & (PAGE - 1));
        if (n > left) n = left;
        at += n;
        left -= n;
    }
    while (length) {
        int kind;
        uint8_t *host = host_of(a, vaddr, &kind);
        uint64_t n = PAGE - (vaddr & (PAGE - 1));
        if (n > length) n = length;
        if (kind == 1) {
            uint64_t slot = (uint64_t)lookup(a, vaddr / PAGE);
            if (copy_on_write) {
                cow(a, slot);
                if (a->track) mark_wrote(a, slot, vaddr & (PAGE - 1), (vaddr & (PAGE - 1)) + n - 1);
                a->touched = 1;
            } else if (a->slot_dirty[slot]) {       /* persistent store: the saved copy must carry it too */
                for (uint64_t i = 0; i < a->ndirty; i++)
                    if (a->dirty_list[i] == slot) memcpy(a->save + i * PAGE + (vaddr & (PAGE - 1)), src, n);
            }
        }
        memcpy(host, src, n);
        src += n;
        vaddr += n;
        length -= n;
    }
    return PEEK_OK;
}

static inline uint64_t import_slot(uint64_t key) { return (hash_page(key) >> 7) & (IMPORT_HASH - 1); }

static int import_lookup(const accel_t *a, uint64_t address) {
    uint64_t i = import_slot(address);
    for (;;) {
        if (a->import_addr[i] == address) return a->import_id[i];
        if (a->import_addr[i] == 0) return 0;
        i = (i + 1) & (IMPORT_HASH - 1);
    }
}

static bool is_pad_page(const accel_t *a, uint64_t page) {
    uint64_t i = import_slot(page);
    for (;;) {
        if (a->pad_page[i] == page) return true;
        if (a->pad_page[i] == 0) return false;
        i = (i + 1) & (IMPORT_HASH - 1);
    }
}

void fm_accel_clear_imports(accel_t *a) {
    memset(a->import_addr, 0, sizeof(a->import_addr));
    memset(a->pad_page, 0, sizeof(a->pad_page));
}

void fm_accel_set_action(accel_t *a, uint32_t id, int action) {
    if (id < MAX_IMPORTS) a->act[id] = (uint8_t)action;
}

/* A bound live address of import `id`. Addresses whose model runs here get a `ret` page. */
void fm_accel_set_import(accel_t *a, uint64_t address, uint32_t id) {
    if (!address || id >= MAX_IMPORTS) return;
    uint64_t i = import_slot(address);
    while (a->import_addr[i] && a->import_addr[i] != address) i = (i + 1) & (IMPORT_HASH - 1);
    a->import_addr[i] = address;
    a->import_id[i] = (uint16_t)id;
    if (a->act[id] == ACT_PYTHON) return;
    uint64_t page = address & VPAGE_MASK;
    i = import_slot(page);
    while (a->pad_page[i] && a->pad_page[i] != page) i = (i + 1) & (IMPORT_HASH - 1);
    a->pad_page[i] = page;
}

/* Plugin stubs: ids[k] is the import id of the stub starting at stub_lo + 4 * k (0: none). */
uint8_t *fm_accel_set_stubs(accel_t *a, uint64_t stub_lo, uint64_t count, const uint16_t *ids, uint64_t pad_phys,
                            uint64_t probe_limit, stub_fn py_stub, const int *regs4) {
    a->stub_lo = stub_lo;
    a->stub_n = count;
    a->stub_id = malloc(count * sizeof(uint16_t) + 2);
    a->pad = reserve(PAGE);
    if (!a->stub_id || !a->pad) return NULL;
    memcpy(a->stub_id, ids, count * sizeof(uint16_t));
    for (uint64_t i = 0; i < PAGE; i += 4) memcpy(a->pad + i, "\xc0\x03\x5f\xd6", 4);     /* ret */
    a->pad_phys = pad_phys;
    a->probe_limit = probe_limit;
    a->py_stub = py_stub;
    a->reg_x0 = regs4[0];
    a->reg_x9 = regs4[1];
    a->reg_pc = regs4[2];
    a->reg_lr = regs4[3];
    return a->pad;
}

static uint64_t get_reg(accel_t *a, int reg) {
    uint64_t value = 0;
    void *ptr = &value;
    a->reg_read_batch(a->uc, &reg, &ptr, 1);
    return value;
}

static void set_reg(accel_t *a, int reg, uint64_t value) {
    a->reg_write(a->uc, reg, &value);      /* uc_reg_write: a PC write ends the current block */
}

/* Run the model of import `id` when it is one of the constant ones. False: Python's turn. */
static bool native_external(accel_t *a, uint32_t id) {
    if (a->ext_n >= EXT_LOG_MAX) return false;
    switch (a->act[id]) {
    case ACT_RETURN_0:
        set_reg(a, a->reg_x0, 0);
        break;
    case ACT_RETURN_1:
        set_reg(a, a->reg_x0, 1);
        break;
    case ACT_STACK_PROBE: {
        uint64_t frame = get_reg(a, a->reg_x9);
        a->ext_log[a->ext_n++] = (uint16_t)id;
        if (frame > a->probe_limit) {
            if (!a->stop) {
                a->stop = STOP_STACK_PROBE;
                a->stop_addr = frame;
            }
            a->emu_stop(a->uc);
        }
        return true;
    }
    default:
        return false;
    }
    a->ext_log[a->ext_n++] = (uint16_t)id;
    return true;
}

/* UC_HOOK_CODE over the plugin stub range */
void fm_accel_stub(uc_engine *uc, uint64_t address, uint32_t size, void *user) {
    (void)uc;
    (void)size;
    accel_t *a = user;
    uint64_t k = (address - a->stub_lo) >> 2;
    uint32_t id = k < a->stub_n ? a->stub_id[k] : 0;
    if (!id) return;
    if (!native_external(a, id)) {
        a->py_stub(address);
        return;
    }
    if (!a->stop) set_reg(a, a->reg_pc, get_reg(a, a->reg_lr));
}

/* A block that starts outside the plugin: a bound import on a `ret` page, or the stop address. */
static void external_block(accel_t *a, uint64_t address) {
    for (int i = 0; i < a->nranges; i++)
        if (address >= a->ranges[i].lo && address < a->ranges[i].hi) return;
    uint32_t id = (uint32_t)import_lookup(a, address);
    if (!id) {
        if (!a->stop) {
            a->stop = STOP_NON_PLUGIN;
            a->stop_addr = address;
        }
        a->emu_stop(a->uc);
        return;
    }
    if (native_external(a, id)) return;
    a->pending_id = id;         /* Python runs the model and resumes at the link register */
    a->emu_stop(a->uc);
}

/* UC_HOOK_TLB_FILL */
bool fm_accel_tlb_fill(uc_engine *uc, uint64_t vaddr, int type, tlb_entry *entry, void *user) {
    (void)uc;
    accel_t *a = user;
    a->fills++;
    for (int attempt = 0; attempt < 2; attempt++) {
        if (vaddr - a->text_lo < a->text_size) {
            if (type == MEM_WRITE) {
                a->faults++;
                a->fault(vaddr, type, WHY_WRITE_CODE);
                return false;
            }
            if (a->code_present[(vaddr - a->text_lo) / PAGE]) {
                entry->paddr = a->code_phys + (vaddr - a->text_lo);
                entry->perms = P_R | P_X;
                return true;
            }
        } else {
            int found = 0;
            for (int i = 0; i < a->nranges; i++) {
                const range_t *r = &a->ranges[i];
                if (vaddr >= r->lo && vaddr < r->hi) {
                    if (type == MEM_FETCH && !(r->perms & P_X)) {
                        a->faults++;
                        a->fault(vaddr, type, WHY_FETCH_PROT);
                        return false;
                    }
                    if (type == MEM_WRITE && !(r->perms & P_W)) {
                        a->faults++;
                        a->fault(vaddr, type, WHY_WRITE_PROT);
                        return false;
                    }
                    entry->paddr = vaddr;
                    entry->perms = (int)r->perms;
                    return true;
                }
            }
            if (!found) {
                int64_t slot = lookup(a, vaddr / PAGE);
                if (slot >= 0) {
                    if (type == MEM_FETCH) {
                        if (a->pad && is_pad_page(a, vaddr & VPAGE_MASK)) {
                            entry->paddr = a->pad_phys + (vaddr & (PAGE - 1));
                            entry->perms = P_X;
                            return true;
                        }
                        a->faults++;
                        a->fault(vaddr, type, WHY_FETCH_PROT);
                        return false;
                    }
                    if (type == MEM_WRITE) cow(a, (uint64_t)slot);
                    entry->paddr = a->data_phys + (uint64_t)slot * PAGE + (vaddr & (PAGE - 1));
                    entry->perms = a->slot_dirty[slot] ? (P_R | P_W) : P_R;
                    return true;
                }
            }
        }
        if (attempt) break;
        if (type == MEM_FETCH && !(vaddr - a->text_lo < a->text_size)) {
            /* Unicorn also asks for the block before the stop address when a run ends. Only a
             * fetch at the program counter is a jump out of the plugin. */
            uint64_t pc = 0;
            void *ptr = &pc;
            a->reg_read_batch(a->uc, a->out_regs, &ptr, 1);
            if (((pc ^ vaddr) & 0x00007FFFFFFFFC00ull) != 0) return false;
            if (a->pad && is_pad_page(a, vaddr & VPAGE_MASK)) {
                entry->paddr = a->pad_phys + (vaddr & (PAGE - 1));
                entry->perms = P_X;
                return true;
            }
        }
        a->faults++;
        if (!a->fault(vaddr, type, WHY_UNMAPPED)) return false;
    }
    return false;
}

/* UC_HOOK_BLOCK */
void fm_accel_block(uc_engine *uc, uint64_t address, uint32_t size, void *user) {
    accel_t *a = user;
    if (address - a->text_lo >= a->text_size) {
        external_block(a, address);
        return;
    }
    a->icount += size >> 2;
    if (a->icount > a->budget) {
        if (!a->stop) a->stop = STOP_BUDGET;
        a->emu_stop(uc);
        return;
    }
    if ((++a->blocks & DEADLINE_EVERY) == 0 && a->deadline && mach_absolute_time() > a->deadline) {
        if (!a->stop) a->stop = STOP_TIMEOUT;
        a->emu_stop(uc);
    }
}

/* Set x0..x30, sp and the thread registers from regs[34] (when not NULL). */
void fm_accel_set_regs(accel_t *a, const uint64_t *regs) {
    void *ptrs[34];
    for (int i = 0; i < 34; i++) ptrs[i] = (void *)&regs[i];
    a->reg_write_batch(a->uc, a->regs, ptrs, 34);
}

/* One uc_emu_start; leaves pc, lr, sp and x0 in the shared state. Returns the uc_err. */
int fm_accel_run(accel_t *a, uint64_t pc, uint64_t until) {
    a->deadline = a->timeout_ticks ? mach_absolute_time() + a->timeout_ticks : 0;
    a->touched = 1;
    int err = a->emu_start(a->uc, pc, until, 0, 0);
    void *ptrs[4] = {&a->pc, &a->lr, &a->sp, &a->x0};
    a->reg_read_batch(a->uc, a->out_regs, ptrs, 4);
    return err;
}

uint16_t *fm_accel_ext_log(accel_t *a) { return a->ext_log; }

uint64_t fm_accel_ticks_per_second(void) {
    mach_timebase_info_data_t info;
    mach_timebase_info(&info);
    return (uint64_t)(1e9 * (double)info.denom / (double)info.numer);
}
