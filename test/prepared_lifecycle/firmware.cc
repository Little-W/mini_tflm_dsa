/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>
#include <string.h>

#include "lifecycle_abi.h"
#include "full_network_abi.h"
#include "dsa_accel.h"
#include "dsa_prepared.h"
#include "riscv_nn_dsa.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/system_setup.h"
#include "tensorflow/lite/schema/schema_generated.h"

#ifndef FULL_NETWORK_ARENA_BYTES
#define FULL_NETWORK_ARENA_BYTES (512 * 1024)
#endif

extern "C" {
volatile uint32_t full_network_mode;
volatile full_network_result_t full_network_result;
volatile full_network_trace_t full_network_trace;
alignas(16) uint8_t full_network_arena[FULL_NETWORK_ARENA_BYTES];
lifecycle_result_t lifecycle_result;
lifecycle_registry_t lifecycle_registry;
uint32_t soc_get_cycle(void);

uint32_t __real_dsa_prepare_conv_s8(dsa_prepared_t*, const dsa_conv_s8_config_t*);
uint32_t __real_dsa_prepare_matmul_s8(dsa_prepared_t*, const dsa_prepared_matmul_s8_config_t*);
uint32_t __real_dsa_prepare_spatial_s8(dsa_prepared_t*, const dsa_vector_config_t*);
uint32_t __real_dsa_prepare_add_s8(dsa_prepared_add_s8_t*, uint32_t,
    const dsa_vector_add_params_t*, int32_t, int32_t, int32_t);
uint32_t __real_dsa_prepared_execute(const dsa_prepared_t*, const void*, void*);
uint32_t __real_dsa_prepared_add_s8_execute(const dsa_prepared_add_s8_t*,
    const int8_t*, const int8_t*, int8_t*);
}

