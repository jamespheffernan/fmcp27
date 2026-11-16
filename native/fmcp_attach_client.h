/*
 * fmcp_attach_client.h: the reader side of the injected channel.
 *
 * fm_fast_reader uses this to drive the in-game library instead of attaching
 * with task_for_pid: it looks the library's bootstrap service up and sends
 * READV / PING / REGIONS batches, receiving the bytes out of line. The reader
 * never calls task_for_pid on this path, so success proves the injected route
 * works without the SIP exception.
 *
 * Header-only so fm_fast_reader needs no build-system change.
 */
#ifndef FMCP_ATTACH_CLIENT_H
#define FMCP_ATTACH_CLIENT_H

#include "fmcp_attach.h"

#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <servers/bootstrap.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

enum {
    FMCP_CONNECT_OK = 0,
    FMCP_CONNECT_ABSENT = 1,    /* no service: the game was not started with the FMCP launcher */
    FMCP_CONNECT_NO_REPLY = 2,
    FMCP_CONNECT_REFUSED = 3,   /* library answered PING with a non-OK status */
    FMCP_CONNECT_VERSION = 4,   /* library speaks a different protocol version */
    FMCP_CONNECT_BAD_REPLY = 5
};

typedef struct {
    mach_port_t service;        /* send right to the library's service */
    int state;                  /* FMCP_CONNECT_* from the last connect */
    uint32_t library_status;    /* FMCP_ATTACH_* from the PING reply */
    uint32_t library_protocol;
    uint32_t pid;
    uint32_t page_size;
    char library_version[28];
} fmcp_channel_t;

static inline const char *fmcp_connect_name(int state) {
    switch (state) {
        case FMCP_CONNECT_OK: return "ok";
        case FMCP_CONNECT_ABSENT: return "not_loaded";
        case FMCP_CONNECT_NO_REPLY: return "no_reply";
        case FMCP_CONNECT_REFUSED: return "refused";
        case FMCP_CONNECT_VERSION: return "version_mismatch";
        default: return "bad_reply";
    }
}

/* One request/reply round trip. On success *out_body is the reply body and, when
 * the reply carried an OOL region, out_bytes/out_len point at it (free with
 * mach_vm_deallocate). Returns a mach error, or KERN_SUCCESS. */
static inline kern_return_t fmcp_round_trip(mach_port_t service, uint32_t op,
                                            const fmcp_item_t *items, uint32_t count,
                                            fmcp_reply_body_t *out_body,
                                            uint8_t **out_bytes, uint64_t *out_len) {
    *out_bytes = NULL; *out_len = 0;
    mach_port_t reply_port = MACH_PORT_NULL;
    kern_return_t kr = mach_port_allocate(mach_task_self(), MACH_PORT_RIGHT_RECEIVE, &reply_port);
    if (kr != KERN_SUCCESS) return kr;

    union {
        fmcp_readv_request_t readv;
        fmcp_simple_request_t simple;
    } req;
    memset(&req, 0, sizeof req);
    mach_msg_header_t *h = &req.readv.header;
    size_t send_size;
    if (op == FMCP_OP_READV) {
        h->msgh_bits = MACH_MSGH_BITS_SET(MACH_MSG_TYPE_COPY_SEND, MACH_MSG_TYPE_MAKE_SEND_ONCE, 0, MACH_MSGH_BITS_COMPLEX);
        req.readv.body.msgh_descriptor_count = 1;
        req.readv.items.address = (void *)items;
        req.readv.items.size = (mach_msg_size_t)(count * sizeof(fmcp_item_t));
        req.readv.items.deallocate = FALSE;
        req.readv.items.copy = MACH_MSG_VIRTUAL_COPY;
        req.readv.items.type = MACH_MSG_OOL_DESCRIPTOR;
        req.readv.request_body.magic = FMCP_ATTACH_MAGIC;
        req.readv.request_body.protocol_version = FMCP_ATTACH_PROTOCOL_VERSION;
        req.readv.request_body.op = op;
        req.readv.request_body.count = count;
        send_size = sizeof(fmcp_readv_request_t);
    } else {
        h->msgh_bits = MACH_MSGH_BITS_SET(MACH_MSG_TYPE_COPY_SEND, MACH_MSG_TYPE_MAKE_SEND_ONCE, 0, 0);
        req.simple.request_body.magic = FMCP_ATTACH_MAGIC;
        req.simple.request_body.protocol_version = FMCP_ATTACH_PROTOCOL_VERSION;
        req.simple.request_body.op = op;
        req.simple.request_body.count = 0;
        send_size = sizeof(fmcp_simple_request_t);
    }
    h->msgh_size = (mach_msg_size_t)send_size;
    h->msgh_remote_port = service;
    h->msgh_local_port = reply_port;
    h->msgh_id = FMCP_ATTACH_MSG_REQUEST;

    struct {
        fmcp_complex_reply_t reply;
        mach_msg_trailer_t trailer;
    } in;
    memset(&in, 0, sizeof in);
    kr = mach_msg(h, MACH_SEND_MSG | MACH_SEND_TIMEOUT, (mach_msg_size_t)send_size, 0,
                  MACH_PORT_NULL, FMCP_ATTACH_TIMEOUT_MS, MACH_PORT_NULL);
    if (kr == MACH_MSG_SUCCESS) {
        kr = mach_msg(&in.reply.header, MACH_RCV_MSG | MACH_RCV_TIMEOUT, 0, sizeof in, reply_port,
                      FMCP_ATTACH_TIMEOUT_MS, MACH_PORT_NULL);
    }
    mach_port_mod_refs(mach_task_self(), reply_port, MACH_PORT_RIGHT_RECEIVE, -1);
    if (kr != MACH_MSG_SUCCESS) return kr;

    bool complex = (in.reply.header.msgh_bits & MACH_MSGH_BITS_COMPLEX) != 0;
    const fmcp_reply_body_t *body = complex ? &in.reply.reply_body
                                            : &((fmcp_simple_reply_t *)&in.reply.header)->reply_body;
    if (in.reply.header.msgh_id != FMCP_ATTACH_MSG_REPLY || body->magic != FMCP_ATTACH_MAGIC) {
        mach_msg_destroy(&in.reply.header);
        return KERN_FAILURE;
    }
    *out_body = *body;
    if (complex && in.reply.body.msgh_descriptor_count == 1
        && in.reply.result.type == MACH_MSG_OOL_DESCRIPTOR && in.reply.result.address != NULL) {
        *out_bytes = (uint8_t *)in.reply.result.address;
        *out_len = in.reply.result.size;
    }
    return KERN_SUCCESS;
}

