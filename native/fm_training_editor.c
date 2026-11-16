/* One field only: stored regular PLAYER club training intensity at +1EB.
 * The Python adapter supplies its complete checked source readset. No arbitrary
 * destination or byte payload is accepted. Game execution is not suspended.
 */
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAX_GUARDS 8192
#define MAX_BYTES (4 * 1024 * 1024)
typedef struct { uint64_t address; uint32_t length; unsigned char *bytes; } Guard;

static int exact(void *dst, size_t length) {
    return fread(dst, 1, length, stdin) == length;
}
static int read_exact(task_t task, uint64_t address, void *out, size_t length) {
    mach_vm_size_t actual = 0;
    return mach_vm_read_overwrite(task, address, length,
        (mach_vm_address_t)out, &actual) == KERN_SUCCESS && actual == length;
}
static int valid_code(unsigned value) {
    return value <= 2 || value == 254 || value == 255;
}
int main(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 2;
    uint64_t player, table;
    uint32_t pid, count;
    unsigned char magic[8], before, after;
    if (!exact(magic, 8) || memcmp(magic, "FMTEDIT1", 8)
        || !exact(&pid, 4) || !pid || pid > INT32_MAX
        || !exact(&player, 8) || player < 4096 || player % 8
        || player > UINT64_MAX - 0x400 || !exact(&table, 8) || table < 4096 || table % 8
        || !exact(&before, 1) || !exact(&after, 1)
        || !valid_code(before) || !valid_code(after)
        || !exact(&count, 4) || !count || count > MAX_GUARDS) return 2;
    Guard *guards = calloc(count, sizeof(*guards));
    if (!guards) return 2;
    size_t total = 0;
    int result = 1, wrote = 0, matched_target = 0, matched_type = 0;
    const char *state = "invalid_request";
    task_t task = MACH_PORT_NULL;
    unsigned char buffer[16384];
    for (unsigned i = 0; i < count; ++i) {
        Guard *g = &guards[i];
        if (!exact(&g->address, 8) || !exact(&g->length, 4)
            || g->address < 4096 || !g->length || g->length > sizeof(buffer)
            || g->address > UINT64_MAX - g->length
            || (total += g->length) > MAX_BYTES) goto finish;
        g->bytes = malloc(g->length);
        if (!g->bytes || !exact(g->bytes, g->length)) goto finish;
        if (g->address == player && g->length == 8
            && !memcmp(g->bytes, &table, 8)) matched_type = 1;
        if (g->address <= player + 0x1eb && g->address + g->length > player + 0x1eb) {
            if (g->bytes[player + 0x1eb - g->address] != before) goto finish;
            matched_target = 1;
        }
    }
    if (fgetc(stdin) != EOF || !matched_target || !matched_type) goto finish;
    if (task_for_pid(mach_task_self(), (pid_t)pid, &task) != KERN_SUCCESS) {
        state = "attach_failed"; goto finish;
    }
    for (unsigned i = 0; i < count; ++i) {
        Guard *g = &guards[i];
        if (!read_exact(task, g->address, buffer, g->length)
            || memcmp(buffer, g->bytes, g->length)) {
            state = "source_changed_before_write"; goto finish;
        }
    }
    /* Repeat the type and target immediately beside the one-byte write. */
    uint64_t current_table;
    unsigned char current;
    if (!read_exact(task, player, &current_table, 8) || current_table != table
        || !read_exact(task, player + 0x1eb, &current, 1) || current != before) {
        state = "target_changed_before_write"; goto finish;
    }
    if (before != after) {
        kern_return_t kr = mach_vm_write(task, player + 0x1eb,
            (vm_offset_t)&after, 1);
        if (kr != KERN_SUCCESS) { state = "write_failed"; goto finish; }
        wrote = 1;
    }
    if (!read_exact(task, player + 0x1eb, &current, 1) || current != after) {
        state = "write_outcome_unverified"; goto finish;
    }
    for (unsigned i = 0; i < count; ++i) {
        Guard *g = &guards[i];
        if (!read_exact(task, g->address, buffer, g->length)) {
            state = "post_write_context_unverified"; goto finish;
        }
        for (unsigned j = 0; j < g->length; ++j) {
            unsigned char expected = g->address + j == player + 0x1eb ? after : g->bytes[j];
            if (buffer[j] != expected) {
                state = "post_write_context_changed"; goto finish;
            }
        }
    }
    state = before == after ? "already_set" : "stored_byte_verified";
    result = 0;
finish:
    printf("{\"ok\":%s,\"state\":\"%s\",\"write_performed\":%s,"
           "\"before_raw\":%u,\"after_raw\":%u,\"guards\":%u}\n",
           result == 0 ? "true" : "false", state, wrote ? "true" : "false", before, after, count);
    if (task != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), task);
    for (unsigned i = 0; i < count; ++i) free(guards[i].bytes);
    free(guards);
    return result;
}
