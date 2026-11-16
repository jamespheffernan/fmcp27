/* Read-only TEAM_BASE assignment scan. The Python caller pins code and RTTI. */
static bool team_table_header(mach_port_t task, uint64_t address, uint64_t header[3]) {
    if (!read_exact(task, address, header, 24)) return false;
    if (!header[0] && !header[1] && !header[2]) return true;
    return header[0] >= 4096 && !(header[0] % 8) && !(header[1] % 8) && !(header[2] % 8)
        && header[0] <= header[1] && header[1] <= header[2] && header[2] - header[0] <= 2000000 * 8;
}

static int run_team_index(const Options *o, mach_port_t task) {
    uint64_t canonical[3], lookup[3], after[3];
    if (!team_table_header(task, o->list_header, canonical)
        || canonical[0] != o->list_start || (canonical[1] - canonical[0]) / 8 != o->list_count
        || !team_table_header(task, o->lookup_header, lookup)) {
        printf("{\"ok\":false,\"pid\":%d,\"command\":\"scan-team-index\",\"error\":\"Team table bounds changed\"}\n", o->pid);
        return 1;
    }
    uint64_t lookup_count = (lookup[1] - lookup[0]) / 8;
    uint64_t i = o->start_index, scanned = 0, matched = 0, actual = 0, national = 0, unavailable = 0;
    bool valid = true;
    printf("{\"pid\":%d,\"command\":\"scan-team-index\",\"matches\":[", o->pid);
    while (i < o->list_count && scanned < o->record_budget && matched < o->max_matches) {
        uint64_t entries[256], selected[256], recheck[256];
        size_t n = (size_t)(o->list_count - i);
        if (n > 256) n = 256;
        if (n > o->record_budget - scanned) n = (size_t)(o->record_budget - scanned);
        uint64_t chunk_index = i;
        size_t selected_count = i < lookup_count ? (size_t)(lookup_count - i) : 0;
        if (selected_count > n) selected_count = n;
        if (!read_exact(task, canonical[0] + i * 8, entries, n * 8)
            || (selected_count && !read_exact(task, lookup[0] + i * 8, selected, selected_count * 8))) {
            valid = false; break;
        }
        size_t used = 0;
        for (; used < n && matched < o->max_matches; ++used, ++i, ++scanned) {
            if (used >= selected_count) { ++unavailable; continue; }
            uint8_t record[0x78], again[0x78];
            if (entries[used] != selected[used] || entries[used] < 4096 || entries[used] % 8
                || !read_exact(task, entries[used], record, sizeof(record))
                || word32(record + 8) != i || !word32(record + 12)
                || (word64(record) != o->team_primary && word64(record) != o->national_team_primary)) {
                valid = false; break;
            }
            ++actual;
            if (word64(record) == o->national_team_primary) ++national;
            unsigned offset = o->team_assignment >= 2 ? 0x68 : 0x50;
            uint64_t competition = word64(record + offset);
            if ((o->team_assignment & 1) && word64(record + offset + 8)) competition = word64(record + offset + 8);
            bool match = competition == o->competition;
            /* Native current-primary branch requires an owner; the next-primary
             * and secondary branches compare assignments directly. */
            if (o->team_assignment == 0 && !word64(record + 0x30)) match = false;
            if (!read_exact(task, entries[used], again, sizeof(again)) || memcmp(record, again, sizeof(record))) {
                valid = false; break;
            }
            if (match) {
                if (matched) putchar(',');
                printf("{\"address\":\"0x%llx\",\"database_index\":%llu}",
                       (unsigned long long)entries[used], (unsigned long long)i);
                ++matched;
            }
        }
        size_t selected_used = used < selected_count ? used : selected_count;
        if (!valid || !read_exact(task, canonical[0] + chunk_index * 8, recheck, used * 8)
            || memcmp(entries, recheck, used * 8)
            || (selected_used && (!read_exact(task, lookup[0] + chunk_index * 8, recheck, selected_used * 8)
                                 || memcmp(selected, recheck, selected_used * 8)))) { valid = false; break; }
    }
    if (!read_exact(task, o->list_header, after, 24) || memcmp(canonical, after, 24)
        || !read_exact(task, o->lookup_header, after, 24) || memcmp(lookup, after, 24)) valid = false;
    printf("],\"ok\":%s,\"error\":%s,\"next_index\":%llu,\"scanned_records\":%llu,"
           "\"teams_examined\":%llu,\"national_teams_examined\":%llu,\"lookup_unavailable_records\":%llu,\"stop_reason\":\"%s\"}\n",
           valid ? "true" : "false", valid ? "null" : "\"Team index read, lookup or identity check failed\"",
           (unsigned long long)i, (unsigned long long)scanned, (unsigned long long)actual,
           (unsigned long long)national, (unsigned long long)unavailable,
           !valid ? "read_or_identity_changed" : i == o->list_count ? "table_end"
           : matched >= o->max_matches ? "match_limit" : "record_budget");
    return valid ? 0 : 1;
}