/* Look the service up and PING it. Fills *channel; returns FMCP_CONNECT_OK on success. */
static inline int fmcp_connect(pid_t pid, fmcp_channel_t *channel) {
    memset(channel, 0, sizeof *channel);
    channel->service = MACH_PORT_NULL;
    char name[128];
    snprintf(name, sizeof name, "%s%d", FMCP_ATTACH_SERVICE_PREFIX, (int)pid);
    mach_port_t service = MACH_PORT_NULL;
    kern_return_t kr = bootstrap_look_up(bootstrap_port, name, &service);
    if (kr != KERN_SUCCESS || service == MACH_PORT_NULL) { channel->state = FMCP_CONNECT_ABSENT; return channel->state; }
    fmcp_reply_body_t body;
    uint8_t *bytes; uint64_t len;
    kr = fmcp_round_trip(service, FMCP_OP_PING, NULL, 0, &body, &bytes, &len);
    if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
    if (kr != KERN_SUCCESS) { mach_port_deallocate(mach_task_self(), service); channel->state = FMCP_CONNECT_NO_REPLY; return channel->state; }
    channel->library_status = body.status;
    channel->library_protocol = body.protocol_version;
    channel->pid = body.pid;
    channel->page_size = body.page_size;
    memcpy(channel->library_version, body.library_version, sizeof channel->library_version);
    channel->library_version[sizeof channel->library_version - 1] = '\0';
    if (body.protocol_version != FMCP_ATTACH_PROTOCOL_VERSION) { mach_port_deallocate(mach_task_self(), service); channel->state = FMCP_CONNECT_VERSION; return channel->state; }
    if (body.status != FMCP_ATTACH_OK || (pid_t)body.pid != pid) { mach_port_deallocate(mach_task_self(), service); channel->state = FMCP_CONNECT_REFUSED; return channel->state; }
    channel->service = service;
    channel->state = FMCP_CONNECT_OK;
    return channel->state;
}

static inline void fmcp_disconnect(fmcp_channel_t *channel) {
    if (channel->service != MACH_PORT_NULL) {
        mach_port_deallocate(mach_task_self(), channel->service);
        channel->service = MACH_PORT_NULL;
    }
}

/* "--route auto|injected|task-for-pid". */
enum { FMCP_PREFER_AUTO = 0, FMCP_PREFER_INJECTED = 1, FMCP_PREFER_TASK_FOR_PID = 2 };
static inline int fmcp_parse_prefer(const char *text) {
    if (text == NULL || text[0] == '\0' || strcmp(text, "auto") == 0) return FMCP_PREFER_AUTO;
    if (strcmp(text, "injected") == 0) return FMCP_PREFER_INJECTED;
    if (strcmp(text, "task-for-pid") == 0 || strcmp(text, "task_for_pid") == 0) return FMCP_PREFER_TASK_FOR_PID;
    return -1;
}

#endif
