/* FM27 ARM64 read-only primitives. Layout is gated by the Python build fingerprint. */
#include <mach-o/dyld_images.h>
#include <mach-o/loader.h>

static bool read_exact(mach_port_t task, uint64_t address, void *out, size_t length) {
    mach_vm_size_t got = 0;
    return address != 0 && mach_vm_read_overwrite(task, address, length,
        (mach_vm_address_t)out, &got) == KERN_SUCCESS && got == length;
}

static uint64_t word64(const uint8_t *p) { uint64_t v; memcpy(&v, p, 8); return v; }
static uint32_t word32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }

static int run_images(pid_t pid, mach_port_t task) {
    struct task_dyld_info info;
    mach_msg_type_number_t count = TASK_DYLD_INFO_COUNT;
    struct { uint32_t version, count; uint64_t array; } header, after;
    if (task_info(task, TASK_DYLD_INFO, (task_info_t)&info, &count) != KERN_SUCCESS ||
        info.all_image_info_format != TASK_DYLD_ALL_IMAGE_INFO_64 ||
        !read_exact(task, info.all_image_info_addr, &header, sizeof(header)) ||
        !header.array || header.count > 4096) {
        printf("{\"ok\":false,\"command\":\"images\",\"pid\":%d,\"error\":\"Cannot read dyld image list\"}\n", pid);
        return 1;
    }
    struct { uint64_t address, path, modified; } *entries = calloc(header.count, 24);
    if (!entries || !read_exact(task, header.array, entries, header.count * 24) ||
        !read_exact(task, info.all_image_info_addr, &after, sizeof(after)) ||
        memcmp(&header, &after, sizeof(header))) {
        free(entries);
        printf("{\"ok\":false,\"command\":\"images\",\"pid\":%d,\"error\":\"Image list changed or unreadable\"}\n", pid);
        return 1;
    }
    printf("{\"ok\":true,\"command\":\"images\",\"pid\":%d,\"images\":[", pid);
    bool comma = false;
    for (uint32_t i = 0; i < header.count; i++) {
        char path[4096] = {0};
        /* Stop at NUL, avoiding reads across an unmapped page. */
        bool complete = false;
        for (size_t j = 0; j < sizeof(path)-1; j++) {
            if (!read_exact(task, entries[i].path+j, path+j, 1)) break;
            if (!path[j]) { complete = true; break; }
        }
        if (!complete || !strstr(path, "/game_plugin.bundle/Contents/MacOS/game_plugin")) continue;
        if (comma) putchar(',');
        printf("{\"address\":\"0x%llx\",\"path\":", (unsigned long long)entries[i].address);
        print_json_string(path); putchar('}'); comma = true;
    }
    free(entries);
    puts("]}");
    return 0;
}

static bool player_name(mach_port_t task, uint64_t handle, char name[129]) {
    uint64_t string = 0; uint32_t length = 0;
    if (!read_exact(task, handle, &string, 8) ||
        !read_exact(task, string, &length, 4) || length == 0 || length > 128 ||
        !read_exact(task, string+4, name, length+1) || name[length] != 0) return false;
    for (uint32_t i=0; i<length; i++) if ((unsigned char)name[i]<32) return false;
    return true;
}

/* All three PERSON name components are optional. A present but malformed
 * string still fails; null targets and terminated empty strings are absent. */
static bool optional_player_name(mach_port_t task, uint64_t handle, char name[129]) {
    uint64_t string; uint32_t length;
    if (!handle) return true;
    if (!read_exact(task, handle, &string, 8)) return false;
    if (!string) return true;
    if (!read_exact(task, string, &length, 4)) return false;
    if (!length) {
        char terminator;
        return read_exact(task, string+4, &terminator, 1) && !terminator;
    }
    return player_name(task, handle, name);
}

static bool ascii_contains(const char *text, const char *query) {
    for (; *text; text++) {
        size_t i=0;
        while (query[i] && text[i] && tolower((unsigned char)query[i]) == tolower((unsigned char)text[i])) i++;
        if (!query[i]) return true;
    }
    return !*query;
}

/* Returns -1 for an invalid selected field, 0 for a known nonmatch, 1 for
 * a match, 2 when fixed potential is unknown and all known criteria pass. */
static int player_filter(const uint8_t *record, size_t delta, const Options *o) {
    bool matches = true, unknown = false;
    for (size_t i = 0; i < o->player_filter_count; ++i) {
        PlayerFilter f = o->player_filters[i];
        int value;
        if (f.kind == 's') {
            int16_t raw; memcpy(&raw, record + f.offset, 2); value = raw;
            if (value < (f.offset == 0x25e ? -100 : 0) || value > 200) return -1;
            if (value < 0) { unknown = true; continue; }
        } else if (f.kind == 'd') {
            uint32_t raw = word32(record + f.offset + delta);
            unsigned year = raw >> 16, day = raw & 65535;
            bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
            if (year < 1850 || year > 2200 || day < 1 || day > (leap ? 366u : 365u)) return -1;
            value = (int)(year * 512 + day);
        } else {
            value = record[f.kind == 'p' ? 0x278 + delta + f.offset : f.offset];
            bool fifths = f.kind == 'r' && (record[0x270] & 0x80);
            if (value > (fifths ? 100 : 20)) return -1;
            if (fifths) { value = (value + 2) / 5; if (value < 1) value = 1; }
        }
        if (value < f.minimum || value > f.maximum) matches = false;
    }
    return !matches ? 0 : unknown ? 2 : 1;
}

