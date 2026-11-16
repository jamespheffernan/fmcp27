/*
 * fmcp_attach_target: a stand-in for the game when testing the injected route.
 *
 * Built and signed like the game (hardened runtime, the game's two dyld
 * entitlements from native/fmcp_attach_target.entitlements, no get-task-allow,
 * ad-hoc). It fills a buffer with a known pattern, prints one line
 *   READY <pid> <buffer address> <buffer bytes>
 * and then waits until stdin closes. Byte i of the buffer is (i * 131 + 7) & 0xff.
 *
 * Usage: fmcp_attach_target [MiB]   (default 64)
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
    size_t mib = argc > 1 ? (size_t)strtoul(argv[1], NULL, 10) : 64;
    if (mib == 0 || mib > 1024) mib = 64;
    size_t size = mib << 20;
    uint8_t *buffer = malloc(size);
    if (buffer == NULL) return 1;
    for (size_t i = 0; i < size; ++i) buffer[i] = (uint8_t)((i * 131u + 7u) & 0xffu);
    printf("READY %d %llu %zu\n", (int)getpid(), (unsigned long long)(uintptr_t)buffer, size);
    fflush(stdout);
    char sink[256];
    while (read(STDIN_FILENO, sink, sizeof sink) > 0) {
    }
    free(buffer);
    return 0;
}