namespace {
uint32_t snapshot_ordinal;

void Marker(uint32_t value) {
  __asm__ volatile("" ::: "memory");
  *reinterpret_cast<volatile uint32_t*>(0x2000000cu) = value;
  __asm__ volatile("" ::: "memory");
}

int Fail(uint32_t error) {
  lifecycle_result.error = error;
  lifecycle_result.complete = 1;
  return static_cast<int>(0x99000000u | error);
}

void Snapshot(uint32_t iteration, uint32_t kind, const void* address, uint32_t bytes) {
  full_network_trace.magic = LIFECYCLE_MAGIC;
  full_network_trace.version = LIFECYCLE_VERSION;
  full_network_trace.ordinal = snapshot_ordinal;
  full_network_trace.operator_index = iteration;
  full_network_trace.output_index = kind;
  full_network_trace.tensor_index = kind;
  full_network_trace.address = reinterpret_cast<uintptr_t>(address);
  full_network_trace.bytes = bytes;
  full_network_trace.type = 0;
  Marker(FULL_NETWORK_TENSOR | snapshot_ordinal++);
}

void StateSnapshot(uint32_t iteration, const full_network_config_t* configuration) {
  Snapshot(iteration, LIFECYCLE_ARENA_SNAPSHOT, full_network_arena,
           FULL_NETWORK_ARENA_BYTES);
  Snapshot(iteration, LIFECYCLE_REGISTRY_SNAPSHOT, &lifecycle_registry,
           sizeof(lifecycle_registry));
  Snapshot(iteration, LIFECYCLE_MODEL_SNAPSHOT,
           reinterpret_cast<const void*>(configuration->model_address),
           configuration->model_bytes);
}

lifecycle_configuration_t* FindConfiguration(const void* pointer) {
  const uintptr_t address = reinterpret_cast<uintptr_t>(pointer);
  for (uint32_t i = 0; i < lifecycle_registry.configurations; ++i) {
    if (lifecycle_registry.configuration[i].address == address)
      return &lifecycle_registry.configuration[i];
  }
  return nullptr;
}

void RecordPreparation(const void* pointer, uint32_t bytes, uint32_t kind,
                       uint32_t status) {
  ++lifecycle_registry.prepare_calls;
  if (lifecycle_registry.in_invoke) lifecycle_registry.error |= 4u;
  if (status != DSA_SUCCESS) {
    ++lifecycle_registry.prepare_failures;
    lifecycle_registry.error |= 32u;
    return;
  }
  const uintptr_t address = reinterpret_cast<uintptr_t>(pointer);
  const uintptr_t begin = reinterpret_cast<uintptr_t>(full_network_arena);
  if (address < begin || address > begin + FULL_NETWORK_ARENA_BYTES - bytes) {
    lifecycle_registry.error |= 2u;
    return;
  }
  lifecycle_configuration_t* entry = FindConfiguration(pointer);
  if (!entry) {
    if (lifecycle_registry.configurations == LIFECYCLE_MAX_CONFIGURATIONS) {
      lifecycle_registry.error |= 1u;
      return;
    }
    entry = &lifecycle_registry.configuration[lifecycle_registry.configurations++];
    entry->address = address;
    entry->bytes = bytes;
    entry->kind = kind;
  }
  ++entry->prepare_calls;
  if (kind != 4u) {
    const auto* descriptor = static_cast<const dsa_prepared_t*>(pointer);
    if (descriptor->readonly_count > 4u) {
      lifecycle_registry.error |= 64u;
      return;
    }
    entry->readonly_count = descriptor->readonly_count;
    for (uint32_t i = 0; i < descriptor->readonly_count; ++i) {
      const uint32_t first = descriptor->readonly[i].begin;
      const uint32_t last = descriptor->readonly[i].end;
      switch (i) {
        case 0: entry->readonly_begin_0 = first; entry->readonly_end_0 = last; break;
        case 1: entry->readonly_begin_1 = first; entry->readonly_end_1 = last; break;
        case 2: entry->readonly_begin_2 = first; entry->readonly_end_2 = last; break;
        case 3: entry->readonly_begin_3 = first; entry->readonly_end_3 = last; break;
      }
    }
  }
}

void RecordExecution(const void* pointer, bool is_add) {
  ++lifecycle_registry.execute_calls;
  if (!lifecycle_registry.in_invoke) lifecycle_registry.error |= 16u;
  lifecycle_configuration_t* entry = FindConfiguration(pointer);
  if (!entry || (entry->kind == 4u) != is_add) {
    lifecycle_registry.error |= 8u;
    return;
  }
  ++entry->execute_calls;
}

int Run() {
  const auto* cfg = reinterpret_cast<const full_network_config_t*>(
      FULL_NETWORK_CONFIG_ADDRESS);
  lifecycle_result.magic = lifecycle_registry.magic = LIFECYCLE_MAGIC;
  lifecycle_result.version = lifecycle_registry.version = LIFECYCLE_VERSION;
  if (cfg->magic != FULL_NETWORK_MAGIC || cfg->version != FULL_NETWORK_VERSION ||
      cfg->mode != FULL_NETWORK_MODE_HARDWARE ||
      cfg->flags & ~FULL_NETWORK_FLAG_PS_RAW || !cfg->reserved ||
      cfg->reserved > LIFECYCLE_MAX_REPEATS) return Fail(1);
  if (cfg->model_address != FULL_NETWORK_MODEL_ADDRESS || cfg->model_bytes < 8 ||
      cfg->model_bytes > FULL_NETWORK_INPUT_ADDRESS - FULL_NETWORK_MODEL_ADDRESS ||
      cfg->input_address != FULL_NETWORK_INPUT_ADDRESS || !cfg->input_bytes ||
      cfg->input_bytes > FULL_NETWORK_GOLDEN_ADDRESS - FULL_NETWORK_INPUT_ADDRESS ||
      cfg->golden_address != FULL_NETWORK_GOLDEN_ADDRESS || !cfg->output_bytes ||
      cfg->output_bytes > FULL_NETWORK_CONFIG_ADDRESS - FULL_NETWORK_GOLDEN_ADDRESS)
    return Fail(2);
  lifecycle_result.repeats = cfg->reserved;
  dsa_set_ps_force_raw((cfg->flags & FULL_NETWORK_FLAG_PS_RAW) != 0);
  full_network_mode = cfg->mode;
  dsa_nn_set_accelerators(cfg->mode);
  const uint32_t init_start = soc_get_cycle();
  tflite::InitializeTarget();
  const auto* model = tflite::GetModel(reinterpret_cast<const void*>(cfg->model_address));
  if (model->version() != TFLITE_SCHEMA_VERSION || model->subgraphs()->size() != 1 ||
      model->subgraphs()->Get(0)->operators()->size() != cfg->expected_operators)
    return Fail(3);
  static tflite::MicroMutableOpResolver<8> resolver;
  if (resolver.AddConv2D() != kTfLiteOk || resolver.AddMaxPool2D() != kTfLiteOk ||
      resolver.AddReshape() != kTfLiteOk || resolver.AddFullyConnected() != kTfLiteOk ||
      resolver.AddDepthwiseConv2D() != kTfLiteOk || resolver.AddAveragePool2D() != kTfLiteOk ||
      resolver.AddSoftmax() != kTfLiteOk || resolver.AddAdd() != kTfLiteOk)
    return Fail(4);
  static tflite::MicroInterpreter interpreter(model, resolver, full_network_arena,
                                            FULL_NETWORK_ARENA_BYTES);
  ++lifecycle_result.allocate_calls;
  if (interpreter.AllocateTensors() != kTfLiteOk) return Fail(5);
  TfLiteTensor* input = interpreter.input(0);
  TfLiteTensor* output = interpreter.output(0);
  if (!input || !output || input->type != kTfLiteInt8 || output->type != kTfLiteInt8 ||
      input->bytes != cfg->input_bytes || output->bytes != cfg->output_bytes)
    return Fail(6);
  lifecycle_result.arena_after_allocate = interpreter.arena_used_bytes();
  lifecycle_result.planning_after_allocate = dsa_total_planning_cycles();
  lifecycle_result.prepare_after_allocate = lifecycle_registry.prepare_calls;
  lifecycle_result.configurations = lifecycle_registry.configurations;
  lifecycle_result.output_address = reinterpret_cast<uintptr_t>(output->data.raw);
  lifecycle_result.output_bytes = output->bytes;
  lifecycle_result.init_cycles = soc_get_cycle() - init_start;
  if (lifecycle_registry.error || !lifecycle_registry.configurations) return Fail(7);
  StateSnapshot(UINT32_MAX, cfg);
  Marker(FULL_NETWORK_BEGIN);
  for (uint32_t iteration = 0; iteration < cfg->reserved; ++iteration) {
    lifecycle_invocation_t& record = lifecycle_result.invocation[iteration];
    memcpy(input->data.int8, reinterpret_cast<const void*>(cfg->input_address), input->bytes);
    record.planning_before = dsa_total_planning_cycles();
    record.arena_before = interpreter.arena_used_bytes();
    record.prepare_before = lifecycle_registry.prepare_calls;
    record.execute_before = lifecycle_registry.execute_calls;
    lifecycle_registry.in_invoke = 1;
    Marker(FULL_NETWORK_LAYER_BEGIN | iteration);
    record.start_cycle = soc_get_cycle();
    record.status = interpreter.Invoke();
    record.end_cycle = soc_get_cycle();
    Marker(FULL_NETWORK_LAYER_END | iteration);
    lifecycle_registry.in_invoke = 0;
    record.invoke_cycles = record.end_cycle - record.start_cycle;
    record.planning_after = dsa_total_planning_cycles();
    record.arena_after = interpreter.arena_used_bytes();
    record.prepare_after = lifecycle_registry.prepare_calls;
    record.execute_after = lifecycle_registry.execute_calls;
    const auto* actual = reinterpret_cast<const uint8_t*>(output->data.raw);
    const auto* golden = reinterpret_cast<const uint8_t*>(cfg->golden_address);
    uint32_t hash = 2166136261u;
    for (uint32_t i = 0; i < output->bytes; ++i) {
      hash = (hash ^ actual[i]) * 16777619u;
      record.mismatches += actual[i] != golden[i];
      if (static_cast<int8_t>(actual[i]) > static_cast<int8_t>(actual[record.predicted_label]))
        record.predicted_label = i;
    }
    record.output_fnv1a = hash;
    record.compared_outputs = output->bytes;
    Snapshot(iteration, LIFECYCLE_OUTPUT_SNAPSHOT, output->data.raw, output->bytes);
    StateSnapshot(iteration, cfg);
    if (record.status != kTfLiteOk || record.mismatches || lifecycle_registry.error ||
        record.planning_before != lifecycle_result.planning_after_allocate ||
        record.planning_after != record.planning_before ||
        record.arena_before != lifecycle_result.arena_after_allocate ||
        record.arena_after != record.arena_before ||
        record.prepare_before != lifecycle_result.prepare_after_allocate ||
        record.prepare_after != record.prepare_before) return Fail(8);
  }
  Marker(FULL_NETWORK_END);
  lifecycle_result.complete = 1;
  return 0;
}
}  // namespace