static int emit_player(mach_port_t task, uint64_t address, uint64_t primary,
                        uint64_t playing, uint64_t person, const char *query,
                        bool comma, ScanStats *stats, bool staff, const Options *options) {
    size_t delta = staff ? 0xf8 : 0, size = staff ? 0x4a0 : 0x3a8;
    uint8_t record[0x4a0]; char first[129] = {0}, last[129] = {0}, common[129] = {0}, full[260];
    if ((address & 7) || !read_exact(task, address, record, size)) {
        stats->read_failures++; return false;
    }
    if (word64(record) != primary || word64(record+0x140) != playing ||
        word64(record+0x388+delta) != person || !word32(record+0x394+delta)
        || word32(record+0x390+delta) == UINT32_MAX) {
        stats->read_failures++; return false;
    }
    int filtered = player_filter(record, delta, options);
    if (filtered < 0) { stats->read_failures++; return false; }
    if (!filtered) return false;
    if (!optional_player_name(task,word64(record+0x298+delta),first) ||
        !optional_player_name(task,word64(record+0x2a0+delta),last) ||
        !optional_player_name(task,word64(record+0x2a8+delta),common)) { stats->read_failures++; return 0; }
    snprintf(full,sizeof(full),"%s%s%s",first,first[0] && last[0] ? " " : "",last);
    if (!full[0] && !common[0]) return -1;
    if (!ascii_contains(full,query) && !ascii_contains(common,query)) return 0;
    if (options->query_players) {
        uint8_t after[0x4a0];
        if (!read_exact(task, address, after, size) || memcmp(record, after, size)) {
            stats->read_failures++; return false;
        }
    }
    if (comma) putchar(',');
    printf("{\"address\":\"0x%llx\",\"first_name\":",(unsigned long long)address);
    print_json_string(first); fputs(",\"last_name\":",stdout); print_json_string(last);
    if (options->query_players) printf(",\"filter_state\":\"%s\"", filtered == 2 ? "unknown_potential" : "match");
    fputs("}",stdout);
    return true;
}

/* Read staff PERSON_DATA names without calling game getters. Null name targets
 * occur on inactive human records and are reported separately by the iterator. */
static int emit_staff(mach_port_t task, uint64_t address, uint64_t person,
                      uint64_t primary, const char *query, bool comma, ScanStats *stats) {
    uint64_t table, handles[3]; char names[3][129] = {{0}}, full[260];
    if (!read_exact(task, address, &table, 8) || table != primary
        || !read_exact(task, person - 0xf0, handles, sizeof(handles))) {
        stats->read_failures++; return 0;
    }
    for (size_t j = 0; j < 3; ++j) {
        if (!handles[j]) continue;
        uint64_t string; uint32_t length;
        if (!read_exact(task, handles[j], &string, 8)) { stats->read_failures++; return 0; }
        if (!string) continue;
        if (!read_exact(task, string, &length, 4)) { stats->read_failures++; return 0; }
        if (length == 0) {
            char terminator;
            if (!read_exact(task, string + 4, &terminator, 1) || terminator) stats->read_failures++;
            continue;
        }
        if (!player_name(task, handles[j], names[j])) { stats->read_failures++; return 0; }
    }
    snprintf(full, sizeof(full), "%s%s%s", names[0], names[0][0] && names[1][0] ? " " : "", names[1]);
    if (!full[0] && !names[2][0]) return -1;
    if (!ascii_contains(full, query) && !ascii_contains(names[2], query)) return 0;
    if (comma) putchar(',');
    printf("{\"address\":\"0x%llx\"}", (unsigned long long)address);
    return 1;
}

static bool club_name(mach_port_t task, uint64_t string, char name[513]) {
    uint32_t length;
    if (!read_exact(task, string, &length, 4) || !length || length > 512
        || !read_exact(task, string + 4, name, length + 1) || name[length]) return false;
    for (uint32_t i = 0; i < length; ++i)
        if ((unsigned char)name[i] < 32 || (unsigned char)name[i] == 127) return false;
    return true;
}

static bool emit_club(mach_port_t task, uint64_t address, const char *query,
                       bool comma, ScanStats *stats) {
    uint64_t strings[2]; char full[513], short_name[513];
    if (!read_exact(task, address + 0xc0, strings, sizeof(strings))
        || !club_name(task, strings[0], full) || !club_name(task, strings[1], short_name)) {
        stats->read_failures++; return false;
    }
    if (!ascii_contains(full, query) && !ascii_contains(short_name, query)) return false;
    if (comma) putchar(',');
    printf("{\"address\":\"0x%llx\",\"name\":", (unsigned long long)address);
    print_json_string(full); fputs(",\"short_name\":", stdout); print_json_string(short_name);
    putchar('}');
    return true;
}

