/*
 * fm_fast_reader: persistent, read-only bulk memory reader for one process.
 *
 * Usage: fm_fast_reader --pid N [--expect-path /absolute/executable]
 *
 * The process attaches once with task_for_pid, then serves a length-prefixed
 * binary protocol on stdin/stdout. No JSON, no hex. All integers are
 * little-endian. It only calls mach_vm_read_overwrite and mach_vm_region
 * (read-only); it never writes, injects code, or suspends threads.
 *
 * Hello (server -> client, once, before any request):
 *   u32 magic=HELLO_MAGIC  u32 status  u32 version  u32 pid  u32 page_size
 *   u32 mach_code  u32 path_len  then path_len bytes (target executable path)
 *   status is ST_OK, or ST_ATTACH_FAILED / ST_PATH_MISMATCH / ST_PROCESS_GONE
 *   (the process then exits non-zero after flushing the hello).
 *
 * Request (client -> server):
 *   u32 magic=REQ_MAGIC  u32 op  u32 count  then count x { u64 addr, u32 len }
 *   op: OP_READV (1), OP_PING (2), OP_QUIT (3), OP_REGIONS (4).
 *   PING, QUIT and REGIONS ignore count and carry no items.
 *
 * Response (server -> client):
 *   u32 magic=RESP_MAGIC  u32 status  u32 count
 *   READV:   count x { u32 item_status, u32 length }, then the concatenated
 *            payload of the items that returned bytes (length bytes each).
 *            An item that failed has a non-zero item_status and length 0.
 *            Header status is ST_OK unless the whole batch was refused or the
 *            target died (ST_PROCESS_GONE, after which the process exits).
 *   PING:    count = 0.
 *   REGIONS: count x { u64 start, u64 size, u32 prot, u32 max_prot,
 *                      u32 user_tag, u32 pages_resident }
 *            (32 bytes each; prot bits are VM_PROT_READ=1, WRITE=2, EXECUTE=4).
 *            Readable protection does not guarantee readable memory: ranges with
 *            pages_resident == 0 (for example user_tag 32 reservations) usually
 *            fail with ST_READ_FAILED. Use them as a hint, not a promise.
 *
 * Limits: item <= 16 MiB, batch <= 256 MiB total payload, <= 1,000,000 items.
 * An item over the limit gets ST_ITEM_TOO_LARGE and does not count toward the
 * batch. A batch over the byte limit is refused whole (ST_BATCH_TOO_LARGE,
 * count 0). A count over 1,000,000 is refused with ST_TOO_MANY_ITEMS and the
 * process exits, because the unread item table cannot be skipped safely.
 */
#include <errno.h>
#include <libproc.h>
#include <mach/mach.h>
#include <mach/mach_error.h>
#include <mach/mach_vm.h>
#include <mach/vm_region.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "fmcp_attach_client.h"

/* The injected route (native/fmcp_attach.h): when the game was started with the
 * FMCP launcher, we read its memory by asking the in-game library over a Mach
 * channel instead of calling task_for_pid. The library's reply tables use the
 * same status numbers and the same 32-byte region record as this file, so the
 * injected path forwards them to the client with no translation. */
static fmcp_channel_t g_channel;
static bool g_injected = false;

#define PROTOCOL_VERSION 1u
#define HELLO_MAGIC 0x4C484D46u /* "FMHL" little-endian */
#define REQ_MAGIC 0x51524D46u   /* "FMRQ" */
#define RESP_MAGIC 0x53524D46u  /* "FMRS" */

enum { OP_READV = 1, OP_PING = 2, OP_QUIT = 3, OP_REGIONS = 4 };

enum {
    ST_OK = 0,
    ST_BAD_MAGIC = 1,
    ST_BAD_OP = 2,
    ST_TOO_MANY_ITEMS = 3,
    ST_BATCH_TOO_LARGE = 4,
    ST_ITEM_TOO_LARGE = 5,
    ST_READ_FAILED = 6,
    ST_PARTIAL = 7,
    ST_PROCESS_GONE = 8,
    ST_BAD_ADDRESS = 9,
    ST_NO_MEMORY = 10,
    ST_ATTACH_FAILED = 11,
    ST_PATH_MISMATCH = 12,
    ST_BAD_LENGTH = 13
};

/* Carried in the hello's mach_code field on success so the client/doctor can
 * report which route attached. 0 stays "task_for_pid" for older clients. */
#define FMCP_ROUTE_IS_TASK_FOR_PID 0u
#define FMCP_ROUTE_IS_INJECTED 1u

