#include <ctype.h>
#include <errno.h>
#include <poll.h>
#include <mach/mach.h>
#include <mach/mach_error.h>
#include <mach/mach_vm.h>
#include <mach/vm_region.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MAX_NEEDLES 64
#define DEFAULT_MAX_BYTES (512ULL * 1024ULL * 1024ULL)
#define DEFAULT_CHUNK_SIZE (1024ULL * 1024ULL)
#define DEFAULT_MAX_MATCHES 64
#define CONTEXT_BYTES 48
#define MAX_PLAYER_FILTERS 96

typedef struct { char kind; unsigned offset; int minimum, maximum; } PlayerFilter;

typedef struct {
    char *value;
    uint8_t *utf8;
    size_t utf8_len;
    uint8_t *utf16le;
    size_t utf16le_len;
} Needle;

typedef struct {
    const char *command;
    pid_t pid;
    Needle needles[MAX_NEEDLES];
    size_t needle_count;
    uint64_t max_bytes;
    uint64_t chunk_size;
    uint64_t max_matches;
    bool private_only;
    bool writable_only;
    uint64_t start_address;
    uint64_t player_primary, player_playing, player_person;
    uint64_t player_staff_primary, player_staff_person, human_primary, human_person;
    uint64_t list_header, list_start, list_count, start_index, record_budget;
    uint64_t team_primary, national_team_primary, competition, lookup_header;
    unsigned team_assignment;
    bool team_assignment_set;
    const char *player_query;
    bool query_players;
    PlayerFilter player_filters[MAX_PLAYER_FILTERS];
    size_t player_filter_count;
    mach_port_t task;
} Options;

typedef struct {
    uint64_t regions_seen;
    uint64_t regions_readable;
    uint64_t regions_writable;
    uint64_t regions_private;
    uint64_t regions_scanned;
    uint64_t bytes_read;
    uint64_t read_failures;
    uint64_t matches;
} ScanStats;

static void print_json_string(const char *text) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)text; *p != '\0'; ++p) {
        switch (*p) {
            case '\\':
                fputs("\\\\", stdout);
                break;
            case '"':
                fputs("\\\"", stdout);
                break;
            case '\b':
                fputs("\\b", stdout);
                break;
            case '\f':
                fputs("\\f", stdout);
                break;
            case '\n':
                fputs("\\n", stdout);
                break;
            case '\r':
                fputs("\\r", stdout);
                break;
            case '\t':
                fputs("\\t", stdout);
                break;
            default:
                if (*p < 0x20) {
                    printf("\\u%04x", *p);
                } else {
                    putchar(*p);
                }
                break;
        }
    }
    putchar('"');
}

#include "fm_live_helper_attach.h"
#include "player_reader.h"
#include "team_reader.h"

static void usage(void) {
    fputs(
        "usage: fm_live_helper <probe|images|scan-session|read-bytes> --pid PID "
        "[--needle TEXT ...] [--max-bytes N] [--chunk-size N] "
        "[--max-matches N] [--private-only]\n",
        stderr
    );
}

static bool parse_u64(const char *text, uint64_t *out) {
    char *end = NULL;
    unsigned long long value = strtoull(text, &end, 10);
    if (end == text || *end != '\0') {
        return false;
    }
    *out = (uint64_t)value;
    return true;
}

static bool is_ascii(const char *text) {
    for (const unsigned char *p = (const unsigned char *)text; *p != '\0'; ++p) {
        if (*p >= 0x80) {
            return false;
        }
    }
    return true;
}

static bool add_needle(Options *options, const char *value) {
    if (options->needle_count >= MAX_NEEDLES || value == NULL || value[0] == '\0') {
        return false;
    }
    Needle *needle = &options->needles[options->needle_count];
    memset(needle, 0, sizeof(*needle));
    needle->value = strdup(value);
    if (needle->value == NULL) {
        return false;
    }
    needle->utf8_len = strlen(value);
    needle->utf8 = (uint8_t *)strdup(value);
    if (needle->utf8 == NULL) {
        return false;
    }
    if (is_ascii(value)) {
        needle->utf16le_len = needle->utf8_len * 2;
        needle->utf16le = calloc(needle->utf16le_len, 1);
        if (needle->utf16le == NULL) {
            return false;
        }
        for (size_t i = 0; i < needle->utf8_len; ++i) {
            needle->utf16le[i * 2] = needle->utf8[i];
        }
    }
    options->needle_count++;
    return true;
}

