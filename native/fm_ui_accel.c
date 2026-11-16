/*
 * fm_ui_accel: in-process accelerator for fmdb's FastUiHandlerVM (fm_live_mcp/fmdb/ui_fastvm.py).
 *
 * A superset of fm_vm_accel.c (same fm_accel_* entry points, so fastvm.FastVM's methods work on
 * it unchanged) built as its own library (scripts/build_ui_accel.sh -> build/libfm_ui_accel2.dylib, ABI 2).
 * It never touches the game: it manages host memory behind a Unicorn instance and serves
 * Unicorn's hot callbacks without entering Python.
 *
 * What it adds for UI handlers (docs/fmdb/UI_FAST.md):
 *   - tracked pages: the copied live pages (data pool) and the VM heap are read-only in the TLB
 *     until first written; the set written since the last commit/restore is the unit of work of
 *     both, so their cost follows the bytes changed, not the size of the heap;
 *   - baselines: fm_ui_commit() makes an immutable snapshot {page -> shared 4 KiB blob} of the
 *     VM-private state, fm_ui_restore() returns to any snapshot (or to pristine live memory);
 *   - freshness: every data page carries the generation it was read in; a page of an older
 *     generation is treated as absent, so the Python fault callback re-reads it from the game
 *     before any code sees it (no computation mixes pages of different ages);
 *   - read sets: fm_ui_trace_begin()/fm_ui_trace_collect() list the live pages a computation
 *     touched, fm_ui_hash_* fingerprint them;
 *   - native models of the hot imports (memcpy/memmove, memset, bzero, strlen, strcmp, strncmp,
 *     memcmp, malloc/new, pthread_self, the owner thread's TLV accessor) and of the game's pool
 *     allocator entry points. A model that meets anything unusual (absent page, refused range,
 *     size limit) declines, and Python runs its own model with the reference behaviour.
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
enum {
    ACT_PYTHON = 0, ACT_RETURN_0 = 1, ACT_RETURN_1 = 2, ACT_STACK_PROBE = 3,
    ACT_MEMCPY = 4, ACT_MEMSET = 5, ACT_BZERO = 6, ACT_STRLEN = 7, ACT_STRCMP = 8, ACT_MEMCMP = 9,
    ACT_MALLOC = 10, ACT_CALLOC = 11, ACT_ALIGNED_NEW = 12, ACT_PTHREAD_SELF = 13, ACT_PTHREAD_EQUAL = 14,
    ACT_TLV = 15, ACT_STRNCMP = 16, ACT_POOL_ALLOC = 17, ACT_POOL_FREE = 18, ACT_FIXED_POOL_ALLOC = 19,
    ACT_POOL_GET = 20, ACT_FREE_LIST_POP = 21, ACT_FREE_LIST_PUSH = 22,
    ACT_COUNT = 23
};
#define ABI_VERSION 2             /* fm_ui_abi_version(): free-list sites (fm_ui_add_site) */
enum { PEEK_OK = 0, PEEK_MISSING = 1, PEEK_CODE = 2 };

#define PAGE 4096ull
#define VPAGE_MASK (~(PAGE - 1))
#define MAX_RANGES 8
#define EMPTY UINT64_MAX
#define DEADLINE_EVERY 1023u
#define EXT_LOG_MAX 4096u
#define MAX_IMPORTS 4096u
#define IMPORT_HASH 16384u
#define MAX_INTERCEPTS 24
#define SITE_SETS 2
#define COPY_LIMIT 0x1000000ull       /* the Python models refuse larger copies */
#define STRING_LIMIT (1ull << 20)
#define BLOB_CHUNK 256
#define NO_BLOB 0xFFFFFFFFu

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

typedef struct blob {
    struct blob *next;
    uint32_t ref;
    uint32_t pad;
    uint8_t data[PAGE];
} blob_t;

typedef struct {
    uint32_t page;
    uint32_t pad;
    blob_t *blob;
} snap_entry;

typedef struct snapshot {
    uint64_t serial, data_epoch;
    uint64_t n;
    snap_entry *e;
} snapshot_t;

/* The first block is read and written from Python through ctypes: keep in sync with
 * ui_fastvm._State (the fields up to stop_addr are fastvm._State). */
typedef struct {
    uint64_t icount, budget;
    uint64_t timeout_ticks, deadline;
    uint64_t stop;
    uint64_t pc, lr, sp, x0;
    uint64_t fills, faults, new_pages, tlb_flushes, blocks;
    uint64_t data_used, data_slots, ndirty;
    uint64_t miss_addr;
    uint64_t ext_n, pending_id, stop_addr;
    /* UI additions */
    uint64_t heap_top, heap_lo, heap_hi;
    uint64_t nalloc;
    uint64_t gen, trace;
    uint64_t sticky;
    uint64_t native_calls, declined;
    uint64_t commits, restores, pages_committed, pages_restored, blobs_live;
    uint64_t oom;
    uint64_t current_serial;
    uint64_t nbase;
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
    uint8_t *data;
    uint64_t *slot_vpage;
    uint32_t *slot_gen, *slot_touch;
    uint64_t *keys;
    uint32_t *vals;
    uint64_t mask;
    range_t ranges[MAX_RANGES];
    int nranges, heap_range;
    /* tracked pages: data slots, then heap pages */
    uint64_t ntracked, heap_pages;
    uint8_t *heap_host;
    blob_t **orig, **base;
    uint8_t *wr;
    uint32_t *wlist, *blist, *bpos, *mark;
    uint64_t nw, tlb_w;
    uint32_t mark_epoch;
    uint64_t data_epoch, serial;
    /* word-level read set: 512 bits per data slot (one per 8 bytes), set while rtrack */
    uint64_t *rbits;
    uint8_t *watch;             /* per data slot: loads and stores go through fm_ui_watch_* */
    uint64_t watch_phys, nwatch, watch_hits;
    uint64_t dbg_addr, dbg_n;   /* diagnostics: who reads this watched word */
    uint64_t dbg_pc[32], dbg_lr[32];
    int rtrack;
    uint64_t rc_vpage;
    int64_t rc_slot;
    blob_t *free_blobs;
    void **chunks;
    uint64_t nchunks, chunk_cap;
    uint8_t *zero;
    /* allocations */
    uint64_t *alloc_addr, *alloc_size;
    uint64_t alloc_cap;
    /* externals */
    stub_fn py_stub;
    uint64_t stub_lo, stub_n, pad_phys, probe_limit;
    uint16_t *stub_id;
    uint8_t *pad;
    uint8_t act[MAX_IMPORTS];
    uint32_t ext_count[MAX_IMPORTS];
    uint64_t import_addr[IMPORT_HASH];
    uint16_t import_id[IMPORT_HASH];
    uint64_t pad_page[IMPORT_HASH];
    uint16_t ext_log[EXT_LOG_MAX];
    int reg_x0, reg_x9, reg_pc, reg_lr;
    int log_externals;
    /* owner thread */
    int owner_thread;
    uint64_t thread_flag, thread_main, thread_other, tsd_offset;
    uint64_t tlv_lo, tlv_hi;      /* absolute addresses of the descriptor array */
    uint64_t *tlv_offset;         /* per descriptor; UINT64_MAX: Python decides */
    /* intercepts */
    uint64_t icpt_addr[MAX_INTERCEPTS];
    int icpt_act[MAX_INTERCEPTS];
    uint64_t icpt_count[MAX_INTERCEPTS];
    /* free-list sites (fm_ui_add_site): resume address instead of the link register */
    uint64_t icpt_resume[MAX_INTERCEPTS];
    uint64_t icpt_pool[MAX_INTERCEPTS];          /* pool record (element size u32 at +0x12C) */
    int icpt_dest[MAX_INTERCEPTS];               /* Unicorn register id of the popped node, -1 none */
    int icpt_nset[MAX_INTERCEPTS];
    int icpt_set_reg[MAX_INTERCEPTS][SITE_SETS];
    uint64_t icpt_set_val[MAX_INTERCEPTS][SITE_SETS];
    int nicpt;
    stub_fn py_intercept;
} accel_t;

