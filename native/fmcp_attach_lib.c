/*
 * libfmcp_attach.dylib: the only FMCP code that runs inside the game.
 *
 * Loaded at launch through DYLD_INSERT_LIBRARIES by the FMCP launcher. It serves
 * read-only memory reads to the FMCP readers over a Mach channel and does
 * nothing else (protocol and policy: native/fmcp_attach.h).
 *
 * In the game process
 *   - Constructor: reads two environment variables and, when both allow it,
 *     starts one detached thread on its own 512 KiB stack. Nothing else runs on
 *     the loading thread. No symbol is interposed, no game memory is written,
 *     no file is created, nothing is logged.
 *   - The thread registers one bootstrap service and blocks in mach_msg. It
 *     wakes only when a reader sends a batch, reads the requested bytes from its
 *     OWN address space with mach_vm_read_overwrite(mach_task_self(), ...) --
 *     which the kernel always permits and which returns KERN_INVALID_ADDRESS
 *     for an unmapped address instead of faulting, so a bad request can never
 *     crash the game -- and replies. Then it blocks again. If no reader ever
 *     connects it stays blocked for the life of the game at no CPU cost.
 *   - Reads happen on this thread, never on a game worker thread, and never
 *     write to or change the protection of any page. The reader cannot make the
 *     library do anything but read bytes and list regions.
 *
 * Kill switch: FMCP_ATTACH_DISABLE=1 makes the constructor return at once. The
 * library also stays inert unless FMCP_ATTACH_TARGET names this process's own
 * executable, so a child process that inherits the environment does nothing.
 */
#include "fmcp_attach.h"

#include <bsm/libbsm.h>
#include <dlfcn.h>
#include <libproc.h>
#include <limits.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <pthread.h>
#include <servers/bootstrap.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Declared in the kernel's sys/codesign.h, exported by libsystem_kernel. */
extern int csops_audittoken(pid_t pid, unsigned int ops, void *useraddr, size_t usersize, audit_token_t *token);
#define FMCP_CS_OPS_STATUS 0u
#define FMCP_CS_VALID 0x00000001u

static char g_library_dir[PROC_PIDPATHINFO_MAXSIZE];
static char g_service[128];
static uint32_t g_page_size = 16384;

/* Receive buffer: the inline request plus the largest trailer we ask for. */
typedef struct {
    fmcp_readv_request_t request;
    mach_msg_audit_trailer_t trailer;
} received_t;

static bool parent_dir(const char *path, char *out, size_t size) {
    const char *slash = strrchr(path, '/');
    if (slash == NULL || slash == path || (size_t)(slash - path) >= size) return false;
    memcpy(out, path, (size_t)(slash - path));
    out[slash - path] = '\0';
    return true;
}

/* The sender must run as our user, be validly signed, and live beside this library. */
static uint32_t check_peer(audit_token_t *token) {
    if (audit_token_to_euid(*token) != geteuid()) return FMCP_ATTACH_DENIED_UID;
    char path[PROC_PIDPATHINFO_MAXSIZE];
    char dir[PROC_PIDPATHINFO_MAXSIZE];
    uint32_t flags = 0;
    pid_t pid = audit_token_to_pid(*token);
    if (csops_audittoken(pid, FMCP_CS_OPS_STATUS, &flags, sizeof flags, token) != 0
        || (flags & FMCP_CS_VALID) == 0) {
        return FMCP_ATTACH_DENIED_PEER;
    }
    if (proc_pidpath_audittoken(token, path, sizeof path) <= 0) return FMCP_ATTACH_DENIED_PEER;
    if (!parent_dir(path, dir, sizeof dir) || strcmp(dir, g_library_dir) != 0) return FMCP_ATTACH_DENIED_PEER;
    return FMCP_ATTACH_OK;
}

static void fill_reply_body(fmcp_reply_body_t *body, uint32_t status, uint32_t count, uint64_t ool_bytes) {
    body->magic = FMCP_ATTACH_MAGIC;
    body->protocol_version = FMCP_ATTACH_PROTOCOL_VERSION;
    body->status = status;
    body->count = count;
    body->ool_bytes = ool_bytes;
    body->pid = (uint32_t)getpid();
    body->page_size = g_page_size;
    strlcpy(body->library_version, FMCP_ATTACH_LIBRARY_VERSION, sizeof body->library_version);
}