/* Add a binary needle from a hex string ("02400FFE..."). No UTF-16 expansion,
 * no transforms — exact bytes only. Used for structural anchors like the
 * STAFF_FAMILY_MARKER. */
static bool add_hex_needle(Options *options, const char *hex) {
    if (options->needle_count >= MAX_NEEDLES || hex == NULL) {
        return false;
    }
    /* Allow optional 0x prefix and ignore spaces. */
    if (hex[0] == '0' && (hex[1] == 'x' || hex[1] == 'X')) {
        hex += 2;
    }
    size_t hex_len = strlen(hex);
    /* Count actual hex digits to size allocation. */
    size_t digits = 0;
    for (size_t i = 0; i < hex_len; ++i) {
        if (!isspace((unsigned char)hex[i])) digits++;
    }
    if (digits == 0 || (digits % 2) != 0) {
        return false;
    }
    size_t byte_len = digits / 2;
    uint8_t *bytes = malloc(byte_len);
    if (bytes == NULL) return false;
    size_t out_idx = 0;
    int high = -1;
    for (size_t i = 0; i < hex_len; ++i) {
        char c = hex[i];
        if (isspace((unsigned char)c)) continue;
        int v;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'a' && c <= 'f') v = 10 + (c - 'a');
        else if (c >= 'A' && c <= 'F') v = 10 + (c - 'A');
        else { free(bytes); return false; }
        if (high < 0) {
            high = v;
        } else {
            bytes[out_idx++] = (uint8_t)((high << 4) | v);
            high = -1;
        }
    }
    Needle *needle = &options->needles[options->needle_count];
    memset(needle, 0, sizeof(*needle));
    /* Store the original hex string as 'value' for JSON output. */
    needle->value = strdup(hex);
    if (needle->value == NULL) { free(bytes); return false; }
    needle->utf8 = bytes;
    needle->utf8_len = byte_len;
    /* No utf16le for binary needles — leave NULL. */
    options->needle_count++;
    return true;
}

static void free_needles(Options *options) {
    for (size_t i = 0; i < options->needle_count; ++i) {
        free(options->needles[i].value);
        free(options->needles[i].utf8);
        free(options->needles[i].utf16le);
    }
}

static uint64_t max_encoded_needle_len(const Options *options) {
    uint64_t max_len = 0;
    for (size_t i = 0; i < options->needle_count; ++i) {
        if (options->needles[i].utf8_len > max_len) {
            max_len = options->needles[i].utf8_len;
        }
        if (options->needles[i].utf16le_len > max_len) {
            max_len = options->needles[i].utf16le_len;
        }
    }
    return max_len;
}

static bool add_player_filter(Options *o, const char *text) {
    if (strlen(text) < 7 || strlen(text) > 40 || text[1] != ':'
        || o->player_filter_count >= MAX_PLAYER_FILTERS) return false;
    unsigned long values[3]; const char *at = text + 2;
    for (size_t i = 0; i < 3; ++i) {
        if (*at < '0' || *at > '9') return false;
        char *end; errno = 0;
        values[i] = strtoul(at, &end, 10);
        if (errno || values[i] > 2000000 || *end != (i < 2 ? ':' : '\0')) return false;
        at = end + (i < 2 ? 1 : 0);
    }
    PlayerFilter f = {text[0], (unsigned)values[0], (int)values[1], (int)values[2]};
    if (f.maximum < f.minimum) return false;
    bool valid = (f.kind == 'r' && f.offset >= 0x148 && f.offset <= 0x18c && f.maximum <= 20)
        || (f.kind == 'b' && f.offset >= 0x148 && f.offset <= 0x156 && f.maximum <= 20)
        || (f.kind == 'p' && f.offset >= 0x40 && f.offset <= 0x47 && f.maximum <= 20)
        || (f.kind == 's' && (f.offset == 0x25c || f.offset == 0x25e) && f.maximum <= 200)
        || (f.kind == 'd' && f.offset == 0x2d0 && f.maximum <= 2200*512+366);
    if (!valid) return false;
    o->player_filters[o->player_filter_count++] = f;
    return true;
}

