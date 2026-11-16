/*
 * fm_live_helper_attach.h: the injected attach route for fm_live_helper.
 *
 * fm_live_helper used to reach the game only through task_for_pid, which the
 * kernel refuses on a Mac with default System Integrity Protection. When the
 * game was started with the FMCP launcher, the in-game library
 * (native/fmcp_attach_lib.c) answers reads and a region list over a Mach
 * channel instead (native/fmcp_attach.h). This header gives the helper that
 * route without changing the library or its protocol:
 *
 *   - reads go to the channel's READV;
 *   - the region walk uses the channel's REGIONS list. The list has no share
 *     mode, so that one field comes from proc_pidinfo(PROC_PIDREGIONINFO),
 *     which needs the same user and no task port. When the kernel will not
 *     answer, the region counts as private (a scan then covers more, never
 *     less);
 *   - the loaded game plugin is found by walking the executable regions for a
 *     Mach-O bundle header. Its path comes from proc_regionfilename; when that
 *     is unavailable, from the game's own bundle layout, accepted only if the
 *     UUID in memory equals the UUID of that file on disk.
 *
 * Include it after print_json_string is defined and before any code that
 * reads: the two macros at the end redirect mach_vm_read_overwrite and
 * mach_vm_region_recurse for the rest of the translation unit. With
 * g_injected false both shims call the real functions, so the task_for_pid
 * route is unchanged.
 *
 * FMCP_ATTACH_ROUTE=auto|injected|task-for-pid selects the route, as it does
 * for fm_fast_reader. FMCP_ATTACH_NO_PROC_INFO=1 makes the injected route act
 * as if the kernel refused both proc_info calls (used by the tests).
 */
#ifndef FM_LIVE_HELPER_ATTACH_H
#define FM_LIVE_HELPER_ATTACH_H

#include <fcntl.h>
#include <libkern/OSByteOrder.h>
#include <libproc.h>
#include <mach-o/fat.h>
#include <mach-o/loader.h>
#include <stddef.h>
#include <sys/proc_info.h>

#include "fmcp_attach_client.h"

#define FH_READ_PIECE (8ULL * 1024ULL * 1024ULL) /* under the channel's 16 MiB item limit */
#define FH_PLUGIN_NEEDLE "/game_plugin.bundle/Contents/MacOS/game_plugin"
#define FH_PLUGIN_IN_APP "/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin"
#define FH_MAX_LOAD_COMMAND_BYTES (256u * 1024u)

static fmcp_channel_t g_channel;
static bool g_injected = false;
static pid_t g_injected_pid = 0;
static bool g_no_proc_info = false;
static fmcp_region_t *g_regions = NULL;
static uint32_t g_region_count = 0;
static bool g_regions_loaded = false;

static kern_return_t fh_read_overwrite(mach_port_t task, mach_vm_address_t address, mach_vm_size_t size,
                                       mach_vm_address_t data, mach_vm_size_t *out_size) {
    if (!g_injected) return mach_vm_read_overwrite(task, address, size, data, out_size);
    *out_size = 0;
    mach_vm_size_t done = 0;
    while (done < size) {
        mach_vm_size_t piece = size - done;
        if (piece > FH_READ_PIECE) piece = FH_READ_PIECE;
        fmcp_item_t item = {address + done, (uint32_t)piece};
        fmcp_reply_body_t body;
        uint8_t *bytes = NULL;
        uint64_t len = 0;
        kern_return_t kr = fmcp_round_trip(g_channel.service, FMCP_OP_READV, &item, 1, &body, &bytes, &len);
        /* All or nothing, as mach_vm_read_overwrite: a partial item is a failed read. */
        bool ok = kr == KERN_SUCCESS && body.status == FMCP_ATTACH_OK && body.count == 1
            && bytes != NULL && len >= sizeof(fmcp_result_t) + piece;
        if (ok) {
            fmcp_result_t result;
            memcpy(&result, bytes, sizeof result);
            ok = result.status == FMCP_ITEM_OK && result.length == piece;
            if (ok) memcpy((void *)(uintptr_t)(data + done), bytes + sizeof result, (size_t)piece);
        }
        if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
        if (!ok) return kr != KERN_SUCCESS ? kr : KERN_INVALID_ADDRESS;
        done += piece;
    }
    *out_size = size;
    return KERN_SUCCESS;
}