extern "C" uint32_t __wrap_dsa_prepare_conv_s8(
    dsa_prepared_t* configuration, const dsa_conv_s8_config_t* parameters) {
  const uint32_t status = __real_dsa_prepare_conv_s8(configuration, parameters);
  RecordPreparation(configuration, sizeof(*configuration), 1u, status);
  return status;
}

extern "C" uint32_t __wrap_dsa_prepare_matmul_s8(
    dsa_prepared_t* configuration, const dsa_prepared_matmul_s8_config_t* parameters) {
  const uint32_t status = __real_dsa_prepare_matmul_s8(configuration, parameters);
  RecordPreparation(configuration, sizeof(*configuration), 2u, status);
  return status;
}

extern "C" uint32_t __wrap_dsa_prepare_spatial_s8(
    dsa_prepared_t* configuration, const dsa_vector_config_t* parameters) {
  const uint32_t status = __real_dsa_prepare_spatial_s8(configuration, parameters);
  RecordPreparation(configuration, sizeof(*configuration), 3u, status);
  return status;
}

extern "C" uint32_t __wrap_dsa_prepare_add_s8(
    dsa_prepared_add_s8_t* configuration, uint32_t length,
    const dsa_vector_add_params_t* quantization, int32_t output_offset,
    int32_t activation_min, int32_t activation_max) {
  const uint32_t status = __real_dsa_prepare_add_s8(configuration, length,
      quantization, output_offset, activation_min, activation_max);
  RecordPreparation(configuration, sizeof(*configuration), 4u, status);
  return status;
}

extern "C" uint32_t __wrap_dsa_prepared_execute(
    const dsa_prepared_t* configuration, const void* input, void* output) {
  RecordExecution(configuration, false);
  return __real_dsa_prepared_execute(configuration, input, output);
}

extern "C" uint32_t __wrap_dsa_prepared_add_s8_execute(
    const dsa_prepared_add_s8_t* configuration, const int8_t* input1,
    const int8_t* input2, int8_t* output) {
  RecordExecution(configuration, true);
  return __real_dsa_prepared_add_s8_execute(configuration, input1, input2, output);
}

extern "C" int main(void) { return Run(); }