/* A reply with no OOL region (PING, or any refusal). */
static void reply_simple(mach_port_t reply_port, uint32_t status) {
    fmcp_simple_reply_t reply;
    memset(&reply, 0, sizeof reply);
    reply.header.msgh_bits = MACH_MSGH_BITS_SET(MACH_MSG_TYPE_MOVE_SEND_ONCE, 0, 0, 0);
    reply.header.msgh_size = sizeof reply;
    reply.header.msgh_remote_port = reply_port;
    reply.header.msgh_id = FMCP_ATTACH_MSG_REPLY;
    fill_reply_body(&reply.reply_body, status, 0, 0);
    if (mach_msg(&reply.header, MACH_SEND_MSG | MACH_SEND_TIMEOUT, sizeof reply, 0,
                 MACH_PORT_NULL, 1000, MACH_PORT_NULL) != MACH_MSG_SUCCESS) {
        mach_port_deallocate(mach_task_self(), reply_port);
    }
}

/* A reply whose count records and payload sit in `bytes` (length `ool_bytes`),
 * sent out of line. The kernel frees the region after it maps it to the reader. */
static void reply_with_bytes(mach_port_t reply_port, uint32_t status, uint32_t count,
                             void *bytes, uint64_t ool_bytes) {
    fmcp_complex_reply_t reply;
    memset(&reply, 0, sizeof reply);
    reply.header.msgh_bits = MACH_MSGH_BITS_SET(MACH_MSG_TYPE_MOVE_SEND_ONCE, 0, 0, MACH_MSGH_BITS_COMPLEX);
    reply.header.msgh_size = sizeof reply;
    reply.header.msgh_remote_port = reply_port;
    reply.header.msgh_id = FMCP_ATTACH_MSG_REPLY;
    reply.body.msgh_descriptor_count = 1;
    reply.result.address = bytes;
    reply.result.size = (mach_msg_size_t)ool_bytes;
    reply.result.deallocate = TRUE;    /* hand the region to the kernel */
    reply.result.copy = MACH_MSG_VIRTUAL_COPY;
    reply.result.type = MACH_MSG_OOL_DESCRIPTOR;
    fill_reply_body(&reply.reply_body, status, count, ool_bytes);
    if (mach_msg(&reply.header, MACH_SEND_MSG | MACH_SEND_TIMEOUT, sizeof reply, 0,
                 MACH_PORT_NULL, 5000, MACH_PORT_NULL) != MACH_MSG_SUCCESS) {
        /* The kernel did not take the message: free the region and the right ourselves. */
        if (bytes != NULL) vm_deallocate(mach_task_self(), (vm_address_t)bytes, (vm_size_t)ool_bytes);
        mach_port_deallocate(mach_task_self(), reply_port);
    }
}

static void serve_readv(mach_port_t reply_port, const fmcp_item_t *items, uint32_t count) {
    if (count > FMCP_MAX_ITEMS) { reply_simple(reply_port, FMCP_ATTACH_TOO_MANY_ITEMS); return; }
    uint64_t payload = 0;
    for (uint32_t i = 0; i < count; ++i) {
        if (items[i].length > 0 && items[i].length <= FMCP_MAX_ITEM_BYTES) {
            payload += items[i].length;
            if (payload > FMCP_MAX_BATCH_BYTES) { reply_simple(reply_port, FMCP_ATTACH_BATCH_TOO_LARGE); return; }
        }
    }
    uint64_t table_bytes = (uint64_t)count * sizeof(fmcp_result_t);
    uint64_t total = table_bytes + payload;
    vm_address_t out = 0;
    if (vm_allocate(mach_task_self(), &out, (vm_size_t)(total ? total : 1), VM_FLAGS_ANYWHERE) != KERN_SUCCESS) {
        reply_simple(reply_port, FMCP_ATTACH_NO_MEMORY);
        return;
    }
    fmcp_result_t *results = (fmcp_result_t *)out;
    uint8_t *data = (uint8_t *)out + table_bytes;
    uint64_t offset = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint64_t address = items[i].address, length = items[i].length;
        uint32_t st = FMCP_ITEM_OK, got = 0;
        if (length == 0) {
            st = FMCP_ITEM_BAD_LENGTH;
        } else if (length > FMCP_MAX_ITEM_BYTES) {
            st = FMCP_ITEM_TOO_LARGE;
        } else if (address == 0 || address > UINT64_MAX - length) {
            st = FMCP_ITEM_BAD_ADDRESS;
        } else {
            mach_vm_size_t read = 0;
            kern_return_t kr = mach_vm_read_overwrite(mach_task_self(), (mach_vm_address_t)address,
                                                      (mach_vm_size_t)length,
                                                      (mach_vm_address_t)(data + offset), &read);
            if (kr == KERN_SUCCESS && read == length) { got = (uint32_t)length; offset += got; }
            else if (kr == KERN_SUCCESS) st = FMCP_ITEM_PARTIAL;
            else st = (kr == KERN_INVALID_ADDRESS) ? FMCP_ITEM_BAD_ADDRESS : FMCP_ITEM_READ_FAILED;
        }
        results[i].status = st;
        results[i].length = got;
    }
    reply_with_bytes(reply_port, FMCP_ATTACH_OK, count, (void *)out, table_bytes + offset);
}