static int fh_region_order(const void *a, const void *b) {
    uint64_t left = ((const fmcp_region_t *)a)->start, right = ((const fmcp_region_t *)b)->start;
    return left < right ? -1 : left > right;
}

/* One REGIONS snapshot per helper process: a helper runs one command and exits. */
static bool fh_load_regions(void) {
    if (g_regions_loaded) return g_regions != NULL;
    g_regions_loaded = true;
    fmcp_reply_body_t body;
    uint8_t *bytes = NULL;
    uint64_t len = 0;
    kern_return_t kr = fmcp_round_trip(g_channel.service, FMCP_OP_REGIONS, NULL, 0, &body, &bytes, &len);
    if (kr == KERN_SUCCESS && body.status == FMCP_ATTACH_OK && bytes != NULL && body.count > 0
        && len >= (uint64_t)body.count * sizeof(fmcp_region_t)) {
        g_regions = malloc((size_t)body.count * sizeof(fmcp_region_t));
        if (g_regions != NULL) {
            memcpy(g_regions, bytes, (size_t)body.count * sizeof(fmcp_region_t));
            g_region_count = body.count;
            qsort(g_regions, g_region_count, sizeof(fmcp_region_t), fh_region_order);
        }
    }
    if (bytes) mach_vm_deallocate(mach_task_self(), (mach_vm_address_t)bytes, len);
    return g_regions != NULL;
}

static unsigned char fh_share_mode(uint64_t start) {
    if (!g_no_proc_info) {
        struct proc_regioninfo info;
        int got = proc_pidinfo(g_injected_pid, PROC_PIDREGIONINFO, start, &info, (int)sizeof info);
        if (got == (int)sizeof info && info.pri_address <= start && start - info.pri_address < info.pri_size) {
            return (unsigned char)info.pri_share_mode;
        }
    }
    return SM_PRIVATE;
}

/* The first region ending above *address, as a leaf (the channel lists no submaps). */
static kern_return_t fh_region_recurse(mach_port_t task, mach_vm_address_t *address, mach_vm_size_t *size,
                                       natural_t *depth, vm_region_recurse_info_t info_out,
                                       mach_msg_type_number_t *count) {
    if (!g_injected) return mach_vm_region_recurse(task, address, size, depth, info_out, count);
    if (!fh_load_regions()) return KERN_FAILURE;
    uint32_t low = 0, high = g_region_count;
    while (low < high) {
        uint32_t middle = low + (high - low) / 2;
        if (g_regions[middle].start + g_regions[middle].size > *address) high = middle;
        else low = middle + 1;
    }
    if (low == g_region_count) return KERN_INVALID_ADDRESS;
    const fmcp_region_t *region = &g_regions[low];
    vm_region_submap_info_data_64_t *info = (vm_region_submap_info_data_64_t *)info_out;
    memset(info, 0, sizeof *info);
    info->protection = (vm_prot_t)region->protection;
    info->max_protection = (vm_prot_t)region->max_protection;
    info->user_tag = region->user_tag;
    info->pages_resident = region->pages_resident;
    info->share_mode = fh_share_mode(region->start);
    *address = region->start;
    *size = region->size;
    return KERN_SUCCESS;
}

static bool fh_read_exact(uint64_t address, void *out, size_t length) {
    mach_vm_size_t got = 0;
    return fh_read_overwrite(MACH_PORT_NULL, address, length, (mach_vm_address_t)(uintptr_t)out, &got) == KERN_SUCCESS
        && got == length;
}

/* LC_UUID from a thin 64-bit Mach-O header followed by its load commands. */
static bool fh_uuid_in_commands(const uint8_t *commands, uint32_t ncmds, uint32_t sizeofcmds, uint8_t uuid[16]) {
    uint32_t offset = 0;
    for (uint32_t i = 0; i < ncmds && offset + sizeof(struct load_command) <= sizeofcmds; i++) {
        struct load_command command;
        memcpy(&command, commands + offset, sizeof command);
        if (command.cmdsize < sizeof command || command.cmdsize > sizeofcmds - offset) return false;
        if (command.cmd == LC_UUID && command.cmdsize >= sizeof(struct uuid_command)) {
            memcpy(uuid, commands + offset + offsetof(struct uuid_command, uuid), 16);
            return true;
        }
        offset += command.cmdsize;
    }
    return false;
}