static bool parse_options(int argc, char **argv, Options *options) {
    memset(options, 0, sizeof(*options));
    options->pid = -1;
    options->max_bytes = DEFAULT_MAX_BYTES;
    options->chunk_size = DEFAULT_CHUNK_SIZE;
    options->max_matches = DEFAULT_MAX_MATCHES;

    if (argc < 2) {
        return false;
    }
    options->command = argv[1];
    for (int i = 2; i < argc; ++i) {
        if (strcmp(argv[i], "--pid") == 0 && i + 1 < argc) {
            options->pid = (pid_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--needle") == 0 && i + 1 < argc) {
            if (!add_needle(options, argv[++i])) {
                return false;
            }
        } else if (strcmp(argv[i], "--hex-needle") == 0 && i + 1 < argc) {
            if (!add_hex_needle(options, argv[++i])) {
                return false;
            }
        } else if (strcmp(argv[i], "--max-bytes") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->max_bytes)) {
                return false;
            }
        } else if (strcmp(argv[i], "--chunk-size") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->chunk_size)) {
                return false;
            }
        } else if (strcmp(argv[i], "--max-matches") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->max_matches)) {
                return false;
            }
        } else if (strcmp(argv[i], "--player-primary") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->player_primary)) return false;
        } else if (strcmp(argv[i], "--player-playing") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->player_playing)) return false;
        } else if (strcmp(argv[i], "--player-person") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->player_person)) return false;
        } else if (strcmp(argv[i], "--player-staff-primary") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->player_staff_primary)) return false;
        } else if (strcmp(argv[i], "--player-staff-person") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->player_staff_person)) return false;
        } else if (strcmp(argv[i], "--human-primary") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->human_primary)) return false;
        } else if (strcmp(argv[i], "--human-person") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->human_person)) return false;
        } else if (strcmp(argv[i], "--player-query") == 0 && i + 1 < argc) {
            options->player_query = argv[++i];
        } else if (strcmp(argv[i], "--team-primary") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->team_primary)) return false;
        } else if (strcmp(argv[i], "--national-team-primary") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->national_team_primary)) return false;
        } else if (strcmp(argv[i], "--competition") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->competition)) return false;
        } else if (strcmp(argv[i], "--lookup-header") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->lookup_header)) return false;
        } else if (strcmp(argv[i], "--team-assignment") == 0 && i + 1 < argc) {
            const char *value = argv[++i];
            if (strcmp(value, "current") == 0) options->team_assignment = 0;
            else if (strcmp(value, "next") == 0) options->team_assignment = 1;
            else if (strcmp(value, "secondary") == 0) options->team_assignment = 2;
            else if (strcmp(value, "next_secondary") == 0) options->team_assignment = 3;
            else return false;
            options->team_assignment_set = true;
        } else if (strcmp(argv[i], "--query-players") == 0) {
            options->query_players = true;
        } else if (strcmp(argv[i], "--player-filter") == 0 && i + 1 < argc) {
            if (!add_player_filter(options, argv[++i])) return false;
        } else if (strcmp(argv[i], "--list-header") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->list_header)) return false;
        } else if (strcmp(argv[i], "--list-start") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->list_start)) return false;
        } else if (strcmp(argv[i], "--list-count") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->list_count)) return false;
        } else if (strcmp(argv[i], "--start-index") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->start_index)) return false;
        } else if (strcmp(argv[i], "--record-budget") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->record_budget)) return false;
        } else if (strcmp(argv[i], "--private-only") == 0) {
            options->private_only = true;
        } else if (strcmp(argv[i], "--writable-only") == 0) {
            options->writable_only = true;
        } else if (strcmp(argv[i], "--start-address") == 0 && i + 1 < argc) {
            if (!parse_u64(argv[++i], &options->start_address)) return false;
        } else {
            return false;
        }
    }
    if (options->pid <= 0 || options->chunk_size == 0 || options->max_matches == 0) {
        return false;
    }
    if ((options->query_players || options->player_filter_count)
        && (!options->query_players || strcmp(options->command, "scan-player-index") != 0)) return false;
    if (strcmp(options->command, "scan-team-index") == 0) {
        return options->team_assignment_set && options->competition >= 4096 && options->competition % 8 == 0
            && options->team_primary && options->national_team_primary && options->lookup_header
            && options->list_header && options->list_start && options->list_count <= 2000000
            && options->start_index <= options->list_count && options->record_budget > 0
            && options->record_budget <= 200000 && options->max_matches <= 100;
    }
    if (strcmp(options->command, "scan-session") == 0 && options->needle_count == 0) {
        if (!add_needle(options, "Current date:")) {
            return false;
        }
    }
    if (strcmp(options->command, "scan-player-index") == 0 || strcmp(options->command, "scan-club-index") == 0 || strcmp(options->command, "scan-staff-index") == 0) {
        return options->player_query && strlen(options->player_query) <= 128
            && options->player_primary
            && (strcmp(options->command, "scan-club-index") == 0 || (options->player_playing && options->player_person))
            && options->list_header && options->list_start && options->list_count <= 2000000
            && options->start_index <= options->list_count && options->record_budget > 0
            && options->record_budget <= 200000 && options->max_matches <= 100;
    }
    if (options->player_query && (!options->player_primary || !options->player_playing || !options->player_person || options->needle_count != 1)) return false;
    return strcmp(options->command, "images") == 0 || strcmp(options->command, "probe") == 0
        || strcmp(options->command, "scan-session") == 0
        || strcmp(options->command, "read-bytes") == 0;
}

