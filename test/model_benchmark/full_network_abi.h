/* SPDX-License-Identifier: Apache-2.0 */
#ifndef FULL_NETWORK_ABI_H
#define FULL_NETWORK_ABI_H

#include <stdint.h>

#define FULL_NETWORK_CONFIG_ADDRESS 0x001e0000u
#define FULL_NETWORK_MODEL_ADDRESS  0x00100000u
#define FULL_NETWORK_INPUT_ADDRESS  0x00180000u
#define FULL_NETWORK_GOLDEN_ADDRESS 0x00190000u
#define FULL_NETWORK_MAGIC          0x46434e4eu
#define FULL_NETWORK_VERSION        3u
#define FULL_NETWORK_BEGIN          0xc0f10001u
#define FULL_NETWORK_END            0xc0f10002u
#define FULL_NETWORK_TENSOR         0xc0f20000u
#define FULL_NETWORK_MODE_CPU       0u
#define FULL_NETWORK_MODE_CONV_FC   9u
#define FULL_NETWORK_MODE_HARDWARE 63u
#define FULL_NETWORK_FLAG_PS_RAW     1u
#define FULL_NETWORK_LAYER_BEGIN   0xd1000000u
#define FULL_NETWORK_LAYER_END     0xd2000000u

/* All ABI fields are little-endian uint32_t words. Data images are generated.
 * Firmware text/data/bss/heap must remain below MODEL_ADDRESS; the stack is
 * placed at the top of the 2 MiB SoC RAM by the existing production linker. */
#define FULL_NETWORK_CONFIG_FIELDS(X) \
    X(magic) X(version) X(mode) X(sample_index) \
    X(model_address) X(model_bytes) X(input_address) X(input_bytes) \
    X(golden_address) X(output_bytes) X(label) X(expected_operators) \
    X(expected_conv_nodes) X(expected_fc_nodes) X(flags) X(reserved)

#define FULL_NETWORK_RESULT_FIELDS(X) \
    X(magic) X(version) X(complete) X(mode) X(sample_index) X(status) X(error) \
    X(trace_enabled) X(start_cycle) X(end_cycle) X(invoke_cycles) \
    X(init_cycles) X(arena_used_bytes) X(input_bytes) X(output_bytes) \
    X(output_address) X(predicted_label) X(expected_label) X(compared_outputs) \
    X(mismatches) X(first_mismatch) X(first_expected) X(first_actual) \
    X(output_fnv1a) X(operator_count) X(trace_records) X(planning_cycles)

#define FULL_NETWORK_TRACE_FIELDS(X) \
    X(magic) X(version) X(ordinal) X(operator_index) X(output_index) \
    X(tensor_index) X(address) X(bytes) X(type)

#define FULL_NETWORK_FIELD(name) uint32_t name;
typedef struct { FULL_NETWORK_CONFIG_FIELDS(FULL_NETWORK_FIELD) } full_network_config_t;
typedef struct { FULL_NETWORK_RESULT_FIELDS(FULL_NETWORK_FIELD) } full_network_result_t;
typedef struct { FULL_NETWORK_TRACE_FIELDS(FULL_NETWORK_FIELD) } full_network_trace_t;
#undef FULL_NETWORK_FIELD

#ifdef __cplusplus
extern "C" {
#endif
extern volatile uint32_t full_network_mode;
extern volatile full_network_result_t full_network_result;
extern volatile full_network_trace_t full_network_trace;
#ifdef __cplusplus
}
#endif

#endif
