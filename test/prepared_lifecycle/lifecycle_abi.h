/* SPDX-License-Identifier: Apache-2.0 */
#ifndef PREPARED_LIFECYCLE_ABI_H
#define PREPARED_LIFECYCLE_ABI_H
#include <stdint.h>

#define LIFECYCLE_MAGIC 0x4c435931u
#define LIFECYCLE_VERSION 1u
#define LIFECYCLE_MAX_REPEATS 8u
#define LIFECYCLE_MAX_CONFIGURATIONS 64u
#define LIFECYCLE_ARENA_SNAPSHOT 0u
#define LIFECYCLE_REGISTRY_SNAPSHOT 1u
#define LIFECYCLE_OUTPUT_SNAPSHOT 2u
#define LIFECYCLE_MODEL_SNAPSHOT 3u

#define LIFECYCLE_RESULT_FIELDS(X) \
    X(magic) X(version) X(complete) X(error) X(repeats) X(allocate_calls) \
    X(init_cycles) X(planning_after_allocate) X(arena_after_allocate) \
    X(prepare_after_allocate) X(configurations) X(output_address) X(output_bytes)

#define LIFECYCLE_INVOCATION_FIELDS(X) \
    X(status) X(start_cycle) X(end_cycle) X(invoke_cycles) \
    X(planning_before) X(planning_after) X(arena_before) X(arena_after) \
    X(prepare_before) X(prepare_after) X(execute_before) X(execute_after) \
    X(mismatches) X(compared_outputs) X(output_fnv1a) X(predicted_label)

#define LIFECYCLE_REGISTRY_FIELDS(X) \
    X(magic) X(version) X(error) X(in_invoke) X(configurations) \
    X(prepare_calls) X(prepare_failures) X(execute_calls)

#define LIFECYCLE_CONFIGURATION_FIELDS(X) \
    X(address) X(bytes) X(kind) X(prepare_calls) X(execute_calls) X(readonly_count) \
    X(readonly_begin_0) X(readonly_end_0) X(readonly_begin_1) X(readonly_end_1) \
    X(readonly_begin_2) X(readonly_end_2) X(readonly_begin_3) X(readonly_end_3)

#define LIFECYCLE_FIELD(name) uint32_t name;
typedef struct { LIFECYCLE_INVOCATION_FIELDS(LIFECYCLE_FIELD) } lifecycle_invocation_t;
typedef struct {
  LIFECYCLE_RESULT_FIELDS(LIFECYCLE_FIELD)
  lifecycle_invocation_t invocation[LIFECYCLE_MAX_REPEATS];
} lifecycle_result_t;
typedef struct { LIFECYCLE_CONFIGURATION_FIELDS(LIFECYCLE_FIELD) } lifecycle_configuration_t;
typedef struct {
  LIFECYCLE_REGISTRY_FIELDS(LIFECYCLE_FIELD)
  lifecycle_configuration_t configuration[LIFECYCLE_MAX_CONFIGURATIONS];
} lifecycle_registry_t;
#undef LIFECYCLE_FIELD
#endif