/* read-bytes: --addr 0xHEX --read-len N — argv-parsed in main() to avoid
 * touching the existing Options struct. */

static bool region_is_readable(const vm_region_submap_info_data_64_t *info) {
    return (info->protection & VM_PROT_READ) != 0;
}

static bool region_is_writable(const vm_region_submap_info_data_64_t *info) {
    return (info->protection & VM_PROT_WRITE) != 0;
}

static bool region_is_private(const vm_region_submap_info_data_64_t *info) {
    return info->share_mode == SM_PRIVATE || info->share_mode == SM_PRIVATE_ALIASED;
}

static void protection_string(vm_prot_t protection, char out[4]) {
    out[0] = (protection & VM_PROT_READ) ? 'r' : '-';
    out[1] = (protection & VM_PROT_WRITE) ? 'w' : '-';
    out[2] = (protection & VM_PROT_EXECUTE) ? 'x' : '-';
    out[3] = '\0';
}

static int run_probe(const Options *options, mach_port_t task) {
    ScanStats stats = {0};
    mach_vm_address_t address = 0;
    natural_t depth = 0;

    while (true) {
        mach_vm_size_t size = 0;
        vm_region_submap_info_data_64_t info;
        mach_msg_type_number_t count = VM_REGION_SUBMAP_INFO_COUNT_64;
        kern_return_t kr = mach_vm_region_recurse(
            task,
            &address,
            &size,
            &depth,
            (vm_region_recurse_info_t)&info,
            &count
        );
        if (kr != KERN_SUCCESS) {
            break;
        }
        if (info.is_submap) {
            depth++;
            continue;
        }
        stats.regions_seen++;
        if (region_is_readable(&info)) {
            stats.regions_readable++;
        }
        if (region_is_writable(&info)) {
            stats.regions_writable++;
        }
        if (region_is_private(&info)) {
            stats.regions_private++;
        }
        mach_vm_address_t next = address + size;
        if (next <= address) {
            break;
        }
        address = next;
    }

    printf("{\"ok\":true,\"command\":\"probe\",\"pid\":%d,\"attach_ok\":true,", options->pid);
    printf("\"regions\":{\"seen\":%llu,\"readable\":%llu,\"writable\":%llu,\"private\":%llu},",
           stats.regions_seen,
           stats.regions_readable,
           stats.regions_writable,
           stats.regions_private);
    printf("\"warnings\":[]}\n");
    return 0;
}