static void *reserve(size_t size) {
    void *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    return p == MAP_FAILED ? NULL : p;
}

static inline uint64_t hash_page(uint64_t vpage) {
    vpage *= 0x9E3779B97F4A7C15ull;
    return vpage ^ (vpage >> 29);
}

/* Slot of a copied live page, whatever its generation (-1: absent). */
static inline int64_t find(const accel_t *a, uint64_t vpage) {
    uint64_t i = hash_page(vpage) & a->mask;
    for (;;) {
        uint64_t k = a->keys[i];
        if (k == vpage) return a->vals[i];
        if (k == EMPTY) return -1;
        i = (i + 1) & a->mask;
    }
}

/* Slot of a live page of the current generation, recorded in the running trace (-1: absent or
 * stale; the caller asks Python to read it). */
static inline int64_t use(accel_t *a, uint64_t vpage) {
    int64_t slot = find(a, vpage);
    if (slot < 0 || a->slot_gen[slot] != (uint32_t)a->gen) return -1;
    a->slot_touch[slot] = (uint32_t)a->trace;
    return slot;
}

static inline void mark_read(accel_t *a, uint64_t slot, uint64_t off, uint64_t n) {
    uint64_t first = off >> 3, last = (off + n - 1) >> 3;
    uint64_t *bits = a->rbits + slot * 8;
    for (uint64_t w = first; w <= last && w < 512; w++) bits[w >> 6] |= 1ull << (w & 63);
}

/* Record that [vaddr, vaddr + n) of live memory was read (no effect on VM-private memory). */
static void note_read(accel_t *a, uint64_t vaddr, uint64_t n) {
    while (n) {
        uint64_t off = vaddr & (PAGE - 1), k = PAGE - off;
        if (k > n) k = n;
        uint64_t vpage = vaddr / PAGE;
        int64_t slot;
        if (vpage == a->rc_vpage) slot = a->rc_slot;
        else {
            slot = (vaddr - a->text_lo < a->text_size) ? -1 : find(a, vpage);
            a->rc_vpage = vpage;
            a->rc_slot = slot;
        }
        if (slot >= 0) mark_read(a, (uint64_t)slot, off, k);
        vaddr += k;
        n -= k;
    }
}

static void flush_tlb(accel_t *a) {
    a->ctl(a->uc, a->tlb_flush_code);
    a->tlb_flushes++;
    a->tlb_w = 0;
}

/* ------------------------------------------------------------------ blobs and tracked pages */
static blob_t *blob_new(accel_t *a) {
    if (!a->free_blobs) {
        if (a->nchunks >= a->chunk_cap) {
            uint64_t cap = a->chunk_cap ? a->chunk_cap * 2 : 64;
            void **list = realloc(a->chunks, cap * sizeof(void *));
            if (!list) {
                a->oom = 1;
                return NULL;
            }
            a->chunks = list;
            a->chunk_cap = cap;
        }
        blob_t *chunk = reserve(sizeof(blob_t) * BLOB_CHUNK);
        if (!chunk) {
            a->oom = 1;
            return NULL;
        }
        a->chunks[a->nchunks++] = chunk;
        for (int i = 0; i < BLOB_CHUNK; i++) {
            chunk[i].next = a->free_blobs;
            a->free_blobs = &chunk[i];
        }
    }
    blob_t *b = a->free_blobs;
    a->free_blobs = b->next;
    b->ref = 1;
    a->blobs_live++;
    return b;
}

static inline void blob_drop(accel_t *a, blob_t *b) {
    if (--b->ref == 0) {
        b->next = a->free_blobs;
        a->free_blobs = b;
        a->blobs_live--;
    }
}

static inline uint8_t *cur_page(const accel_t *a, uint64_t t) {
    return t < a->data_slots ? a->data + t * PAGE : a->heap_host + (t - a->data_slots) * PAGE;
}

/* The page as it is without any VM-private store: the copied live bytes, zero for the heap. */
static inline const uint8_t *pristine(const accel_t *a, uint64_t t) {
    if (t >= a->data_slots) return a->zero;
    return a->orig[t] ? a->orig[t]->data : a->data + t * PAGE;
}

static inline void mark_written(accel_t *a, uint64_t t) {
    if (a->wr[t]) return;
    if (t < a->data_slots && !a->orig[t]) {
        blob_t *b = blob_new(a);
        if (!b) return;
        memcpy(b->data, a->data + t * PAGE, PAGE);
        a->orig[t] = b;
    }
    a->wr[t] = 1;
    a->wlist[a->nw++] = (uint32_t)t;
}

static void set_base(accel_t *a, uint64_t t, blob_t *b) {      /* takes over one reference of b */
    if (a->base[t]) blob_drop(a, a->base[t]);
    else {
        a->blist[a->nbase] = (uint32_t)t;
        a->bpos[t] = (uint32_t)++a->nbase;
    }
    a->base[t] = b;
}

static void unbase(accel_t *a, uint64_t t) {
    if (!a->base[t]) return;
    blob_drop(a, a->base[t]);
    a->base[t] = NULL;
    uint32_t i = a->bpos[t] - 1;
    uint32_t last = a->blist[--a->nbase];
    a->blist[i] = last;
    a->bpos[last] = i + 1;
    a->bpos[t] = 0;
}

/* After a commit or restore: pages that only Python stored to never got write access in the
 * TLB and are simply forgotten; up to `sticky` pages keep their write access (and stay in the
 * list, so the next commit/restore looks at them again); beyond that the TLB is flushed. */
static void settle(accel_t *a) {
    if (a->tlb_w && a->nw <= a->sticky) return;
    for (uint64_t i = 0; i < a->nw; i++) a->wr[a->wlist[i]] = 0;
    a->nw = 0;
    if (a->tlb_w) flush_tlb(a);
}

/* Snapshot the VM-private state (every tracked page that differs from pristine). */
snapshot_t *fm_ui_commit(accel_t *a) {
    for (uint64_t i = 0; i < a->nw; i++) {
        uint64_t t = a->wlist[i];
        const uint8_t *c = cur_page(a, t);
        const uint8_t *b = a->base[t] ? a->base[t]->data : pristine(a, t);
        if (c != b && memcmp(c, b, PAGE) != 0) {
            blob_t *n = blob_new(a);
            if (!n) return NULL;
            memcpy(n->data, c, PAGE);
            set_base(a, t, n);
            a->pages_committed++;
        }
    }
    snapshot_t *s = malloc(sizeof(*s));
    if (!s) {
        a->oom = 1;
        return NULL;
    }
    s->n = a->nbase;
    s->e = malloc((a->nbase ? a->nbase : 1) * sizeof(snap_entry));
    if (!s->e) {
        free(s);
        a->oom = 1;
        return NULL;
    }
    for (uint64_t i = 0; i < a->nbase; i++) {
        uint32_t t = a->blist[i];
        s->e[i].page = t;
        s->e[i].blob = a->base[t];
        a->base[t]->ref++;
    }
    s->serial = ++a->serial;
    s->data_epoch = a->data_epoch;
    a->current_serial = s->serial;
    a->commits++;
    settle(a);
    a->ndirty = a->nw;
    return s;
}