static void serve_regions(mach_port_t reply_port) {
    size_t capacity = 8192, used = 0;
    vm_address_t out = 0;
    if (vm_allocate(mach_task_self(), &out, (vm_size_t)(capacity * sizeof(fmcp_region_t)), VM_FLAGS_ANYWHERE) != KERN_SUCCESS) {
        reply_simple(reply_port, FMCP_ATTACH_NO_MEMORY);
        return;
    }
    fmcp_region_t *records = (fmcp_region_t *)out;
    mach_vm_address_t address = 0;
    for (;;) {
        mach_vm_size_t size = 0;
        vm_region_basic_info_data_64_t basic;
        mach_msg_type_number_t basic_count = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t object = MACH_PORT_NULL;
        kern_return_t kr = mach_vm_region(mach_task_self(), &address, &size, VM_REGION_BASIC_INFO_64,
                                          (vm_region_info_t)&basic, &basic_count, &object);
        if (kr != KERN_SUCCESS) break; /* KERN_INVALID_ADDRESS ends the map */
        if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
        vm_region_extended_info_data_t ext;
        mach_msg_type_number_t ext_count = VM_REGION_EXTENDED_INFO_COUNT;
        mach_vm_address_t ext_address = address;
        mach_vm_size_t ext_size = 0;
        mach_port_t ext_object = MACH_PORT_NULL;
        uint32_t user_tag = 0, resident = 0;
        if (mach_vm_region(mach_task_self(), &ext_address, &ext_size, VM_REGION_EXTENDED_INFO,
                           (vm_region_info_t)&ext, &ext_count, &ext_object) == KERN_SUCCESS) {
            if (ext_object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), ext_object);
            if (ext_address == address) { user_tag = ext.user_tag; resident = ext.pages_resident; }
        }
        if (used == capacity) {
            vm_address_t grown = 0;
            if (vm_allocate(mach_task_self(), &grown, (vm_size_t)(capacity * 2 * sizeof(fmcp_region_t)), VM_FLAGS_ANYWHERE) != KERN_SUCCESS) break;
            memcpy((void *)grown, records, used * sizeof(fmcp_region_t));
            vm_deallocate(mach_task_self(), out, (vm_size_t)(capacity * sizeof(fmcp_region_t)));
            out = grown; records = (fmcp_region_t *)out; capacity *= 2;
        }
        records[used].start = address;
        records[used].size = size;
        records[used].protection = (uint32_t)basic.protection;
        records[used].max_protection = (uint32_t)basic.max_protection;
        records[used].user_tag = user_tag;
        records[used].pages_resident = resident;
        used++;
        if (address > UINT64_MAX - size) break;
        address += size;
    }
    reply_with_bytes(reply_port, FMCP_ATTACH_OK, (uint32_t)used, (void *)out, used * sizeof(fmcp_region_t));
}

static void serve_one(received_t *in) {
    mach_msg_header_t *header = &in->request.header;
    mach_port_t reply_port = header->msgh_remote_port;
    bool well_formed = header->msgh_id == FMCP_ATTACH_MSG_REQUEST
        && MACH_MSGH_BITS_REMOTE(header->msgh_bits) == MACH_MSG_TYPE_MOVE_SEND_ONCE
        && reply_port != MACH_PORT_NULL;
    if (!well_formed) { mach_msg_destroy(header); return; }

    /* The audit trailer sits right after the received message body. */
    mach_msg_audit_trailer_t *trailer =
        (mach_msg_audit_trailer_t *)((uint8_t *)header + round_msg(header->msgh_size));
    bool have_audit = trailer->msgh_trailer_size >= sizeof(mach_msg_audit_trailer_t);

    /* Pull the inline request body; its offset depends on whether an OOL item
     * descriptor is present (complex message). */
    bool complex = (header->msgh_bits & MACH_MSGH_BITS_COMPLEX) != 0;
    fmcp_request_body_t body;
    const fmcp_item_t *items = NULL;
    uint32_t item_count = 0;
    bool items_valid = false;
    if (complex) {
        if (in->request.body.msgh_descriptor_count != 1
            || in->request.items.type != MACH_MSG_OOL_DESCRIPTOR) {
            mach_msg_destroy(header);
            return;
        }
        body = in->request.request_body;
        items = (const fmcp_item_t *)in->request.items.address;
        item_count = (uint32_t)(in->request.items.size / sizeof(fmcp_item_t));
        items_valid = items != NULL;
    } else {
        body = ((fmcp_simple_request_t *)header)->request_body;
    }

    if (body.magic != FMCP_ATTACH_MAGIC) { mach_msg_destroy(header); return; }
    if (!have_audit) { reply_simple(reply_port, FMCP_ATTACH_DENIED_PEER); goto cleanup; }
    if (body.protocol_version != FMCP_ATTACH_PROTOCOL_VERSION) {
        reply_simple(reply_port, FMCP_ATTACH_VERSION_MISMATCH); goto cleanup;
    }
    uint32_t peer = check_peer(&trailer->msgh_audit);
    if (peer != FMCP_ATTACH_OK) { reply_simple(reply_port, peer); goto cleanup; }

    switch (body.op) {
        case FMCP_OP_PING:    reply_simple(reply_port, FMCP_ATTACH_OK); break;
        case FMCP_OP_REGIONS: serve_regions(reply_port); break;
        case FMCP_OP_READV:
            if (!items_valid || body.count != item_count) reply_simple(reply_port, FMCP_ATTACH_BAD_REQUEST);
            else serve_readv(reply_port, items, item_count);
            break;
        default: reply_simple(reply_port, FMCP_ATTACH_BAD_REQUEST); break;
    }
cleanup:
    /* Free the inbound OOL item table the kernel mapped for us. */
    if (complex && items != NULL) vm_deallocate(mach_task_self(), (vm_address_t)items, (vm_size_t)in->request.items.size);
}