static ssize_t find_bytes(const uint8_t *data, size_t data_len, const uint8_t *needle, size_t needle_len, size_t start) {
    if (needle_len == 0 || data_len < needle_len || start > data_len - needle_len) {
        return -1;
    }
    for (size_t i = start; i <= data_len - needle_len; ++i) {
        if (data[i] == needle[0] && memcmp(data + i, needle, needle_len) == 0) {
            return (ssize_t)i;
        }
    }
    return -1;
}

static char *context_from_bytes(const uint8_t *data, size_t data_len, size_t match_start, size_t match_len, const char *encoding) {
    size_t start = match_start > CONTEXT_BYTES ? match_start - CONTEXT_BYTES : 0;
    size_t end = match_start + match_len + CONTEXT_BYTES;
    if (end > data_len) {
        end = data_len;
    }
    char *out = calloc(192, 1);
    if (out == NULL) {
        return NULL;
    }
    size_t out_len = 0;
    bool previous_space = false;
    if (strcmp(encoding, "utf-16le") == 0) {
        if ((start % 2) != (match_start % 2)) {
            start++;
        }
        for (size_t i = start; i + 1 < end && out_len < 160; i += 2) {
            unsigned char lo = data[i];
            unsigned char hi = data[i + 1];
            char ch = (hi == 0 && isprint(lo)) ? (char)lo : ' ';
            bool is_space = isspace((unsigned char)ch) || ch == ' ';
            if (is_space) {
                if (!previous_space && out_len > 0) {
                    out[out_len++] = ' ';
                }
                previous_space = true;
            } else {
                out[out_len++] = ch;
                previous_space = false;
            }
        }
    } else {
        for (size_t i = start; i < end && out_len < 160; ++i) {
            unsigned char byte = data[i];
            char ch = (byte < 0x80 && isprint(byte)) ? (char)byte : ' ';
            bool is_space = isspace((unsigned char)ch) || ch == ' ';
            if (is_space) {
                if (!previous_space && out_len > 0) {
                    out[out_len++] = ' ';
                }
                previous_space = true;
            } else {
                out[out_len++] = ch;
                previous_space = false;
            }
        }
    }
    while (out_len > 0 && out[out_len - 1] == ' ') {
        out_len--;
    }
    out[out_len] = '\0';
    return out;
}

static void emit_match(
    const Needle *needle,
    const char *encoding,
    mach_vm_address_t absolute_address,
    mach_vm_address_t region_start,
    mach_vm_size_t region_size,
    const vm_region_submap_info_data_64_t *info,
    const uint8_t *buffer,
    size_t buffer_len,
    size_t match_offset,
    size_t match_len,
    bool needs_comma
) {
    char protection[4];
    protection_string(info->protection, protection);
    char *context = context_from_bytes(buffer, buffer_len, match_offset, match_len, encoding);
    if (needs_comma) {
        putchar(',');
    }
    fputs("{\"kind\":\"needle\",\"value\":", stdout);
    print_json_string(needle->value);
    fputs(",\"encoding\":", stdout);
    print_json_string(encoding);
    printf(",\"address\":\"0x%llx\",\"region\":{\"start\":\"0x%llx\",\"end\":\"0x%llx\",\"protection\":",
           (unsigned long long)absolute_address,
           (unsigned long long)region_start,
           (unsigned long long)(region_start + region_size));
    print_json_string(protection);
    printf(",\"share_mode\":%u},\"context\":", info->share_mode);
    print_json_string(context != NULL ? context : "");
    fputs(",\"confidence\":0.75,\"source\":\"live_memory\"}", stdout);
    free(context);
}

