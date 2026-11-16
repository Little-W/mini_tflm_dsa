/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "include/gemmini.h"

static FILE *commands;
static unsigned char *host_memory;
static size_t memory_size;
static uint64_t physical_base;
static size_t instruction_count, fence_count, record_count;
static size_t timed_start_record;
static int last_record_is_fence;

static void fail(const char *message) {
    fprintf(stderr, "gemmini command trace: %s\n", message);
    exit(2);
}

static uint64_t physical_address(uint64_t pointer) {
    const uint64_t begin = (uintptr_t)host_memory;
    if (pointer == 0u) return 0u;
    if (pointer < begin || pointer >= begin + memory_size)
        fail("scheduler emitted a DRAM pointer outside the input memory image");
    return physical_base + pointer - begin;
}

void gemmini_trace_instruction(unsigned custom, uint64_t rs1, uint64_t rs2,
                               unsigned funct) {
    if (!commands || custom != XCUSTOM_ACC || funct > 127u)
        fail("invalid RoCC instruction");
    switch (funct) {
        case k_MVIN: case k_MVIN2: case k_MVIN3: case k_MVOUT:
            rs1 = physical_address(rs1);
            break;
        case k_LOOP_WS_CONFIG_ADDRS_AB: case k_LOOP_WS_CONFIG_ADDRS_DC:
            rs1 = physical_address(rs1);
            rs2 = physical_address(rs2);
            break;
        default:
            break;
    }
    fprintf(commands, "%u 0x%016" PRIx64 " 0x%016" PRIx64 "\n", funct, rs1, rs2);
    ++instruction_count;
    ++record_count;
    last_record_is_fence = 0;
}

void gemmini_trace_fence(void) {
    if (!commands) fail("fence emitted without an output stream");
    fputs("FENCE\n", commands);
    ++fence_count;
    ++record_count;
    last_record_is_fence = 1;
}

uint32_t gemmini_trace_result_instruction(unsigned custom, uint64_t rs1,
                                          unsigned funct) {
    (void)custom; (void)rs1; (void)funct;
    fail("a scheduler requested a hardware result during command generation");
    return 0u;
}

static uint64_t number(const char *text) {
    char *end;
    errno = 0;
    const unsigned long long value = strtoull(text, &end, 0);
    if (errno || !text[0] || *end || text[0] == '-') fail("invalid unsigned argument");
    return (uint64_t)value;
}

static void *tensor(uint64_t address, size_t bytes) {
    if (address < physical_base || address - physical_base > memory_size ||
        bytes > memory_size - (address - physical_base))
        fail("tensor span exceeds the memory image");
    return host_memory + (address - physical_base);
}