static int run_entity_index(const Options *o, mach_port_t task) {
    bool clubs = strcmp(o->command, "scan-club-index") == 0;
    bool staff_search = strcmp(o->command, "scan-staff-index") == 0;
    uint64_t header[3], after[3];
    if (!read_exact(task, o->list_header, header, sizeof(header))
        || header[0] != o->list_start || header[0] % 8 || header[1] % 8 || header[2] % 8
        || header[1] < header[0] || header[2] < header[1]
        || (header[1] - header[0]) != o->list_count * 8
        || header[2] - header[0] > 2000000 * 8) {
        printf("{\"ok\":false,\"pid\":%d,\"command\":\"%s\",\"error\":\"Entity table bounds changed\"}\n", o->pid, o->command);
        return 1;
    }
    uint64_t i = o->start_index, scanned = 0, other = 0, actual = 0, player_staff = 0, unavailable_names = 0;
    ScanStats stats = {0};
    bool valid = true;
    printf("{\"pid\":%d,\"command\":\"%s\",\"matches\":[", o->pid, o->command);
    while (i < o->list_count && scanned < o->record_budget && stats.matches < o->max_matches) {
        uint64_t entries[256], recheck[256];
        size_t n = (size_t)(o->list_count - i);
        if (n > 256) n = 256;
        if (n > o->record_budget - scanned) n = (size_t)(o->record_budget - scanned);
        uint64_t chunk = header[0] + i * 8;
        if (!read_exact(task, chunk, entries, n * 8)) { valid = false; break; }
        size_t used = 0;
        for (; used < n && stats.matches < o->max_matches; ++used, ++i, ++scanned) {
            uint8_t person[20];
            if (entries[used] < 4096 || entries[used] % 8
                || !read_exact(task, entries[used], person, sizeof(person))
                || word32(person + 8) != i) { valid = false; break; }
            bool staff = !clubs && o->player_staff_person && word64(person) == o->player_staff_person;
            bool human = staff_search && o->human_person && word64(person) == o->human_person;
            if (!staff && !human && word64(person) != (clubs ? o->player_primary : o->player_person)) { ++other; continue; }
            ++actual;
            if (staff) ++player_staff;
            /* DATABASE_RECORD duni/rdui are independent, including CLUB. */
            if (!word32(person + 12)) {
                valid = false; break;
            }
            uint64_t staff_offset = staff ? 0x480 : human ? 0x548 : 0x208;
            uint64_t staff_primary = staff ? o->player_staff_primary : human ? o->human_primary : o->player_primary;
            int staff_match = staff_search ? emit_staff(task, entries[used] - staff_offset,
                entries[used], staff_primary, o->player_query, stats.matches > 0, &stats) : 0;
            if (staff_match < 0) ++unavailable_names;
            int player_match = staff_search ? staff_match : clubs ? emit_club(task, entries[used], o->player_query,
                                             stats.matches > 0, &stats)
                                 : emit_player(task, entries[used] - (staff ? 0x480 : 0x388),
                            staff ? o->player_staff_primary : o->player_primary, o->player_playing,
                            staff ? o->player_staff_person : o->player_person, o->player_query,
                            stats.matches > 0, &stats, staff, o);
            if (!staff_search && player_match < 0) ++unavailable_names;
            if (player_match == 1) ++stats.matches;
            if (stats.read_failures) { valid = false; break; }
        }
        if (!valid || !read_exact(task, chunk, recheck, used * 8)
            || memcmp(entries, recheck, used * 8)) { valid = false; break; }
    }
    if (!read_exact(task, o->list_header, after, sizeof(after))
        || memcmp(header, after, sizeof(header))) valid = false;
    printf("],\"unavailable_name_records\":%llu,\"player_staff_examined\":%llu,\"ok\":%s,\"error\":%s,\"next_index\":%llu,\"scanned_records\":%llu,"
           "\"%s\":%llu,\"%s\":%llu,"
           "\"stop_reason\":\"%s\"}\n", (unsigned long long)unavailable_names, (unsigned long long)player_staff, valid ? "true" : "false",
           valid ? "null" : "\"Entity index read, type or identity check failed\"",
           (unsigned long long)i, (unsigned long long)scanned,
           clubs ? "clubs_examined" : staff_search ? "staff_examined" : "actual_players_examined", (unsigned long long)actual,
           clubs ? "other_club_records" : "other_person_records", (unsigned long long)other,
           !valid ? "read_or_identity_changed" : i == o->list_count ? "table_end"
           : stats.matches >= o->max_matches ? "match_limit" : "record_budget");
    return valid ? 0 : 1;
}