/* Return to a snapshot (NULL: pristine). 0 ok, -1 the snapshot predates an invalidation. */
int fm_ui_restore(accel_t *a, const snapshot_t *target) {
    uint64_t want = target ? target->serial : 0;
    if (target && target->data_epoch != a->data_epoch) return -1;
    a->restores++;
    if (want != a->current_serial) {
        uint32_t epoch = ++a->mark_epoch;
        if (target) {
            for (uint64_t i = 0; i < target->n; i++) {
                uint32_t t = target->e[i].page;
                blob_t *b = target->e[i].blob;
                a->mark[t] = epoch;
                if (a->base[t] != b) {
                    memcpy(cur_page(a, t), b->data, PAGE);
                    b->ref++;
                    set_base(a, t, b);
                    a->pages_restored++;
                }
            }
        }
        for (uint64_t i = a->nbase; i-- > 0;) {
            uint32_t t = a->blist[i];
            if (a->mark[t] != epoch) {
                const uint8_t *p = pristine(a, t);
                if (p != cur_page(a, t)) memcpy(cur_page(a, t), p, PAGE);
                unbase(a, t);
                a->pages_restored++;
            }
        }
        a->current_serial = want;
    }
    for (uint64_t i = 0; i < a->nw; i++) {
        uint64_t t = a->wlist[i];
        const uint8_t *src = a->base[t] ? a->base[t]->data : pristine(a, t);
        if (src != cur_page(a, t)) memcpy(cur_page(a, t), src, PAGE);
    }
    a->pages_restored += a->nw;
    settle(a);
    a->ndirty = a->nw;
    return 0;
}

/* Free a snapshot. `a` is NULL when the instance is gone already (its blobs went with it). */
void fm_ui_release(accel_t *a, snapshot_t *s) {
    if (!s) return;
    if (a)
        for (uint64_t i = 0; i < s->n; i++) blob_drop(a, s->e[i].blob);
    free(s->e);
    free(s);
}

/* ------------------------------------------------------------------ watched pages
 * A watched live page is entered in the TLB at an address inside an I/O region (mapped by
 * Python with uc_mmio_map over these two callbacks), so each load and store of emulated code
 * on it arrives here with its exact offset and size; all other pages keep the direct path.
 * Used for the few pages the running game keeps changing: their read set is kept per 8-byte
 * word instead of per page. */
uint64_t fm_ui_watch_read(uc_engine *uc, uint64_t offset, unsigned size, void *user) {
    (void)uc;
    accel_t *a = user;
    uint64_t slot = offset / PAGE, value = 0;
    a->watch_hits++;
    if (slot >= a->data_used || size > 8) return 0;
    mark_read(a, slot, offset & (PAGE - 1), size);
    a->slot_touch[slot] = (uint32_t)a->trace;
    memcpy(&value, a->data + offset, size);
    if (a->dbg_addr && a->slot_vpage[slot] * PAGE + ((offset & (PAGE - 1)) & ~7ull) == a->dbg_addr && a->dbg_n < 32) {
        uint64_t pc = 0, lr = 0;
        void *ptrs[2] = {&pc, &lr};
        a->reg_read_batch(a->uc, a->out_regs, ptrs, 2);
        a->dbg_pc[a->dbg_n] = pc;
        a->dbg_lr[a->dbg_n++] = lr;
    }
    return value;
}

void fm_ui_watch_write(uc_engine *uc, uint64_t offset, unsigned size, uint64_t value, void *user) {
    (void)uc;
    accel_t *a = user;
    uint64_t slot = offset / PAGE;
    a->watch_hits++;
    if (slot >= a->data_used || size > 8) return;
    mark_written(a, slot);
    memcpy(a->data + offset, &value, size);
}

void fm_ui_set_watch_base(accel_t *a, uint64_t watch_phys) { a->watch_phys = watch_phys; }

/* Diagnostics: record pc and lr of the next loads of the watched 8-byte word at vaddr. */
void fm_ui_debug_word(accel_t *a, uint64_t vaddr) {
    a->dbg_addr = vaddr & ~7ull;
    a->dbg_n = 0;
}

uint64_t fm_ui_debug_hits(const accel_t *a, uint64_t *pcs, uint64_t *lrs) {
    memcpy(pcs, a->dbg_pc, sizeof(a->dbg_pc));
    memcpy(lrs, a->dbg_lr, sizeof(a->dbg_lr));
    return a->dbg_n;
}

/* Watch exactly the given live pages (absent ones are skipped); returns how many are watched. */
uint64_t fm_ui_watch(accel_t *a, const uint64_t *vaddrs, uint64_t n) {
    if (a->nwatch) memset(a->watch, 0, a->data_slots);
    a->nwatch = 0;
    for (uint64_t i = 0; i < n; i++) {
        int64_t slot = find(a, vaddrs[i] / PAGE);
        if (slot >= 0 && !a->watch[slot]) {
            a->watch[slot] = 1;
            a->nwatch++;
        }
    }
    flush_tlb(a);
    return a->nwatch;
}

/* Watch one more page (just copied, so not in the TLB yet). */
void fm_ui_watch_add(accel_t *a, uint64_t vaddr) {
    int64_t slot = find(a, vaddr / PAGE);
    if (slot >= 0 && !a->watch[slot]) {
        a->watch[slot] = 1;
        a->nwatch++;
    }
}

/* ------------------------------------------------------------------ construction */
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
    a->heap_range = -1;
    a->gen = 1;
    a->trace = 1;
    a->sticky = 16;
    a->log_externals = 0;
    uint64_t cap = 1;
    while (cap < data_slots * 2) cap <<= 1;
    a->mask = cap - 1;
    a->code = reserve(a->text_size);
    a->code_present = calloc(a->text_size / PAGE, 1);
    a->data = reserve(data_slots * PAGE);
    a->slot_vpage = malloc(data_slots * sizeof(uint64_t));
    a->slot_gen = calloc(data_slots, sizeof(uint32_t));
    a->slot_touch = calloc(data_slots, sizeof(uint32_t));
    a->keys = malloc(cap * sizeof(uint64_t));
    a->vals = malloc(cap * sizeof(uint32_t));
    a->zero = reserve(PAGE);
    a->rbits = reserve(data_slots * 8 * sizeof(uint64_t));
    a->rc_vpage = EMPTY;
    a->watch = calloc(data_slots, 1);
    if (!a->rbits || !a->watch) return NULL;
    if (!a->code || !a->code_present || !a->data || !a->slot_vpage || !a->slot_gen || !a->slot_touch ||
        !a->keys || !a->vals || !a->zero)
        return NULL;
    memset(a->keys, 0xFF, cap * sizeof(uint64_t));
    return a;
}

