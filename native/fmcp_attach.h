/*
 * fmcp_attach.h: the injected attach route, shared by the in-game library
 * (native/fmcp_attach_lib.c) and the reader client (native/fmcp_attach_client.h,
 * used by fm_fast_reader).
 *
 * Why the library serves reads instead of handing over a task port
 *   The first design was for the in-game library to send the reader a send
 *   right to the game's own task READ port, after which the reader's existing
 *   mach_vm_read code would work with no task_for_pid. On current macOS that is
 *   impossible without changing the game's entitlements: a hardened process's
 *   own task ports are immovable (anti-exfiltration), so moving or copying the
 *   self read port into a Mach message raises EXC_GUARD ILLEGAL_MOVE and kills
 *   the process. Measured on this machine (Darwin 27); see docs/attach-injected.md.
 *   So the library serves reads itself: it reads its own memory with
 *   mach_vm_read_overwrite(mach_task_self(), ...) -- always permitted, and
 *   fault-safe (a bad address returns KERN_INVALID_ADDRESS, never a crash) --
 *   and returns the bytes to the reader over a Mach channel.
 *
 * The channel
 *   The FMCP launcher starts the game with libfmcp_attach.dylib in
 *   DYLD_INSERT_LIBRARIES. A constructor starts one detached thread that
 *   registers a bootstrap service FMCP_ATTACH_SERVICE_PREFIX + "<game pid>" and
 *   blocks in mach_msg. The reader looks the service up and sends read batches;
 *   the library answers each with the bytes. No read ever runs on a game thread's
 *   own work -- the serving thread is the library's own -- and nothing is written
 *   to game memory, no symbol is interposed, and the thread costs no CPU while
 *   idle. Kill switch: FMCP_ATTACH_DISABLE=1 makes the library inert.
 *
 * Who is answered
 *   Only a sender whose audit token has the game's effective uid, a valid code
 *   signature, and an executable in the same directory as the loaded library
 *   (the FMCP build directory). Everything else gets a refusal and no bytes.
 *
 * Wire protocol (Apple Silicon = little-endian; all integers host order)
 *   Request  (reader -> library): mach_msg, msgh_id FMCP_ATTACH_MSG_REQUEST,
 *     reply port in msgh_local_port as MAKE_SEND_ONCE. One OOL descriptor
 *     carries the item table for READV (count x fmcp_item_t); PING and REGIONS
 *     carry no descriptor. Inline body: fmcp_request_body_t.
 *   Reply    (library -> reader): complex, msgh_id FMCP_ATTACH_MSG_REPLY. For
 *     READV and REGIONS one OOL descriptor carries the result bytes
 *     (fmcp_reply_body_t.ool_bytes long); PING and refusals carry none. Inline
 *     body: fmcp_reply_body_t.
 *   READV result bytes: count x fmcp_result_t, then the concatenated payloads of
 *     the items that returned bytes, in item order.
 *   REGIONS result bytes: count x fmcp_region_t.
 *   A reader refuses a library whose protocol_version differs. Bump
 *   FMCP_ATTACH_PROTOCOL_VERSION on any change here or to what the channel grants.
 *
 * Limits mirror fm_fast_reader so the reader can drive either without retuning.
 */
#ifndef FMCP_ATTACH_H
#define FMCP_ATTACH_H

#include <mach/mach.h>
#include <stdint.h>

#define FMCP_ATTACH_PROTOCOL_VERSION 2u
#define FMCP_ATTACH_LIBRARY_VERSION "fmcp-attach 2.0.0"
#define FMCP_ATTACH_SERVICE_PREFIX "com.fmcp27.attach."
#define FMCP_ATTACH_MAGIC 0x54414D46u /* "FMAT" little-endian */
#define FMCP_ATTACH_MSG_REQUEST 0x464D0001
#define FMCP_ATTACH_MSG_REPLY 0x464D0002
#define FMCP_ATTACH_TIMEOUT_MS 20000u

/* Environment the library reads at load time. */
#define FMCP_ATTACH_ENV_DISABLE "FMCP_ATTACH_DISABLE" /* "1": the library does nothing at all */
#define FMCP_ATTACH_ENV_TARGET "FMCP_ATTACH_TARGET"   /* executable path the library may serve */

/* Operations (match fm_fast_reader's op numbers). */
enum { FMCP_OP_READV = 1, FMCP_OP_PING = 2, FMCP_OP_REGIONS = 4 };

/* Reply status (header level). */
enum {
    FMCP_ATTACH_OK = 0,
    FMCP_ATTACH_VERSION_MISMATCH = 1,
    FMCP_ATTACH_DENIED_UID = 2,
    FMCP_ATTACH_DENIED_PEER = 3,
    FMCP_ATTACH_BAD_REQUEST = 4,
    FMCP_ATTACH_TOO_MANY_ITEMS = 5,
    FMCP_ATTACH_BATCH_TOO_LARGE = 6,
    FMCP_ATTACH_NO_MEMORY = 7
};

/* Per-item READV status (match fm_fast_reader item status names). */
enum {
    FMCP_ITEM_OK = 0,
    FMCP_ITEM_READ_FAILED = 6,
    FMCP_ITEM_PARTIAL = 7,
    FMCP_ITEM_BAD_ADDRESS = 9,
    FMCP_ITEM_TOO_LARGE = 5,
    FMCP_ITEM_BAD_LENGTH = 13
};

#define FMCP_MAX_ITEM_BYTES (16ULL * 1024 * 1024)
#define FMCP_MAX_BATCH_BYTES (256ULL * 1024 * 1024)
#define FMCP_MAX_ITEMS 1000000u

#pragma pack(push, 1)
typedef struct { uint64_t address; uint32_t length; } fmcp_item_t;
typedef struct { uint32_t status; uint32_t length; } fmcp_result_t;
typedef struct {
    uint64_t start, size;
    uint32_t protection, max_protection, user_tag, pages_resident;
} fmcp_region_t; /* 32 bytes, identical to fm_fast_reader's REGIONS record */
#pragma pack(pop)

typedef struct {
    uint32_t magic;
    uint32_t protocol_version;
    uint32_t op;
    uint32_t count;      /* READV item count; 0 for PING/REGIONS */
} fmcp_request_body_t;

typedef struct {
    uint32_t magic;
    uint32_t protocol_version;
    uint32_t status;
    uint32_t count;      /* items (READV) or regions (REGIONS) in the OOL bytes */
    uint64_t ool_bytes;  /* length of the OOL result region, 0 when none */
    uint32_t pid;        /* the game's pid as the library sees it */
    uint32_t page_size;
    char library_version[28];
} fmcp_reply_body_t;

/* On-wire request: header, body descriptor, optional OOL item table, inline body. */
typedef struct {
    mach_msg_header_t header;
    mach_msg_body_t body;
    mach_msg_ool_descriptor_t items; /* present only when request_body.op == READV */
    fmcp_request_body_t request_body;
} fmcp_readv_request_t;

typedef struct {
    mach_msg_header_t header;
    fmcp_request_body_t request_body;
} fmcp_simple_request_t; /* PING / REGIONS: no descriptor */

/* On-wire reply: header, body descriptor, OOL result bytes, inline body. */
typedef struct {
    mach_msg_header_t header;
    mach_msg_body_t body;
    mach_msg_ool_descriptor_t result;
    fmcp_reply_body_t reply_body;
} fmcp_complex_reply_t;

typedef struct {
    mach_msg_header_t header;
    fmcp_reply_body_t reply_body;
} fmcp_simple_reply_t; /* PING / refusal: no descriptor */

#endif