static void scan_buffer_for_matches(
    const Options *options,
    ScanStats *stats,
    const vm_region_submap_info_data_64_t *info,
    mach_vm_address_t region_start,
    mach_vm_size_t region_size,
    mach_vm_address_t chunk_address,
    mach_vm_address_t body_start_address,
    const uint8_t *buffer,
    size_t buffer_len
) {
    for (size_t n = 0; n < options->needle_count && stats->matches < options->max_matches; ++n) {
        const Needle *needle = &options->needles[n];
        const struct {
            const char *encoding;
            const uint8_t *bytes;
            size_t len;
        } encodings[] = {
            {"utf-8", needle->utf8, needle->utf8_len},
            {"utf-16le", needle->utf16le, needle->utf16le_len},
        };
        for (size_t e = 0; e < 2 && stats->matches < options->max_matches; ++e) {
            if (encodings[e].bytes == NULL || encodings[e].len == 0) {
                continue;
            }
            size_t offset = 0;
            while (stats->matches < options->max_matches) {
                ssize_t found = find_bytes(buffer, buffer_len, encodings[e].bytes, encodings[e].len, offset);
                if (found < 0) {
                    break;
                }
                mach_vm_address_t absolute_address = chunk_address + (mach_vm_address_t)found;
                if (absolute_address + (mach_vm_address_t)encodings[e].len <= body_start_address) {
                    offset = (size_t)found + encodings[e].len;
                    continue;
                }
                if (options->player_query) {
                    if (emit_player(options->task, absolute_address, options->player_primary,
                        options->player_playing, options->player_person, options->player_query,
                        stats->matches > 0, stats, false, options) == 1) stats->matches++;
                    offset = (size_t)found + encodings[e].len;
                    continue;
                }
                emit_match(
                    needle,
                    encodings[e].encoding,
                    absolute_address,
                    region_start,
                    region_size,
                    info,
                    buffer,
                    buffer_len,
                    (size_t)found,
                    encodings[e].len,
                    stats->matches > 0
                );
                stats->matches++;
                offset = (size_t)found + encodings[e].len;
            }
        }
    }
}

static int run_scan(const Options *options, mach_port_t task) {
    ScanStats stats = {0};
    mach_vm_address_t address = options->start_address;
    mach_vm_address_t next_address = address;
    bool reached_end = false;
    natural_t depth = 0;
    uint64_t remaining = options->max_bytes;
    uint64_t chunk_size = options->chunk_size;
    if (chunk_size > 16ULL * 1024ULL * 1024ULL) {
        chunk_size = 16ULL * 1024ULL * 1024ULL;
    }
    uint64_t overlap = max_encoded_needle_len(options);
    if (overlap > 0) {
        overlap--;
    }
    if (overlap > 65536ULL) {
        overlap = 65536ULL;
    }
    uint8_t *buffer = malloc((size_t)(chunk_size + overlap));
    if (buffer == NULL) {
        fputs("{\"ok\":false,\"error\":{\"code\":\"allocation_failed\"},\"warnings\":[]}\n", stdout);
        return 1;
    }

    printf("{\"ok\":true,\"command\":\"scan-session\",\"pid\":%d,\"attach_ok\":true,", options->pid);
    printf("\"limits\":{\"max_bytes\":%llu,\"chunk_size\":%llu,\"overlap_bytes\":%llu,\"max_matches\":%llu,\"private_only\":%s},",
           options->max_bytes,
           chunk_size,
           overlap,
           options->max_matches,
           options->private_only ? "true" : "false");
    fputs("\"matches\":[", stdout);

    while (remaining > 0 && stats.matches < options->max_matches) {
        mach_vm_size_t size = 0;
        vm_region_submap_info_data_64_t info;
        mach_msg_type_number_t count = VM_REGION_SUBMAP_INFO_COUNT_64;
        kern_return_t kr = mach_vm_region_recurse(
            task,
            &address,
            &size,
            &depth,
            (vm_region_recurse_info_t)&info,
            &count
        );
        if (kr != KERN_SUCCESS) {
            reached_end = true;
            break;
        }
        if (info.is_submap) {
            depth++;
            continue;
        }
        stats.regions_seen++;
        if (region_is_readable(&info)) {
            stats.regions_readable++;
        }
        if (region_is_writable(&info)) {
            stats.regions_writable++;
        }
        if (region_is_private(&info)) {
            stats.regions_private++;
        }

        bool scan_region = region_is_readable(&info)
            && (!options->private_only || region_is_private(&info))
            && (!options->writable_only || region_is_writable(&info));
        if (scan_region) {
            stats.regions_scanned++;
            mach_vm_size_t offset = options->start_address > address
                ? options->start_address - address : 0;
            while (offset < size && remaining > 0 && stats.matches < options->max_matches) {
                uint64_t wanted = chunk_size;
                if (wanted > size - offset) {
                    wanted = size - offset;
                }
                if (wanted > remaining) {
                    wanted = remaining;
                }
                uint64_t prefix_overlap = offset < overlap ? offset : overlap;
                mach_vm_address_t read_address = address + offset - prefix_overlap;
                uint64_t read_size = wanted + prefix_overlap;
                mach_vm_size_t out_size = 0;
                kern_return_t read_kr = mach_vm_read_overwrite(
                    task,
                    read_address,
                    (mach_vm_size_t)read_size,
                    (mach_vm_address_t)buffer,
                    &out_size
                );
                if (read_kr == KERN_SUCCESS && out_size > 0) {
                    stats.bytes_read += out_size;
                    remaining -= wanted;
                    scan_buffer_for_matches(
                        options,
                        &stats,
                        &info,
                        address,
                        size,
                        read_address,
                        address + offset,
                        buffer,
                        (size_t)out_size
                    );
                } else {
                    stats.read_failures++;
                    remaining = remaining > wanted ? remaining - wanted : 0;
                }
                offset += wanted;
                next_address = address + offset;
            }
        }
        mach_vm_address_t next = address + size;
        if (next <= address) {
            break;
        }
        address = next;
    }

    const char *stop_reason = stats.matches >= options->max_matches ? "match_limit"
        : reached_end ? "address_space_end" : "byte_budget";
    printf("],\"stop_reason\":\"%s\",\"next_address\":\"0x%llx\",\"scan\":{\"regions_seen\":%llu,\"regions_readable\":%llu,\"regions_writable\":%llu,"
           "\"regions_private\":%llu,\"regions_scanned\":%llu,\"bytes_read\":%llu,"
           "\"read_failures\":%llu,\"matches\":%llu},\"warnings\":[]}\n",
           stop_reason,
           (unsigned long long)next_address,
           stats.regions_seen,
           stats.regions_readable,
           stats.regions_writable,
           stats.regions_private,
           stats.regions_scanned,
           stats.bytes_read,
           stats.read_failures,
           stats.matches);
    free(buffer);
    return 0;
}