/* Called once, after the private ranges exist: the heap range becomes tracked. */
int fm_ui_setup(accel_t *a, uint64_t heap_lo) {
    for (int i = 0; i < a->nranges; i++)
        if (a->ranges[i].lo == heap_lo) a->heap_range = i;
    if (a->heap_range < 0) return -1;
    range_t *r = &a->ranges[a->heap_range];
    a->heap_lo = r->lo;
    a->heap_hi = r->hi;
    a->heap_top = r->lo;
    a->heap_host = r->host;
    a->heap_pages = (r->hi - r->lo) / PAGE;
    a->ntracked = a->data_slots + a->heap_pages;
    a->orig = calloc(a->ntracked, sizeof(blob_t *));
    a->base = calloc(a->ntracked, sizeof(blob_t *));
    a->wr = calloc(a->ntracked, 1);
    a->wlist = malloc(a->ntracked * sizeof(uint32_t));
    a->blist = malloc(a->ntracked * sizeof(uint32_t));
    a->bpos = calloc(a->ntracked, sizeof(uint32_t));
    a->mark = calloc(a->ntracked, sizeof(uint32_t));
    a->alloc_cap = 1 << 16;
    a->alloc_addr = malloc(a->alloc_cap * sizeof(uint64_t));
    a->alloc_size = malloc(a->alloc_cap * sizeof(uint64_t));
    if (!a->orig || !a->base || !a->wr || !a->wlist || !a->blist || !a->bpos || !a->mark || !a->alloc_addr ||
        !a->alloc_size)
        return -1;
    return 0;
}

void fm_accel_free(accel_t *a) {
    if (!a) return;
    munmap(a->code, a->text_size);
    munmap(a->data, a->data_slots * PAGE);
    for (int i = 0; i < a->nranges; i++)
        if (a->ranges[i].host) munmap(a->ranges[i].host, a->ranges[i].hi - a->ranges[i].lo);
    for (uint64_t i = 0; i < a->nchunks; i++) munmap(a->chunks[i], sizeof(blob_t) * BLOB_CHUNK);
    free(a->chunks);
    munmap(a->zero, PAGE);
    munmap(a->rbits, a->data_slots * 8 * sizeof(uint64_t));
    free(a->watch);
    free(a->code_present);
    free(a->slot_vpage);
    free(a->slot_gen);
    free(a->slot_touch);
    free(a->keys);
    free(a->vals);
    free(a->orig);
    free(a->base);
    free(a->wr);
    free(a->wlist);
    free(a->blist);
    free(a->bpos);
    free(a->mark);
    free(a->alloc_addr);
    free(a->alloc_size);
    free(a->tlv_offset);
    free(a->stub_id);
    free(a);
}

uint8_t *fm_accel_code_host(accel_t *a) { return a->code; }
uint8_t *fm_accel_data_host(accel_t *a) { return a->data; }

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

/* Add a copied live page, or bring a page of an older generation up to date. Returns the slot,
 * -1 when the pool is full, -2 when the page is already present in this generation, -3 when a
 * stale page still carries VM-private stores (the caller must restore to pristine first). */
int64_t fm_accel_add_data(accel_t *a, uint64_t vaddr, const uint8_t *bytes) {
    uint64_t vpage = vaddr / PAGE;
    int64_t have = find(a, vpage);
    if (have >= 0) {
        if (a->slot_gen[have] == (uint32_t)a->gen) return -2;
        if (a->base[have]) return -3;
        memcpy(a->data + (uint64_t)have * PAGE, bytes, PAGE);
        if (a->orig[have]) memcpy(a->orig[have]->data, bytes, PAGE);
        a->slot_gen[have] = (uint32_t)a->gen;
        return have;
    }
    if (a->data_used >= a->data_slots) return -1;
    uint64_t slot = a->data_used++;
    a->rc_vpage = EMPTY;
    memset(a->rbits + slot * 8, 0, 8 * sizeof(uint64_t));
    memcpy(a->data + slot * PAGE, bytes, PAGE);
    a->slot_vpage[slot] = vpage;
    a->slot_gen[slot] = (uint32_t)a->gen;
    a->slot_touch[slot] = 0;
    uint64_t i = hash_page(vpage) & a->mask;
    while (a->keys[i] != EMPTY) i = (i + 1) & a->mask;
    a->keys[i] = vpage;
    a->vals[i] = (uint32_t)slot;
    a->new_pages++;
    return (int64_t)slot;
}

/* 0 absent, 1 data of this generation, 2 code (present), 3 private, 4 data of an older generation. */
int fm_accel_has(const accel_t *a, uint64_t vaddr) {
    if (vaddr - a->text_lo < a->text_size) return a->code_present[(vaddr - a->text_lo) / PAGE] ? 2 : 0;
    for (int i = 0; i < a->nranges; i++)
        if (vaddr >= a->ranges[i].lo && vaddr < a->ranges[i].hi) return 3;
    int64_t slot = find(a, vaddr / PAGE);
    if (slot < 0) return 0;
    return a->slot_gen[slot] == (uint32_t)a->gen ? 1 : 4;
}

void fm_accel_restore(accel_t *a) { fm_ui_restore(a, NULL); }

/* Forget every copied live page (the code pool and the private ranges stay). The caller has
 * restored to pristine; snapshots taken before are refused afterwards. */
void fm_accel_reset_data(accel_t *a) {
    fm_ui_restore(a, NULL);
    for (uint64_t i = 0; i < a->nw; i++) a->wr[a->wlist[i]] = 0;
    a->nw = 0;
    for (uint64_t t = 0; t < a->data_used; t++)
        if (a->orig[t]) {
            blob_drop(a, a->orig[t]);
            a->orig[t] = NULL;
        }
    a->data_used = 0;
    if (a->nwatch) memset(a->watch, 0, a->data_slots);
    a->nwatch = 0;
    a->rc_vpage = EMPTY;
    a->data_epoch++;
    memset(a->keys, 0xFF, (a->mask + 1) * sizeof(uint64_t));
    flush_tlb(a);
}

/* A new generation: every copied live page is stale until Python reads it again. */
void fm_ui_new_generation(accel_t *a) {
    fm_ui_restore(a, NULL);
    for (uint64_t i = 0; i < a->nw; i++) a->wr[a->wlist[i]] = 0;
    a->nw = 0;
    a->gen++;
    flush_tlb(a);
}

/* Start a trace: pages touched from now on are listed by fm_ui_trace_collect; with `words`
 * every read of live memory is also recorded per 8-byte word (fm_ui_trace_masks). */
void fm_ui_trace_begin(accel_t *a, int words) {
    a->trace++;
    a->rtrack = words;
    if (words) memset(a->rbits, 0, a->data_used * 8 * sizeof(uint64_t));
    flush_tlb(a);
}

void fm_ui_trace_end(accel_t *a) { a->rtrack = 0; }

/* The read words of the given live pages (8 x u64 each; all zero for an absent page). */
void fm_ui_trace_masks(const accel_t *a, const uint64_t *vaddrs, uint64_t n, uint64_t *out) {
    for (uint64_t i = 0; i < n; i++) {
        int64_t slot = find(a, vaddrs[i] / PAGE);
        if (slot < 0) memset(out + i * 8, 0, 64);
        else memcpy(out + i * 8, a->rbits + (uint64_t)slot * 8, 64);
    }
}

/* Addresses of the live pages touched since fm_ui_trace_begin (up to cap); returns the count. */
uint64_t fm_ui_trace_collect(const accel_t *a, uint64_t *out, uint64_t cap) {
    uint64_t n = 0;
    for (uint64_t t = 0; t < a->data_used; t++)
        if (a->slot_touch[t] == (uint32_t)a->trace) {
            if (n < cap) out[n] = a->slot_vpage[t] * PAGE;
            n++;
        }
    return n;
}