static bool fh_memory_uuid(uint64_t base, const struct mach_header_64 *header, uint8_t uuid[16]) {
    if (header->sizeofcmds == 0 || header->sizeofcmds > FH_MAX_LOAD_COMMAND_BYTES) return false;
    uint8_t *commands = malloc(header->sizeofcmds);
    bool found = commands != NULL && fh_read_exact(base + sizeof *header, commands, header->sizeofcmds)
        && fh_uuid_in_commands(commands, header->ncmds, header->sizeofcmds, uuid);
    free(commands);
    return found;
}

/* LC_UUID of the arm64 slice of a file on disk (thin or universal). */
static bool fh_disk_uuid(const char *path, uint8_t uuid[16]) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return false;
    bool found = false;
    uint8_t *commands = NULL;
    uint8_t head[4096];
    off_t slice = 0;
    ssize_t got = pread(fd, head, sizeof head, 0);
    if (got < (ssize_t)sizeof(struct fat_header)) goto done;
    uint32_t magic;
    memcpy(&magic, head, 4);
    if (magic == FAT_CIGAM || magic == FAT_CIGAM_64) {
        bool wide = magic == FAT_CIGAM_64;
        uint32_t count = OSSwapBigToHostInt32(((struct fat_header *)(void *)head)->nfat_arch);
        size_t each = wide ? sizeof(struct fat_arch_64) : sizeof(struct fat_arch);
        bool located = false;
        for (uint32_t i = 0; i < count && sizeof(struct fat_header) + (i + 1) * each <= (size_t)got; i++) {
            const uint8_t *entry = head + sizeof(struct fat_header) + i * each;
            uint32_t cputype;
            memcpy(&cputype, entry, 4);
            if ((cpu_type_t)OSSwapBigToHostInt32(cputype) != CPU_TYPE_ARM64) continue;
            if (wide) { uint64_t offset; memcpy(&offset, entry + 8, 8); slice = (off_t)OSSwapBigToHostInt64(offset); }
            else { uint32_t offset; memcpy(&offset, entry + 8, 4); slice = (off_t)OSSwapBigToHostInt32(offset); }
            located = true;
            break;
        }
        if (!located) goto done;
    }
    struct mach_header_64 header;
    if (pread(fd, &header, sizeof header, slice) != (ssize_t)sizeof header || header.magic != MH_MAGIC_64
        || header.sizeofcmds == 0 || header.sizeofcmds > FH_MAX_LOAD_COMMAND_BYTES) goto done;
    commands = malloc(header.sizeofcmds);
    if (commands == NULL
        || pread(fd, commands, header.sizeofcmds, slice + (off_t)sizeof header) != (ssize_t)header.sizeofcmds) goto done;
    found = fh_uuid_in_commands(commands, header.ncmds, header.sizeofcmds, uuid);
done:
    free(commands);
    close(fd);
    return found;
}