static int run_read_bytes(pid_t pid, mach_port_t task, uint64_t addr, uint64_t len) {
    if (addr == 0 || len == 0 || len > (16 * 1024) || addr > UINT64_MAX - len) {
        printf("{\"ok\":false,\"command\":\"read-bytes\",\"pid\":%d,\"error\":{\"code\":\"bad_len\"},\"warnings\":[]}\n", pid);
        return 1;
    }
    uint8_t *buf = calloc((size_t)len, 1);
    if (buf == NULL) {
        printf("{\"ok\":false,\"command\":\"read-bytes\",\"pid\":%d,\"error\":{\"code\":\"oom\"},\"warnings\":[]}\n", pid);
        return 1;
    }
    mach_vm_size_t out_size = 0;
    kern_return_t kr = mach_vm_read_overwrite(task, (mach_vm_address_t)addr, (mach_vm_size_t)len, (mach_vm_address_t)buf, &out_size);
    if (kr != KERN_SUCCESS) {
        printf("{\"ok\":false,\"command\":\"read-bytes\",\"pid\":%d,\"addr\":\"0x%llx\",\"error\":{\"code\":\"read_failed\",\"mach_code\":%d},\"warnings\":[]}\n",
               pid, (unsigned long long)addr, kr);
        free(buf);
        return 1;
    }
    printf("{\"ok\":true,\"command\":\"read-bytes\",\"pid\":%d,\"addr\":\"0x%llx\",\"len\":%llu,\"hex\":\"",
           pid, (unsigned long long)addr, (unsigned long long)out_size);
    for (size_t i = 0; i < out_size; ++i) {
        printf("%02x", buf[i]);
    }
    printf("\",\"warnings\":[]}\n");
    free(buf);
    return 0;
}