static inline uint64_t hash_masked(const uint8_t *p, const uint64_t *mask) {
    uint64_t h = 0x243F6A8885A308D3ull;
    for (uint64_t g = 0; g < 8; g++) {
        uint64_t bits = mask[g];
        while (bits) {
            uint64_t w = g * 64 + (uint64_t)__builtin_ctzll(bits), v;
            bits &= bits - 1;
            memcpy(&v, p + w * 8, 8);
            h = (h ^ v ^ (w << 52)) * 0x9E3779B97F4A7C15ull;
            h ^= h >> 29;
        }
    }
    h *= 0xBF58476D1CE4E5B9ull;
    return h ^ (h >> 32);
}

/* Fingerprints of the masked words of n consecutive pages in buf (masks: 8 x u64 per page). */
void fm_ui_hash_masked(const uint8_t *buf, const uint64_t *masks, uint64_t n, uint64_t *out) {
    for (uint64_t i = 0; i < n; i++) out[i] = hash_masked(buf + i * PAGE, masks + i * 8);
}

/* The same over the copied (pristine) bytes of live pages; 0 marks an absent page. */
void fm_ui_hash_live_masked(const accel_t *a, const uint64_t *vaddrs, const uint64_t *masks, uint64_t n,
                            uint64_t *out) {
    for (uint64_t i = 0; i < n; i++) {
        int64_t slot = find(a, vaddrs[i] / PAGE);
        out[i] = slot < 0 ? 0 : hash_masked(pristine(a, (uint64_t)slot), masks + i * 8);
    }
}

static inline uint64_t hash_bytes(const uint8_t *p) {
    uint64_t h = 0x243F6A8885A308D3ull;
    for (uint64_t i = 0; i < PAGE; i += 8) {
        uint64_t w;
        memcpy(&w, p + i, 8);
        h = (h ^ w) * 0x9E3779B97F4A7C15ull;
        h ^= h >> 29;
    }
    h *= 0xBF58476D1CE4E5B9ull;
    return h ^ (h >> 32);
}

/* 64-bit fingerprints of n consecutive 4 KiB pages in buf. */
void fm_ui_hash_pages(const uint8_t *buf, uint64_t n, uint64_t *out) {
    for (uint64_t i = 0; i < n; i++) out[i] = hash_bytes(buf + i * PAGE);
}

/* Fingerprints of the copied (pristine) bytes of the given live pages; 0 marks an absent page. */
void fm_ui_hash_live(const accel_t *a, const uint64_t *vaddrs, uint64_t n, uint64_t *out) {
    for (uint64_t i = 0; i < n; i++) {
        int64_t slot = find(a, vaddrs[i] / PAGE);
        out[i] = slot < 0 ? 0 : hash_bytes(pristine(a, (uint64_t)slot));
    }
}

/* The pristine bytes of one copied live page (as the game had them when read). 0 ok, 1 absent. */
int fm_ui_live_page(accel_t *a, uint64_t vaddr, uint8_t *dst, uint64_t lo, uint64_t hi) {
    vaddr &= VPAGE_MASK;
    if (vaddr - a->text_lo < a->text_size) {
        if (!a->code_present[(vaddr - a->text_lo) / PAGE]) {
            a->miss_addr = vaddr;
            return PEEK_MISSING;
        }
        memcpy(dst, a->code + (vaddr - a->text_lo), PAGE);
        return PEEK_OK;
    }
    int64_t slot = use(a, vaddr / PAGE);
    if (slot < 0) {
        a->miss_addr = vaddr;
        return PEEK_MISSING;
    }
    memcpy(dst, pristine(a, (uint64_t)slot), PAGE);
    if (a->rtrack && hi > lo) mark_read(a, (uint64_t)slot, lo, hi - lo);
    return PEEK_OK;
}

/* ------------------------------------------------------------------ guest memory access */
/* Host address of a readable guest byte, or NULL (absent, stale). */
static inline uint8_t *g_read(accel_t *a, uint64_t vaddr) {
    if (vaddr - a->text_lo < a->text_size)
        return a->code_present[(vaddr - a->text_lo) / PAGE] ? a->code + (vaddr - a->text_lo) : NULL;
    if (vaddr - a->heap_lo < a->heap_hi - a->heap_lo) return a->heap_host + (vaddr - a->heap_lo);
    for (int i = 0; i < a->nranges; i++)
        if (vaddr >= a->ranges[i].lo && vaddr < a->ranges[i].hi) return a->ranges[i].host + (vaddr - a->ranges[i].lo);
    int64_t slot = use(a, vaddr / PAGE);
    return slot < 0 ? NULL : a->data + (uint64_t)slot * PAGE + (vaddr & (PAGE - 1));
}

/* Host address of a writable guest byte, or NULL (code, protected, absent, stale). With `mark`
 * the page joins the written set (copy-on-write for live pages). */
static inline uint8_t *g_write(accel_t *a, uint64_t vaddr, int mark) {
    if (vaddr - a->text_lo < a->text_size) return NULL;
    if (vaddr - a->heap_lo < a->heap_hi - a->heap_lo) {
        if (mark) mark_written(a, a->data_slots + (vaddr - a->heap_lo) / PAGE);
        return a->heap_host + (vaddr - a->heap_lo);
    }
    for (int i = 0; i < a->nranges; i++)
        if (vaddr >= a->ranges[i].lo && vaddr < a->ranges[i].hi)
            return (a->ranges[i].perms & P_W) ? a->ranges[i].host + (vaddr - a->ranges[i].lo) : NULL;
    int64_t slot = use(a, vaddr / PAGE);
    if (slot < 0) return NULL;
    if (mark) mark_written(a, (uint64_t)slot);
    return a->data + (uint64_t)slot * PAGE + (vaddr & (PAGE - 1));
}

static bool readable(accel_t *a, uint64_t vaddr, uint64_t n) {
    if (!n) return true;
    for (uint64_t p = vaddr & VPAGE_MASK; p < vaddr + n; p += PAGE)
        if (!g_read(a, p)) return false;
    return true;
}

static bool writable(accel_t *a, uint64_t vaddr, uint64_t n) {
    if (!n) return true;
    for (uint64_t p = vaddr & VPAGE_MASK; p < vaddr + n; p += PAGE)
        if (!g_write(a, p, 0)) return false;
    return true;
}

static void copy_out(accel_t *a, uint64_t vaddr, uint8_t *dst, uint64_t n) {     /* after readable() */
    if (a->rtrack) note_read(a, vaddr, n);
    while (n) {
        uint64_t k = PAGE - (vaddr & (PAGE - 1));
        if (k > n) k = n;
        memcpy(dst, g_read(a, vaddr), k);
        dst += k;
        vaddr += k;
        n -= k;
    }
}

static void copy_in(accel_t *a, uint64_t vaddr, const uint8_t *src, uint64_t n) { /* after writable() */
    while (n) {
        uint64_t k = PAGE - (vaddr & (PAGE - 1));
        if (k > n) k = n;
        memcpy(g_write(a, vaddr, 1), src, k);
        src += k;
        vaddr += k;
        n -= k;
    }
}

static void fill(accel_t *a, uint64_t vaddr, int c, uint64_t n) {
    while (n) {
        uint64_t k = PAGE - (vaddr & (PAGE - 1));
        if (k > n) k = n;
        memset(g_write(a, vaddr, 1), c, k);
        vaddr += k;
        n -= k;
    }
}