/* The same answer as run_images (player_reader.h), without a task port. */
static int run_images_injected(pid_t pid) {
    char expected[PROC_PIDPATHINFO_MAXSIZE + sizeof FH_PLUGIN_IN_APP] = {0};
    uint8_t expected_uuid[16];
    bool have_expected = false;
    char executable[PROC_PIDPATHINFO_MAXSIZE] = {0};
    if (proc_pidpath(pid, executable, sizeof executable) > 0) {
        char *macos = strstr(executable, "/Contents/MacOS/");
        if (macos != NULL) {
            *macos = '\0';
            snprintf(expected, sizeof expected, "%s%s", executable, FH_PLUGIN_IN_APP);
            have_expected = fh_disk_uuid(expected, expected_uuid);
        }
    }
    if (!fh_load_regions()) {
        printf("{\"ok\":false,\"command\":\"images\",\"pid\":%d,\"error\":\"Cannot read the region list\"}\n", pid);
        return 1;
    }
    printf("{\"ok\":true,\"command\":\"images\",\"pid\":%d,\"images\":[", pid);
    bool comma = false;
    for (uint32_t i = 0; i < g_region_count; i++) {
        const fmcp_region_t *region = &g_regions[i];
        if ((region->protection & (VM_PROT_READ | VM_PROT_EXECUTE)) != (VM_PROT_READ | VM_PROT_EXECUTE)
            || region->size < sizeof(struct mach_header_64)) continue;
        struct mach_header_64 header;
        if (!fh_read_exact(region->start, &header, sizeof header) || header.magic != MH_MAGIC_64
            || header.filetype != MH_BUNDLE) continue;
        char path[PROC_PIDPATHINFO_MAXSIZE] = {0};
        const char *chosen = NULL;
        if (!g_no_proc_info && proc_regionfilename(pid, region->start, path, sizeof path) > 0
            && strstr(path, FH_PLUGIN_NEEDLE) != NULL) {
            chosen = path;
        } else if (have_expected) {
            uint8_t loaded_uuid[16];
            if (fh_memory_uuid(region->start, &header, loaded_uuid) && memcmp(loaded_uuid, expected_uuid, 16) == 0) {
                chosen = expected;
            }
        }
        if (chosen == NULL) continue;
        if (comma) putchar(',');
        printf("{\"address\":\"0x%llx\",\"path\":", (unsigned long long)region->start);
        print_json_string(chosen);
        putchar('}');
        comma = true;
    }
    puts("]}");
    return 0;
}

/*
 * Attach for one command. Returns true with either g_injected set or *task
 * holding a task port. On failure it has printed the JSON error.
 */
static bool fh_attach(const char *command, pid_t pid, mach_port_t *task) {
    *task = MACH_PORT_NULL;
    const char *no_proc_info = getenv("FMCP_ATTACH_NO_PROC_INFO");
    g_no_proc_info = no_proc_info != NULL && strcmp(no_proc_info, "1") == 0;
    int prefer = fmcp_parse_prefer(getenv("FMCP_ATTACH_ROUTE"));
    if (prefer < 0) {
        printf("{\"ok\":false,\"command\":");
        print_json_string(command);
        printf(",\"pid\":%d,\"attach_ok\":false,\"error\":{\"code\":\"invalid_attach_route\"},\"warnings\":[]}\n", pid);
        return false;
    }
    int state = FMCP_CONNECT_ABSENT;
    if (prefer != FMCP_PREFER_TASK_FOR_PID) {
        state = fmcp_connect(pid, &g_channel);
        if (state == FMCP_CONNECT_OK) {
            g_injected = true;
            g_injected_pid = pid;
            return true;
        }
    }
    kern_return_t kr = KERN_FAILURE;
    if (prefer != FMCP_PREFER_INJECTED) {
        kr = task_for_pid(mach_task_self(), pid, task);
        if (kr == KERN_SUCCESS) return true;
    }
    printf("{\"ok\":false,\"command\":");
    print_json_string(command);
    printf(",\"pid\":%d,\"attach_ok\":false,\"error\":{\"code\":", pid);
    if (prefer == FMCP_PREFER_INJECTED) {
        printf("\"attach_library_%s\"", fmcp_connect_name(state));
    } else {
        printf("\"task_for_pid_failed\",\"mach_code\":%d,\"mach_message\":", kr);
        print_json_string(mach_error_string(kr));
        if (prefer == FMCP_PREFER_AUTO) printf(",\"attach_library\":\"%s\"", fmcp_connect_name(state));
    }
    printf(",\"hint\":\"Quit Football Manager and start it from Steam with the FMCP 27 launch line in its Launch Options.\"}"
           ",\"warnings\":[%s]}\n",
           prefer == FMCP_PREFER_INJECTED ? "" : "\"helper_requires_com.apple.security.cs.debugger\"");
    return false;
}

#define mach_vm_read_overwrite fh_read_overwrite
#define mach_vm_region_recurse fh_region_recurse

#endif