/* One query owns one task port (or one channel to the in-game library). Never reopen the PID after task death. */
static int run_read_stream(pid_t pid, mach_port_t task) {
    setvbuf(stdin, NULL, _IONBF, 0);
    printf("{\"ok\":true,\"command\":\"read-stream\",\"pid\":%d}\n", pid);
    fflush(stdout);
    uint64_t total = 0;
    for (unsigned count = 0; count < 100000; ++count) {
        struct pollfd input = {STDIN_FILENO, POLLIN, 0};
        if (poll(&input, 1, 45000) <= 0) return 1;
        char line[96];
        if (fgets(line, sizeof(line), stdin) == NULL) return feof(stdin) ? 0 : 1;
        char *end;
        errno = 0;
        if (!isdigit((unsigned char)line[0])) return 2;
        uint64_t addr = strtoull(line, &end, 10);
        if (errno || *end != ' ' || !isdigit((unsigned char)end[1])) return 2;
        uint64_t len = strtoull(end + 1, &end, 10);
        if (errno || strcmp(end, "\n") != 0 || !len || len > 16384
            || !addr || addr > UINT64_MAX - len || total + len > 64 * 1024 * 1024) return 2;
        total += len;
        int result = run_read_bytes(pid, task, addr, len);
        fflush(stdout);
        if (result) return result;
    }
    return 2;
}

int main(int argc, char **argv) {
    if (argc == 4 && strcmp(argv[1], "read-stream") == 0 && strcmp(argv[2], "--pid") == 0) {
        char *end;
        errno = 0;
        long pid = strtol(argv[3], &end, 10);
        if (errno || *end || pid <= 0 || pid > INT32_MAX) return 2;
        mach_port_t task = MACH_PORT_NULL;
        if (!fh_attach("read-stream", (pid_t)pid, &task)) return 1;
        int result = run_read_stream((pid_t)pid, task);
        if (task != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), task);
        return result;
    }
    /* Special-case --addr / --read-len for read-bytes; otherwise use Options parser. */
    uint64_t read_addr = 0, read_len = 0;
    pid_t read_pid = -1;
    int is_read_bytes = (argc >= 2 && strcmp(argv[1], "read-bytes") == 0);
    if (is_read_bytes) {
        for (int i = 2; i < argc; ++i) {
            if (strcmp(argv[i], "--pid") == 0 && i + 1 < argc) read_pid = (pid_t)atoi(argv[++i]);
            else if (strcmp(argv[i], "--addr") == 0 && i + 1 < argc) {
                const char *s = argv[++i];
                if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) read_addr = strtoull(s+2, NULL, 16);
                else read_addr = strtoull(s, NULL, 10);
            }
            else if (strcmp(argv[i], "--read-len") == 0 && i + 1 < argc) read_len = strtoull(argv[++i], NULL, 10);
        }
        if (read_pid <= 0 || read_addr == 0 || read_len == 0) {
            usage();
            return 2;
        }
        mach_port_t task2 = MACH_PORT_NULL;
        if (!fh_attach("read-bytes", read_pid, &task2)) return 1;
        int result = run_read_bytes(read_pid, task2, read_addr, read_len);
        if (task2 != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), task2);
        return result;
    }

    Options options;
    if (!parse_options(argc, argv, &options)) {
        usage();
        return 2;
    }

    mach_port_t task = MACH_PORT_NULL;
    if (!fh_attach(options.command, options.pid, &task)) {
        free_needles(&options);
        return 1;
    }

    options.task = task;
    int result = 0;
    if (strcmp(options.command, "scan-team-index") == 0) {
        result = run_team_index(&options, task);
    } else if (strcmp(options.command, "scan-player-index") == 0 || strcmp(options.command, "scan-club-index") == 0 || strcmp(options.command, "scan-staff-index") == 0) {
        result = run_entity_index(&options, task);
    } else if (strcmp(options.command, "images") == 0) {
        result = g_injected ? run_images_injected(options.pid) : run_images(options.pid, task);
    } else if (strcmp(options.command, "probe") == 0) {
        result = run_probe(&options, task);
    } else {
        result = run_scan(&options, task);
    }

    if (task != MACH_PORT_NULL) {
        mach_port_deallocate(mach_task_self(), task);
    }
    free_needles(&options);
    return result;
}