static inline bool peek(accel_t *a, uint64_t vaddr, void *dst, uint64_t n) {
    if (!readable(a, vaddr, n)) return false;
    copy_out(a, vaddr, dst, n);
    return true;
}

/* Copy guest memory out. PEEK_MISSING leaves the first absent address in miss_addr. */
int fm_accel_peek(accel_t *a, uint64_t vaddr, uint8_t *dst, uint64_t length) {
    uint64_t first = vaddr, total = length;
    while (length) {
        uint8_t *host = g_read(a, vaddr);
        if (!host) {
            a->miss_addr = vaddr;
            return PEEK_MISSING;
        }
        uint64_t n = PAGE - (vaddr & (PAGE - 1));
        if (n > length) n = length;
        memcpy(dst, host, n);
        dst += n;
        vaddr += n;
        length -= n;
    }
    if (a->rtrack) note_read(a, first, total);
    return PEEK_OK;
}

/* Copy into guest memory. With copy_on_write the pages join the written set (undone by a
 * restore, kept by a commit); without it the bytes are part of pristine memory for the session
 * (overlays). Code is refused. A refused poke changes nothing. */
int fm_accel_poke(accel_t *a, uint64_t vaddr, const uint8_t *src, uint64_t length, int copy_on_write) {
    uint64_t at = vaddr, left = length;
    while (left) {
        if (at - a->text_lo < a->text_size) {
            a->miss_addr = at;
            return PEEK_CODE;
        }
        if (!g_write(a, at, 0)) {
            a->miss_addr = at;
            return PEEK_MISSING;
        }
        uint64_t n = PAGE - (at & (PAGE - 1));
        if (n > left) n = left;
        at += n;
        left -= n;
    }
    if (copy_on_write) {
        copy_in(a, vaddr, src, length);
        return PEEK_OK;
    }
    while (length) {
        uint64_t off = vaddr & (PAGE - 1);
        uint64_t n = PAGE - off;
        if (n > length) n = length;
        memcpy(g_write(a, vaddr, 0), src, n);
        if (!(vaddr - a->heap_lo < a->heap_hi - a->heap_lo)) {
            int64_t slot = find(a, vaddr / PAGE);
            bool private_range = false;
            for (int i = 0; i < a->nranges; i++)
                if (vaddr >= a->ranges[i].lo && vaddr < a->ranges[i].hi) private_range = true;
            if (!private_range && slot >= 0) {
                if (a->orig[slot]) memcpy(a->orig[slot]->data + off, src, n);
                if (a->base[slot]) memcpy(a->base[slot]->data + off, src, n);
            }
        }
        src += n;
        vaddr += n;
        length -= n;
    }
    return PEEK_OK;
}

/* ------------------------------------------------------------------ allocations */
static uint64_t heap_alloc(accel_t *a, uint64_t size, uint64_t align) {
    if (!size) size = 1;
    if (!align || align > (1ull << 30)) return 0;
    uint64_t top = (a->heap_top + align - 1) & ~(align - 1);
    if (top > a->heap_hi || size > a->heap_hi - top) return 0;
    if (a->nalloc >= a->alloc_cap) {
        uint64_t cap = a->alloc_cap * 2;
        uint64_t *addr = realloc(a->alloc_addr, cap * sizeof(uint64_t));
        if (!addr) return 0;
        a->alloc_addr = addr;
        uint64_t *sz = realloc(a->alloc_size, cap * sizeof(uint64_t));
        if (!sz) return 0;
        a->alloc_size = sz;
        a->alloc_cap = cap;
    }
    a->alloc_addr[a->nalloc] = top;
    a->alloc_size[a->nalloc] = size;
    a->nalloc++;
    a->heap_top = top + size;
    return top;
}

/* Python's vm.alloc(): 0 when the heap is exhausted. */
uint64_t fm_ui_alloc(accel_t *a, uint64_t size, uint64_t align) { return heap_alloc(a, size, align); }

/* Size of the allocation that starts at address (UINT64_MAX: none). */
uint64_t fm_ui_alloc_size(const accel_t *a, uint64_t address) {
    uint64_t lo = 0, hi = a->nalloc;
    while (lo < hi) {
        uint64_t mid = (lo + hi) / 2;
        if (a->alloc_addr[mid] < address) lo = mid + 1;
        else hi = mid;
    }
    return lo < a->nalloc && a->alloc_addr[lo] == address ? a->alloc_size[lo] : UINT64_MAX;
}

/* ------------------------------------------------------------------ externals */
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

/* Owner-thread model (thread='owner'): where the game keeps its thread identity and how dyld
 * finds a thread-local variable. offsets[i] is the block offset of descriptor i (from the
 * on-disk image); UINT64_MAX leaves the descriptor to Python (the RNG state). */
int fm_ui_set_owner_thread(accel_t *a, uint64_t flag, uint64_t main_ptr, uint64_t other_ptr, uint64_t tsd_offset,
                           uint64_t tlv_lo, uint64_t tlv_hi, const uint64_t *offsets) {
    uint64_t n = (tlv_hi - tlv_lo) / 24;
    a->tlv_offset = malloc((n ? n : 1) * sizeof(uint64_t));
    if (!a->tlv_offset) return -1;
    memcpy(a->tlv_offset, offsets, n * sizeof(uint64_t));
    a->thread_flag = flag;
    a->thread_main = main_ptr;
    a->thread_other = other_ptr;
    a->tsd_offset = tsd_offset;
    a->tlv_lo = tlv_lo;
    a->tlv_hi = tlv_hi;
    a->owner_thread = 1;
    return 0;
}

static uint64_t get_reg(accel_t *a, int reg) {
    uint64_t value = 0;
    void *ptr = &value;
    a->reg_read_batch(a->uc, &reg, &ptr, 1);
    return value;
}

static void get_args(accel_t *a, uint64_t *x, int n) {
    void *ptrs[4] = {&x[0], &x[1], &x[2], &x[3]};
    a->reg_read_batch(a->uc, a->regs, ptrs, n);
}

static void set_reg(accel_t *a, int reg, uint64_t value) {
    a->reg_write(a->uc, reg, &value);      /* uc_reg_write: a PC write ends the current block */
}

/* Length of the C string at vaddr the way the Python model reads it (64-byte chunks, every
 * chunk fully readable); UINT64_MAX: Python decides. */
static uint64_t c_strlen(accel_t *a, uint64_t vaddr, uint64_t limit, uint64_t chunk_cap) {
    uint64_t len = 0;
    uint8_t chunk[64];
    while (len < limit) {
        uint64_t want = 64;
        if (chunk_cap && limit - len < want) want = limit - len;
        if (!peek(a, vaddr + len, chunk, want)) return UINT64_MAX;
        const uint8_t *nul = memchr(chunk, 0, want);
        if (nul) return len + (uint64_t)(nul - chunk);
        len += want;
    }
    return chunk_cap ? limit : UINT64_MAX;
}

static int compare_guest(accel_t *a, uint64_t x, uint64_t nx, uint64_t y, uint64_t ny) {
    uint64_t n = nx < ny ? nx : ny;
    if (a->rtrack) {
        note_read(a, x, nx);
        note_read(a, y, ny);
    }
    while (n) {
        uint64_t k = PAGE - (x & (PAGE - 1)), j = PAGE - (y & (PAGE - 1));
        if (k > j) k = j;
        if (k > n) k = n;
        int c = memcmp(g_read(a, x), g_read(a, y), k);
        if (c) return c < 0 ? -1 : 1;
        x += k;
        y += k;
        n -= k;
    }
    return nx == ny ? 0 : (nx < ny ? -1 : 1);
}