static void *attach_thread(void *unused) {
    (void)unused;
    pthread_setname_np("fmcp-attach");
    mach_port_t service = MACH_PORT_NULL;
    if (mach_port_allocate(mach_task_self(), MACH_PORT_RIGHT_RECEIVE, &service) != KERN_SUCCESS) return NULL;
    if (mach_port_insert_right(mach_task_self(), service, service, MACH_MSG_TYPE_MAKE_SEND) != KERN_SUCCESS) {
        mach_port_mod_refs(mach_task_self(), service, MACH_PORT_RIGHT_RECEIVE, -1);
        return NULL;
    }
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    kern_return_t kr = bootstrap_register(bootstrap_port, g_service, service);
#pragma clang diagnostic pop
    mach_port_deallocate(mach_task_self(), service); /* bootstrap_register copied the send right */
    if (kr != KERN_SUCCESS) {
        mach_port_mod_refs(mach_task_self(), service, MACH_PORT_RIGHT_RECEIVE, -1);
        return NULL;
    }
    for (;;) {
        received_t in;
        memset(&in, 0, sizeof in);
        kr = mach_msg(&in.request.header,
                      MACH_RCV_MSG | MACH_RCV_TRAILER_TYPE(MACH_MSG_TRAILER_FORMAT_0)
                          | MACH_RCV_TRAILER_ELEMENTS(MACH_RCV_TRAILER_AUDIT),
                      0, sizeof in, service, MACH_MSG_TIMEOUT_NONE, MACH_PORT_NULL);
        if (kr == MACH_MSG_SUCCESS) serve_one(&in);
        else if (kr != MACH_RCV_TOO_LARGE && kr != MACH_RCV_INTERRUPTED) return NULL;
    }
}

static bool should_serve(void) {
    const char *disable = getenv(FMCP_ATTACH_ENV_DISABLE);
    if (disable != NULL && strcmp(disable, "1") == 0) return false;
    const char *target = getenv(FMCP_ATTACH_ENV_TARGET);
    if (target == NULL || target[0] == '\0') return false;
    char self_path[PROC_PIDPATHINFO_MAXSIZE];
    if (proc_pidpath(getpid(), self_path, sizeof self_path) <= 0) return false;
    if (strcmp(self_path, target) != 0) return false;
    Dl_info info;
    if (dladdr((const void *)&should_serve, &info) == 0 || info.dli_fname == NULL) return false;
    char resolved[PATH_MAX];
    if (realpath(info.dli_fname, resolved) == NULL) return false;
    if (!parent_dir(resolved, g_library_dir, sizeof g_library_dir)) return false;
    g_page_size = (uint32_t)vm_page_size;
    int n = snprintf(g_service, sizeof g_service, "%s%d", FMCP_ATTACH_SERVICE_PREFIX, (int)getpid());
    return n > 0 && (size_t)n < sizeof g_service;
}

__attribute__((constructor)) static void fmcp_attach_init(void) {
    if (!should_serve()) return;
    pthread_attr_t attr;
    if (pthread_attr_init(&attr) != 0) return;
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_attr_setstacksize(&attr, 512 * 1024);
    pthread_t thread;
    pthread_create(&thread, &attr, attach_thread, NULL);
    pthread_attr_destroy(&attr);
}

/* Lets `nm` and the doctor identify the library and its protocol. */
__attribute__((visibility("default"), used)) const char fmcp_attach_library_version[] = FMCP_ATTACH_LIBRARY_VERSION;
__attribute__((visibility("default"), used)) const unsigned fmcp_attach_protocol_version = FMCP_ATTACH_PROTOCOL_VERSION;