#define MAX_ITEM_BYTES (16ULL * 1024 * 1024)
#define MAX_BATCH_BYTES (256ULL * 1024 * 1024)
#define MAX_ITEMS 1000000u
#define REGION_RECORD 32u
#define KEEP_BUFFER_BYTES (64ULL * 1024 * 1024)

static mach_port_t g_task = MACH_PORT_NULL;
static uint8_t *g_buffer = NULL;
static size_t g_buffer_size = 0;

static void put32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static void put64(uint8_t *p, uint64_t v) {
    put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32));
}
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t get64(const uint8_t *p) {
    return (uint64_t)get32(p) | ((uint64_t)get32(p + 4) << 32);
}

/* Returns 1 on success, 0 on clean EOF before the first byte, -1 on error or short read. */
static int read_full(int fd, void *buf, size_t n) {
    size_t done = 0;
    while (done < n) {
        ssize_t r = read(fd, (uint8_t *)buf + done, n - done);
        if (r < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (r == 0) return done == 0 ? 0 : -1;
        done += (size_t)r;
    }
    return 1;
}

static bool write_full(int fd, const void *buf, size_t n) {
    size_t done = 0;
    while (done < n) {
        ssize_t w = write(fd, (const uint8_t *)buf + done, n - done);
        if (w < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        done += (size_t)w;
    }
    return true;
}

/* True when the kernel has turned our send right into a dead name. */
static bool task_is_dead(void) {
    mach_port_type_t type = 0;
    if (mach_port_type(mach_task_self(), g_task, &type) != KERN_SUCCESS) return true;
    return (type & MACH_PORT_TYPE_DEAD_NAME) != 0;
}

static bool kr_means_gone(kern_return_t kr) {
    return kr == MACH_SEND_INVALID_DEST || kr == KERN_INVALID_ARGUMENT || kr == KERN_TERMINATED
        || kr == KERN_INVALID_TASK || kr == MACH_SEND_INVALID_RIGHT || kr == KERN_INVALID_RIGHT;
}

static uint32_t target_page_size(void) {
    task_vm_info_data_t info;
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    if (task_info(g_task, TASK_VM_INFO, (task_info_t)&info, &count) == KERN_SUCCESS
        && count >= TASK_VM_INFO_REV1_COUNT && info.page_size > 0) {
        return (uint32_t)info.page_size;
    }
    return (uint32_t)vm_page_size;
}

static int send_hello(uint32_t status, uint32_t pid, uint32_t page, uint32_t mach_code, const char *path) {
    uint32_t path_len = (uint32_t)strlen(path);
    uint8_t head[28];
    put32(head, HELLO_MAGIC); put32(head + 4, status); put32(head + 8, PROTOCOL_VERSION);
    put32(head + 12, pid); put32(head + 16, page); put32(head + 20, mach_code); put32(head + 24, path_len);
    return write_full(STDOUT_FILENO, head, sizeof head) && write_full(STDOUT_FILENO, path, path_len) ? 0 : 1;
}

static bool send_header(uint32_t status, uint32_t count) {
    uint8_t head[12];
    put32(head, RESP_MAGIC); put32(head + 4, status); put32(head + 8, count);
    return write_full(STDOUT_FILENO, head, sizeof head);
}

static bool ensure_buffer(size_t need) {
    if (need <= g_buffer_size) return true;
    uint8_t *grown = realloc(g_buffer, need);
    if (grown == NULL) return false;
    g_buffer = grown;
    g_buffer_size = need;
    return true;
}

static void trim_buffer(void) {
    if (g_buffer_size > KEEP_BUFFER_BYTES) {
        free(g_buffer);
        g_buffer = NULL;
        g_buffer_size = 0;
    }
}

/* Map a library header status to this file's header status. Item-level statuses
 * match one for one and need no mapping. */
static uint32_t map_injected_status(uint32_t library_status) {
    switch (library_status) {
        case FMCP_ATTACH_OK: return ST_OK;
        case FMCP_ATTACH_TOO_MANY_ITEMS: return ST_TOO_MANY_ITEMS;
        case FMCP_ATTACH_BATCH_TOO_LARGE: return ST_BATCH_TOO_LARGE;
        case FMCP_ATTACH_NO_MEMORY: return ST_NO_MEMORY;
        default: return ST_READ_FAILED;
    }
}

/* Injected READV: read the item table from stdin, forward it to the library,
 * and relay the library's result table and payload unchanged. */
static int serve_readv_injected(uint32_t count) {
    fmcp_item_t *items = NULL;
    if (count > 0) {
        items = malloc((size_t)count * sizeof(fmcp_item_t));
        if (items == NULL) return 4;
        if (read_full(STDIN_FILENO, items, (size_t)count * sizeof(fmcp_item_t)) != 1) {
            free(items);
            return 2;
        }
    }
    fmcp_reply_body_t body;
    uint8_t *bytes = NULL;
    uint64_t len = 0;
    kern_return_t kr = fmcp_round_trip(g_channel.service, FMCP_OP_READV, items, count, &body, &bytes, &len);
    free(items);
    if (kr != KERN_SUCCESS) {
        if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
        return send_header(ST_PROCESS_GONE, 0) ? 3 : 1; /* the library/game went away */
    }
    uint32_t header_status = map_injected_status(body.status);
    if (header_status != ST_OK) {
        if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
        return send_header(header_status, 0) ? 0 : 1;
    }
    /* body.count result records of 8 bytes, then the payloads: relay verbatim. */
    uint64_t table_bytes = (uint64_t)body.count * 8;
    int rc = (send_header(ST_OK, body.count)
              && (len == 0 || write_full(STDOUT_FILENO, bytes, (size_t)len))) ? 0 : 1;
    (void)table_bytes;
    if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
    return rc;
}

static int serve_regions_injected(void) {
    fmcp_reply_body_t body;
    uint8_t *bytes = NULL;
    uint64_t len = 0;
    kern_return_t kr = fmcp_round_trip(g_channel.service, FMCP_OP_REGIONS, NULL, 0, &body, &bytes, &len);
    if (kr != KERN_SUCCESS) {
        if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
        return send_header(ST_PROCESS_GONE, 0) ? 3 : 1;
    }
    if (body.status != FMCP_ATTACH_OK) {
        if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
        return send_header(map_injected_status(body.status), 0) ? 0 : 1;
    }
    int rc = (send_header(ST_OK, body.count)
              && (len == 0 || write_full(STDOUT_FILENO, bytes, (size_t)len))) ? 0 : 1;
    if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
    return rc;
}

/* Returns 0 to keep serving, non-zero exit code to stop. */
static int serve_readv(uint32_t count) {
    if (g_injected) return serve_readv_injected(count);
    uint8_t *table = NULL;
    uint8_t *results = NULL;
    int rc = 0;
    if (count > 0) {
        table = malloc((size_t)count * 12);
        results = malloc((size_t)count * 8);
        if (table == NULL || results == NULL) {
            free(table); free(results);
            return 4;
        }
        if (read_full(STDIN_FILENO, table, (size_t)count * 12) != 1) {
            free(table); free(results);
            return 2;
        }
    }
    uint64_t total = 0;
    bool over_batch = false;
    for (uint32_t i = 0; i < count && !over_batch; ++i) {
        uint64_t length = get32(table + (size_t)i * 12 + 8);
        if (length <= MAX_ITEM_BYTES) {
            total += length;
            if (total > MAX_BATCH_BYTES) over_batch = true;
        }
    }
    if (over_batch) {
        free(table); free(results);
        return send_header(ST_BATCH_TOO_LARGE, 0) ? 0 : 1;
    }
    if (!ensure_buffer(total ? (size_t)total : 1)) {
        free(table); free(results);
        return send_header(ST_NO_MEMORY, 0) ? 0 : 1;
    }
    uint32_t header_status = ST_OK;
    size_t offset = 0;
    bool gone = false;
    for (uint32_t i = 0; i < count; ++i) {
        const uint8_t *entry = table + (size_t)i * 12;
        uint64_t address = get64(entry);
        uint64_t length = get32(entry + 8);
        uint32_t status = ST_OK;
        uint32_t got = 0;
        if (gone) {
            status = ST_PROCESS_GONE;
        } else if (length == 0) {
            status = ST_BAD_LENGTH;
        } else if (length > MAX_ITEM_BYTES) {
            status = ST_ITEM_TOO_LARGE;
        } else if (address == 0 || address > UINT64_MAX - length) {
            status = ST_BAD_ADDRESS;
        } else {
            mach_vm_size_t out_size = 0;
            kern_return_t kr = mach_vm_read_overwrite(g_task, (mach_vm_address_t)address, (mach_vm_size_t)length,
                                                      (mach_vm_address_t)(g_buffer + offset), &out_size);
            if (kr == KERN_SUCCESS && out_size == length) {
                got = (uint32_t)length;
                offset += got;
            } else if (kr == KERN_SUCCESS) {
                status = ST_PARTIAL;
            } else if (kr_means_gone(kr) || task_is_dead()) {
                status = ST_PROCESS_GONE;
                gone = true;
                header_status = ST_PROCESS_GONE;
            } else {
                status = ST_READ_FAILED;
            }
        }
        put32(results + (size_t)i * 8, status);
        put32(results + (size_t)i * 8 + 4, got);
    }
    if (!send_header(header_status, count)
        || (count > 0 && !write_full(STDOUT_FILENO, results, (size_t)count * 8))
        || (offset > 0 && !write_full(STDOUT_FILENO, g_buffer, offset))) {
        rc = 1;
    } else if (gone) {
        rc = 3;
    }
    free(table);
    free(results);
    trim_buffer();
    return rc;
}

static int serve_regions(void) {
    if (g_injected) return serve_regions_injected();
    size_t capacity = 4096, used = 0;
    uint8_t *out = malloc(capacity * REGION_RECORD);
    if (out == NULL) return send_header(ST_NO_MEMORY, 0) ? 0 : 1;
    mach_vm_address_t address = 0;
    uint32_t status = ST_OK;
    for (;;) {
        mach_vm_size_t size = 0;
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t info_count = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t object = MACH_PORT_NULL;
        kern_return_t kr = mach_vm_region(g_task, &address, &size, VM_REGION_BASIC_INFO_64,
                                          (vm_region_info_t)&info, &info_count, &object);
        if (kr != KERN_SUCCESS) {
            if (kr_means_gone(kr) || task_is_dead()) status = ST_PROCESS_GONE;
            break; /* KERN_INVALID_ADDRESS is the normal end of the map */
        }
        if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
        vm_region_extended_info_data_t extended;
        mach_msg_type_number_t extended_count = VM_REGION_EXTENDED_INFO_COUNT;
        mach_vm_address_t extended_address = address;
        mach_vm_size_t extended_size = 0;
        mach_port_t extended_object = MACH_PORT_NULL;
        uint32_t user_tag = 0, resident = 0;
        if (mach_vm_region(g_task, &extended_address, &extended_size, VM_REGION_EXTENDED_INFO,
                           (vm_region_info_t)&extended, &extended_count, &extended_object) == KERN_SUCCESS) {
            if (extended_object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), extended_object);
            if (extended_address == address) {
                user_tag = extended.user_tag;
                resident = extended.pages_resident;
            }
        }
        if (used == capacity) {
            capacity *= 2;
            uint8_t *grown = realloc(out, capacity * REGION_RECORD);
            if (grown == NULL) { status = ST_NO_MEMORY; break; }
            out = grown;
        }
        uint8_t *record = out + used * REGION_RECORD;
        put64(record, address);
        put64(record + 8, size);
        put32(record + 16, (uint32_t)info.protection);
        put32(record + 20, (uint32_t)info.max_protection);
        put32(record + 24, user_tag);
        put32(record + 28, resident);
        used++;
        if (address > UINT64_MAX - size) break;
        address += size;
    }
    if (status != ST_OK) used = 0;
    int rc = (send_header(status, (uint32_t)used) && (used == 0 || write_full(STDOUT_FILENO, out, used * REGION_RECORD))) ? 0 : 1;
    free(out);
    return rc == 0 && status == ST_PROCESS_GONE ? 3 : rc;
}

/* On the injected route there is no task port to watch; death is noticed when a
 * forwarded request to the library fails. */
static bool target_is_dead(void) {
    return g_injected ? false : task_is_dead();
}

static int serve(void) {
    for (;;) {
        struct pollfd input = {STDIN_FILENO, POLLIN, 0};
        int ready = poll(&input, 1, 500);
        if (ready < 0) {
            if (errno == EINTR) continue;
            return 1;
        }
        if (ready == 0) {
            if (target_is_dead()) return 3;
            continue;
        }
        uint8_t head[12];
        int got = read_full(STDIN_FILENO, head, sizeof head);
        if (got == 0) return 0; /* stdin closed */
        if (got < 0) return 2;
        if (get32(head) != REQ_MAGIC) {
            send_header(ST_BAD_MAGIC, 0);
            return 2;
        }
        uint32_t op = get32(head + 4), count = get32(head + 8);
        int result;
        switch (op) {
            case OP_READV:
                if (count > MAX_ITEMS) {
                    send_header(ST_TOO_MANY_ITEMS, 0);
                    return 2;
                }
                result = serve_readv(count);
                break;
            case OP_PING:
                result = target_is_dead() ? (send_header(ST_PROCESS_GONE, 0), 3) : (send_header(ST_OK, 0) ? 0 : 1);
                break;
            case OP_QUIT:
                send_header(ST_OK, 0);
                return 0;
            case OP_REGIONS:
                result = serve_regions();
                break;
            default:
                send_header(ST_BAD_OP, 0);
                return 2;
        }
        if (result) return result;
    }
}

int main(int argc, char **argv) {
    long pid = 0;
    const char *expect_path = NULL;
    const char *route_text = getenv("FMCP_ATTACH_ROUTE");
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--pid") == 0 && i + 1 < argc) {
            char *end;
            errno = 0;
            pid = strtol(argv[++i], &end, 10);
            if (errno || *end || pid <= 0 || pid > INT32_MAX) pid = 0;
        } else if (strcmp(argv[i], "--expect-path") == 0 && i + 1 < argc) {
            expect_path = argv[++i];
        } else if (strcmp(argv[i], "--route") == 0 && i + 1 < argc) {
            route_text = argv[++i];
        } else {
            pid = 0;
            break;
        }
    }
    int prefer = fmcp_parse_prefer(route_text);
    if (pid <= 0 || prefer < 0) {
        fprintf(stderr, "usage: fm_fast_reader --pid N [--expect-path PATH] [--route auto|injected|task-for-pid]\n");
        return 2;
    }
    signal(SIGPIPE, SIG_IGN);

    char path[PROC_PIDPATHINFO_MAXSIZE];
    memset(path, 0, sizeof path);
    if (proc_pidpath((int)pid, path, sizeof path) <= 0) {
        send_hello(ST_PROCESS_GONE, (uint32_t)pid, 0, 0, "");
        return 3;
    }

    /* The injected route first (unless the caller forced task_for_pid): look the
     * in-game library's service up and PING it. It never calls task_for_pid, so a
     * machine with default SIP can use it where task_for_pid would fail. */
    if (prefer != FMCP_PREFER_TASK_FOR_PID) {
        int state = fmcp_connect((pid_t)pid, &g_channel);
        if (state == FMCP_CONNECT_OK) {
            if (expect_path != NULL && strcmp(expect_path, path) != 0) {
                fmcp_disconnect(&g_channel);
                send_hello(ST_PATH_MISMATCH, (uint32_t)pid, 0, 0, path);
                return 1;
            }
            g_injected = true;
            uint32_t page = g_channel.page_size ? g_channel.page_size : (uint32_t)vm_page_size;
            /* The 6th hello field carries the route (1 = injected) for the client/doctor. */
            if (send_hello(ST_OK, (uint32_t)pid, page, FMCP_ROUTE_IS_INJECTED, path) != 0) return 1;
            int result = serve();
            fmcp_disconnect(&g_channel);
            return result;
        }
        if (prefer == FMCP_PREFER_INJECTED) {
            /* Forced injected and the library is not there: say so and stop. */
            send_hello(ST_ATTACH_FAILED, (uint32_t)pid, 0, (uint32_t)state, path);
            return 1;
        }
        /* auto: fall through to task_for_pid. */
    }

    kern_return_t kr = task_for_pid(mach_task_self(), (pid_t)pid, &g_task);
    if (kr != KERN_SUCCESS) {
        send_hello(ST_ATTACH_FAILED, (uint32_t)pid, 0, (uint32_t)kr, path);
        return 1;
    }
    /* Re-check the path after attaching so a recycled pid cannot slip through. */
    char again[PROC_PIDPATHINFO_MAXSIZE];
    memset(again, 0, sizeof again);
    if (proc_pidpath((int)pid, again, sizeof again) <= 0 || strcmp(again, path) != 0) {
        send_hello(ST_PATH_MISMATCH, (uint32_t)pid, 0, 0, path);
        return 1;
    }
    if (expect_path != NULL && strcmp(expect_path, path) != 0) {
        send_hello(ST_PATH_MISMATCH, (uint32_t)pid, 0, 0, path);
        return 1;
    }
    if (send_hello(ST_OK, (uint32_t)pid, target_page_size(), FMCP_ROUTE_IS_TASK_FOR_PID, path) != 0) return 1;
    int result = serve();
    mach_port_deallocate(mach_task_self(), g_task);
    return result;
}