static bool owner_pthread(accel_t *a, uint64_t *out) {
    uint8_t flag;
    if (!a->owner_thread || !peek(a, a->thread_flag, &flag, 1)) return false;
    return peek(a, flag == 1 ? a->thread_main : a->thread_other, out, 8);
}

static bool pool_alloc(accel_t *a, int action, const uint64_t *x, uint64_t *result) {
    if (action == ACT_POOL_FREE) {
        *result = 0;
        return true;
    }
    uint32_t word;
    if (action == ACT_FIXED_POOL_ALLOC || action == ACT_POOL_GET) {
        /* 0x4356EB8: element size u32 at pool+0x38; 0x43569F8: element size u32 at pool+0x12C */
        uint64_t at = x[0] + (action == ACT_POOL_GET ? 0x12C : 0x38);
        if (!peek(a, at, &word, 4) || word == 0 || word > 0x100000) return false;
        uint64_t block = heap_alloc(a, word, 16);
        if (!block) return false;
        fill(a, block, 0, word);
        *result = block;
        return true;
    }
    uint64_t size = x[1] & 0xFFFFFFFFull;
    if (!peek(a, x[0] + 0x30, &word, 4) || word > 64 || size > 0x4000000) return false;
    uint64_t block = heap_alloc(a, size + word, 16);
    if (!block) return false;
    if (size + word) fill(a, block, 0, size + word);
    if (word) {
        uint32_t stored = (uint32_t)size;
        copy_in(a, block, (const uint8_t *)&stored, 4);
    }
    *result = block + word;
    return true;
}

/* Run the model of `action`. False: nothing was changed and Python runs its own model. */
static bool run_native(accel_t *a, int action) {
    uint64_t x[4] = {0, 0, 0, 0}, result = 0;
    bool set = false;
    switch (action) {
    case ACT_RETURN_0:
        set = true;
        break;
    case ACT_RETURN_1:
        result = 1;
        set = true;
        break;
    case ACT_MEMCPY: {
        get_args(a, x, 3);
        uint64_t n = x[2];
        if (n > COPY_LIMIT) return false;
        if (n) {
            if (!readable(a, x[1], n) || !writable(a, x[0], n)) return false;
            if (n <= 256) {
                uint8_t tmp[256];
                copy_out(a, x[1], tmp, n);
                copy_in(a, x[0], tmp, n);
            } else {
                uint8_t *tmp = malloc(n);
                if (!tmp) return false;
                copy_out(a, x[1], tmp, n);
                copy_in(a, x[0], tmp, n);
                free(tmp);
            }
        }
        break;                               /* x0 already holds dst */
    }
    case ACT_MEMSET:
        get_args(a, x, 3);
        if (x[2] > COPY_LIMIT || !writable(a, x[0], x[2])) return false;
        fill(a, x[0], (int)(x[1] & 0xFF), x[2]);
        break;
    case ACT_BZERO:
        get_args(a, x, 2);
        if (x[1] > COPY_LIMIT || !writable(a, x[0], x[1])) return false;
        fill(a, x[0], 0, x[1]);
        break;
    case ACT_STRLEN:
        get_args(a, x, 1);
        result = c_strlen(a, x[0], STRING_LIMIT, 0);
        if (result == UINT64_MAX) return false;
        set = true;
        break;
    case ACT_STRCMP: {
        get_args(a, x, 2);
        uint64_t nx = c_strlen(a, x[0], STRING_LIMIT, 0);
        if (nx == UINT64_MAX) return false;
        uint64_t ny = c_strlen(a, x[1], STRING_LIMIT, 0);
        if (ny == UINT64_MAX) return false;
        result = (uint64_t)(int64_t)compare_guest(a, x[0], nx, x[1], ny);
        set = true;
        break;
    }
    case ACT_STRNCMP: {
        get_args(a, x, 3);
        if (x[2] > STRING_LIMIT) return false;
        uint64_t nx = x[2] ? c_strlen(a, x[0], x[2], 1) : 0;
        if (nx == UINT64_MAX) return false;
        uint64_t ny = x[2] ? c_strlen(a, x[1], x[2], 1) : 0;
        if (ny == UINT64_MAX) return false;
        result = (uint64_t)(int64_t)compare_guest(a, x[0], nx, x[1], ny);
        set = true;
        break;
    }
    case ACT_MEMCMP:
        get_args(a, x, 3);
        if (x[2] > COPY_LIMIT || !readable(a, x[0], x[2]) || !readable(a, x[1], x[2])) return false;
        result = (uint64_t)(int64_t)compare_guest(a, x[0], x[2], x[1], x[2]);
        set = true;
        break;
    case ACT_MALLOC:
        get_args(a, x, 1);
        result = heap_alloc(a, x[0], 16);
        if (!result) return false;
        set = true;
        break;
    case ACT_CALLOC:
        get_args(a, x, 2);
        if (x[1] && x[0] > UINT64_MAX / x[1]) return false;
        result = heap_alloc(a, x[0] * x[1], 16);
        if (!result) return false;
        set = true;
        break;
    case ACT_ALIGNED_NEW: {
        get_args(a, x, 2);
        uint64_t align = x[1] < 16 ? 16 : x[1];
        if (align & (align - 1)) return false;
        result = heap_alloc(a, x[0], align);
        if (!result) return false;
        set = true;
        break;
    }
    case ACT_PTHREAD_SELF:
        if (!owner_pthread(a, &result)) return false;
        set = true;
        break;
    case ACT_PTHREAD_EQUAL:
        get_args(a, x, 2);
        result = x[0] == x[1];
        set = true;
        break;
    case ACT_TLV: {
        get_args(a, x, 1);
        uint64_t desc = x[0];
        if (!a->owner_thread || desc < a->tlv_lo || desc >= a->tlv_hi || (desc - a->tlv_lo) % 24) return false;
        uint64_t offset = a->tlv_offset[(desc - a->tlv_lo) / 24];
        uint64_t word, owner, self, block;
        if (offset == UINT64_MAX || !peek(a, desc + 8, &word, 8) || (word >> 32) != offset) return false;
        uint64_t key = word & 0xFFFFFFFFull;
        if (!owner_pthread(a, &owner) || !peek(a, owner + a->tsd_offset, &self, 8) || self != owner) return false;
        if (key == 0 || key >= 1024 || !peek(a, owner + a->tsd_offset + 8 * key, &block, 8)) return false;
        if (block < 0x100000000ull) return false;
        result = block + offset;
        set = true;
        break;
    }
    case ACT_POOL_ALLOC:
    case ACT_POOL_FREE:
    case ACT_FIXED_POOL_ALLOC:
    case ACT_POOL_GET:
        get_args(a, x, 2);
        if (!pool_alloc(a, action, x, &result)) return false;
        set = true;
        break;
    default:
        return false;
    }
    if (set) set_reg(a, a->reg_x0, result);
    return true;
}