static void describe(FILE *stream) {
    fprintf(stream,
        "{\"dim\":%u,\"bank_num\":%u,\"bank_rows\":%u,\"acc_rows\":%u,"
        "\"elem_bytes\":%zu,\"acc_bytes\":%zu,\"max_bytes\":%u,"
        "\"address_bits\":%u,\"custom_opcode_index\":%u,"
        "\"scratchpad_bytes\":%zu,\"accumulator_bytes\":%zu}",
        DIM, BANK_NUM, BANK_ROWS, ACC_ROWS, sizeof(elem_t), sizeof(acc_t),
        MAX_BYTES, ADDR_LEN, XCUSTOM_ACC,
        (size_t)BANK_NUM * BANK_ROWS * DIM * sizeof(elem_t),
        (size_t)ACC_ROWS * DIM * sizeof(acc_t));
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--describe") == 0) {
        describe(stdout); puts(""); return 0;
    }
    const char *memory_path = NULL, *commands_path = NULL, *metadata_path = NULL;
    const char *operation = "matmul", *flow = "ws";
    const char *transpose = "none";
    size_t m = 0u, n = 0u, k = 0u;
    size_t tile_i = 0u, tile_j = 0u, tile_k = 0u;
    uint64_t a = 0u, b = 0u, d = 0u, c = 0u;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc) fail("each option requires one argument");
        const char *key = argv[i], *value = argv[i + 1];
        if (strcmp(key, "--memory") == 0) memory_path = value;
        else if (strcmp(key, "--commands") == 0) commands_path = value;
        else if (strcmp(key, "--metadata") == 0) metadata_path = value;
        else if (strcmp(key, "--operation") == 0) operation = value;
        else if (strcmp(key, "--flow") == 0) flow = value;
        else if (strcmp(key, "--transpose") == 0) transpose = value;
        else if (strcmp(key, "--base") == 0) physical_base = number(value);
        else if (strcmp(key, "--m") == 0) m = number(value);
        else if (strcmp(key, "--n") == 0) n = number(value);
        else if (strcmp(key, "--k") == 0) k = number(value);
        else if (strcmp(key, "--a") == 0) a = number(value);
        else if (strcmp(key, "--b") == 0) b = number(value);
        else if (strcmp(key, "--d") == 0) d = number(value);
        else if (strcmp(key, "--c") == 0) c = number(value);
        else if (strcmp(key, "--tile") == 0) {
            char trailing;
            if (sscanf(value, "%zu,%zu,%zu%c", &tile_i, &tile_j, &tile_k, &trailing) != 3 ||
                !tile_i || !tile_j || !tile_k)
                fail("--tile requires three positive tile counts I,J,K");
        }
        else fail("unknown option");
    }
    if (!memory_path || !commands_path || !metadata_path || !physical_base)
        fail("memory, commands, metadata and a nonzero physical base are required");
    if (sizeof(elem_t) != 1u || sizeof(acc_t) != 4u)
        fail("this trace protocol requires INT8 inputs and INT32 accumulation");
    enum tiled_matmul_type_t dataflow;
    if (strcmp(flow, "ws") == 0) dataflow = WS;
    else if (strcmp(flow, "os") == 0) dataflow = OS;
    else fail("flow must be ws or os");
    const int transpose_a = strcmp(transpose, "a") == 0;
    const int transpose_b = strcmp(transpose, "b") == 0;
    if (!transpose_a && !transpose_b && strcmp(transpose, "none") != 0)
        fail("transpose must be none, a or b");
    if ((transpose_a || transpose_b) &&
        (dataflow != WS || strcmp(operation, "matmul") != 0))
        fail("transposed storage requires the official WS matrix path");
    FILE *memory_file = fopen(memory_path, "rb");
    if (!memory_file || fseek(memory_file, 0, SEEK_END) != 0) fail("cannot open memory image");
    const long size = ftell(memory_file);
    if (size <= 0 || fseek(memory_file, 0, SEEK_SET) != 0) fail("invalid memory image size");
    memory_size = (size_t)size;
    if (posix_memalign((void **)&host_memory, 4096u, memory_size) != 0)
        fail("cannot allocate host memory");
    if (fread(host_memory, 1u, memory_size, memory_file) != memory_size)
        fail("cannot read memory image");
    fclose(memory_file);
    unsigned char *initial = malloc(memory_size);
    if (!initial) fail("cannot allocate validation copy");
    memcpy(initial, host_memory, memory_size);
    commands = fopen(commands_path, "w");
    if (!commands) fail("cannot create command trace");
    gemmini_flush(0);
    gemmini_fence();
    timed_start_record = record_count;
    if (strcmp(operation, "matmul") == 0) {
        if (!m || !n || !k || m > 65535u || n > 65535u || k > 65535u)
            fail("matrix dimensions must be in [1,65535]");
        const elem_t *A = tensor(a, m * k);
        const elem_t *B = tensor(b, k * n);
        const acc_t *D = tensor(d, n * sizeof(acc_t));
        elem_t *C = tensor(c, m * n);
        const size_t stride_a = transpose_a ? m : k;
        const size_t stride_b = transpose_b ? k : n;
        if (tile_i) tiled_matmul(m, n, k, A, B, D, C, stride_a, stride_b, n, n,
                         MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY, 1,
                         NO_ACTIVATION, (acc_scale_t)0.03125f, 0,
                         true, tile_i, tile_j, tile_k,
                         transpose_a, transpose_b, false, false, 0, dataflow);
        else tiled_matmul_auto(m, n, k, A, B, D, C, stride_a, stride_b, n, n,
                         MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY, 1,
                         NO_ACTIVATION, (acc_scale_t)0.03125f, 0,
                         true, transpose_a, transpose_b, false, false, 0, dataflow);
    } else fail("operation must be matmul");
    if (!last_record_is_fence) gemmini_fence();
    if (fclose(commands) != 0) fail("cannot finish command trace");
    commands = NULL;
    if (memcmp(initial, host_memory, memory_size) != 0)
        fail("host scheduling modified a tensor; hardware execution was not isolated");
    FILE *metadata = fopen(metadata_path, "w");
    if (!metadata) fail("cannot write emission metadata");
    fprintf(metadata, "{\"operation\":\"%s\",\"dataflow\":\"%s\","
            "\"instructions\":%zu,\"fences\":%zu,\"records\":%zu,"
            "\"timed_start_record\":%zu,\"host_tensor_bytes_unchanged\":true,"
            "\"official_cpu_reference_passed\":%s,\"config\":",
            operation, flow, instruction_count, fence_count, record_count, timed_start_record,
            "null");
    describe(metadata);
    fprintf(metadata, ",\"explicit_tile\":[%zu,%zu,%zu]", tile_i, tile_j, tile_k);
    fprintf(metadata, ",\"transpose\":\"%s\"", transpose);
    fputs("}\n", metadata);
    if (fclose(metadata) != 0) fail("cannot finish emission metadata");
    free(initial); free(host_memory);
    return 0;
}