/* Run the model of import `id` when it has one here. False: Python's turn. */
static bool native_external(accel_t *a, uint32_t id) {
    int action = a->act[id];
    if (action == ACT_PYTHON) return false;
    if (a->log_externals && a->ext_n >= EXT_LOG_MAX) return false;
    if (action == ACT_STACK_PROBE) {
        uint64_t frame = get_reg(a, a->reg_x9);
        if (frame > a->probe_limit) {
            if (!a->stop) {
                a->stop = STOP_STACK_PROBE;
                a->stop_addr = frame;
            }
            a->emu_stop(a->uc);
        }
    } else if (!run_native(a, action)) {
        a->declined++;
        return false;
    }
    a->ext_count[id]++;
    a->native_calls++;
    if (a->log_externals) a->ext_log[a->ext_n++] = (uint16_t)id;
    return true;
}

/* Per-import counts of the calls handled here since the last call; clears them. */
uint64_t fm_ui_ext_counts(accel_t *a, uint32_t *ids, uint32_t *counts, uint64_t cap) {
    uint64_t n = 0;
    for (uint32_t id = 0; id < MAX_IMPORTS && n < cap; id++)
        if (a->ext_count[id]) {
            ids[n] = id;
            counts[n] = a->ext_count[id];
            a->ext_count[id] = 0;
            n++;
        }
    a->native_calls = 0;
    return n;
}

void fm_ui_log_externals(accel_t *a, int on) { a->log_externals = on; }

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

/* Shipped functions replaced by a model (the game's pool allocator): UC_HOOK_CODE on each entry. */
int fm_ui_add_intercept(accel_t *a, uint64_t address, int action, stub_fn py_intercept) {
    if (a->nicpt >= MAX_INTERCEPTS) return -1;
    a->icpt_addr[a->nicpt] = address;
    a->icpt_act[a->nicpt] = action;
    a->icpt_resume[a->nicpt] = 0;
    a->icpt_dest[a->nicpt] = -1;
    a->icpt_nset[a->nicpt] = 0;
    a->py_intercept = py_intercept;
    return a->nicpt++;
}

int fm_ui_abi_version(void) { return ABI_VERSION; }

/* An inlined free-list pop or push inside a shipped function (docs/fmdb/UI_ROUND2.md section 6).
 * The site's instructions are skipped: execution resumes at `resume` with `dest` (a Unicorn
 * register id, ACT_FREE_LIST_POP) holding a zeroed VM-heap block of the pool's element size
 * and the scratch registers the skipped instructions write set to `set_vals` (absolute). */
int fm_ui_add_site(accel_t *a, uint64_t address, int action, uint64_t resume, int dest, uint64_t pool,
                   int nset, const int *set_regs, const uint64_t *set_vals, stub_fn py_intercept) {
    if (a->nicpt >= MAX_INTERCEPTS || nset < 0 || nset > SITE_SETS || !resume) return -1;
    if (action != ACT_FREE_LIST_POP && action != ACT_FREE_LIST_PUSH && action != ACT_PYTHON) return -1;
    int i = a->nicpt;
    a->icpt_addr[i] = address;
    a->icpt_act[i] = action;
    a->icpt_resume[i] = resume;
    a->icpt_dest[i] = dest;
    a->icpt_pool[i] = pool;
    a->icpt_nset[i] = nset;
    for (int k = 0; k < nset; k++) {
        a->icpt_set_reg[i][k] = set_regs[k];
        a->icpt_set_val[i][k] = set_vals[k];
    }
    a->py_intercept = py_intercept;
    return a->nicpt++;
}

/* The model of free-list site i. False: nothing was changed and Python runs its own model. */
static bool run_site(accel_t *a, int i) {
    int action = a->icpt_act[i];
    if (action == ACT_FREE_LIST_POP) {
        uint32_t size;
        if (a->icpt_dest[i] < 0 || !peek(a, a->icpt_pool[i] + 0x12C, &size, 4) || size == 0 || size > 0x100000)
            return false;
        uint64_t block = heap_alloc(a, size, 16);
        if (!block) return false;
        fill(a, block, 0, size);
        set_reg(a, a->icpt_dest[i], block);
    } else if (action != ACT_FREE_LIST_PUSH) {
        return false;
    }
    for (int k = 0; k < a->icpt_nset[i]; k++) set_reg(a, a->icpt_set_reg[i][k], a->icpt_set_val[i][k]);
    return true;
}

uint64_t fm_ui_intercept_count(accel_t *a, int index) {
    uint64_t n = a->icpt_count[index];
    a->icpt_count[index] = 0;
    return n;
}

void fm_ui_intercept(uc_engine *uc, uint64_t address, uint32_t size, void *user) {
    (void)uc;
    (void)size;
    accel_t *a = user;
    for (int i = 0; i < a->nicpt; i++)
        if (a->icpt_addr[i] == address) {
            bool site = a->icpt_resume[i] != 0;
            if (!(site ? run_site(a, i) : run_native(a, a->icpt_act[i]))) {
                a->declined++;
                a->py_intercept(address);
                return;
            }
            a->icpt_count[i]++;
            if (!a->stop) set_reg(a, a->reg_pc, site ? a->icpt_resume[i] : get_reg(a, a->reg_lr));
            return;
        }
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
        } else if (vaddr - a->heap_lo < a->heap_hi - a->heap_lo) {
            if (type == MEM_FETCH) {
                a->faults++;
                a->fault(vaddr, type, WHY_FETCH_PROT);
                return false;
            }
            uint64_t t = a->data_slots + (vaddr - a->heap_lo) / PAGE;
            if (type == MEM_WRITE) mark_written(a, t);
            entry->paddr = vaddr;
            if (a->wr[t]) {
                entry->perms = P_R | P_W;
                a->tlb_w++;
            } else
                entry->perms = P_R;
            return true;
        } else {
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
            int64_t slot = use(a, vaddr / PAGE);
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
                if (a->watch[slot] && a->watch_phys) {
                    entry->paddr = a->watch_phys + (uint64_t)slot * PAGE + (vaddr & (PAGE - 1));
                    entry->perms = P_R | P_W;
                    return true;
                }
                if (type == MEM_WRITE) mark_written(a, (uint64_t)slot);
                entry->paddr = a->data_phys + (uint64_t)slot * PAGE + (vaddr & (PAGE - 1));
                if (a->wr[slot]) {
                    entry->perms = P_R | P_W;
                    a->tlb_w++;
                } else
                    entry->perms = P_R;
                return true;
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

void fm_accel_set_regs(accel_t *a, const uint64_t *regs) {
    void *ptrs[34];
    for (int i = 0; i < 34; i++) ptrs[i] = (void *)&regs[i];
    a->reg_write_batch(a->uc, a->regs, ptrs, 34);
}

/* One uc_emu_start; leaves pc, lr, sp and x0 in the shared state. Returns the uc_err. */
int fm_accel_run(accel_t *a, uint64_t pc, uint64_t until) {
    a->deadline = a->timeout_ticks ? mach_absolute_time() + a->timeout_ticks : 0;
    int err = a->emu_start(a->uc, pc, until, 0, 0);
    void *ptrs[4] = {&a->pc, &a->lr, &a->sp, &a->x0};
    a->reg_read_batch(a->uc, a->out_regs, ptrs, 4);
    a->ndirty = a->nw;
    return err;
}

uint16_t *fm_accel_ext_log(accel_t *a) { return a->ext_log; }

uint64_t fm_accel_ticks_per_second(void) {
    mach_timebase_info_data_t info;
    mach_timebase_info(&info);
    return (uint64_t)(1e9 * (double)info.denom / (double)info.numer);
}
