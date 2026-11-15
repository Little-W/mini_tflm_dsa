/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>
#include <string.h>

#include "full_network_abi.h"
#include "riscv_nn_dsa.h"
#include "tensorflow/lite/core/c/common.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_profiler_interface.h"
#include "tensorflow/lite/micro/system_setup.h"
#include "tensorflow/lite/schema/schema_generated.h"

#ifndef FULL_NETWORK_ARENA_BYTES
#define FULL_NETWORK_ARENA_BYTES (256 * 1024)
#endif
#ifndef FULL_NETWORK_TRACE_ENABLED
#define FULL_NETWORK_TRACE_ENABLED 0
#endif

extern "C" {
volatile uint32_t full_network_mode;
volatile full_network_result_t full_network_result;
volatile full_network_trace_t full_network_trace;
alignas(16) uint8_t full_network_arena[FULL_NETWORK_ARENA_BYTES];
uint32_t soc_get_cycle(void);
}

namespace {
void Marker(uint32_t value) {
  __asm__ volatile("" ::: "memory");
  *reinterpret_cast<volatile uint32_t*>(0x2000000cu) = value;
  __asm__ volatile("" ::: "memory");
}

int Fail(uint32_t error, TfLiteStatus status = kTfLiteError) {
  full_network_result.error = error;
  full_network_result.status = static_cast<uint32_t>(status);
  full_network_result.complete = 1;
  return static_cast<int>(0x99000000u | error);
}

uint32_t Fnv1a(const uint8_t* data, uint32_t bytes) {
  uint32_t value = 2166136261u;
  for (uint32_t i = 0; i < bytes; ++i) value = (value ^ data[i]) * 16777619u;
  return value;
}

#if FULL_NETWORK_TRACE_ENABLED
// GetTensor() requires preserve_all_tensors. Observe the already allocated
// EvalTensor at node completion instead, retaining the ordinary arena plan.
class ObservableInterpreter : public tflite::MicroInterpreter {
 public:
  using tflite::MicroInterpreter::MicroInterpreter;
  const TfLiteEvalTensor* GetLiveEvalTensor(int index) {
    const TfLiteContext& ctx = context();
    return ctx.GetEvalTensor ? ctx.GetEvalTensor(&ctx, index) : nullptr;
  }
};

class OutputObserver : public tflite::MicroProfilerInterface {
 public:
  const tflite::Model* model = nullptr;
  ObservableInterpreter* interpreter = nullptr;
  uint32_t next_operator = 0;
  uint32_t ordinal = 0;

  uint32_t BeginEvent(const char*) override {
    const uint32_t index = next_operator++;
    Marker(FULL_NETWORK_LAYER_BEGIN | index);
    return index;
  }
  void EndEvent(uint32_t index) override {
    Marker(FULL_NETWORK_LAYER_END | index);
    const auto* operators = model->subgraphs()->Get(0)->operators();
    if (index >= operators->size()) {
      full_network_result.error = 20;
      return;
    }
    const auto* outputs = operators->Get(index)->outputs();
    for (uint32_t i = 0; i < outputs->size(); ++i) {
      const int tensor_index = outputs->Get(i);
      if (tensor_index < 0) continue;
      const TfLiteEvalTensor* tensor = interpreter->GetLiveEvalTensor(tensor_index);
      if (!tensor || !tensor->dims || !tensor->data.raw) {
        full_network_result.error = 23;
        return;
      }
      uint32_t element_bytes;
      switch (tensor->type) {
        case kTfLiteInt8: case kTfLiteUInt8: case kTfLiteBool: element_bytes = 1; break;
        case kTfLiteInt16: element_bytes = 2; break;
        case kTfLiteInt32: case kTfLiteFloat32: element_bytes = 4; break;
        default: full_network_result.error = 21; return;
      }
      uint32_t count = 1;
      for (int d = 0; d < tensor->dims->size; ++d) count *= tensor->dims->data[d];
      full_network_trace.magic = FULL_NETWORK_MAGIC;
      full_network_trace.version = FULL_NETWORK_VERSION;
      full_network_trace.ordinal = ordinal;
      full_network_trace.operator_index = index;
      full_network_trace.output_index = i;
      full_network_trace.tensor_index = static_cast<uint32_t>(tensor_index);
      full_network_trace.address = reinterpret_cast<uintptr_t>(tensor->data.raw);
      full_network_trace.bytes = count * element_bytes;
      full_network_trace.type = tensor->type;
      Marker(FULL_NETWORK_TENSOR | ordinal);
      ++ordinal;
    }
  }
};
#endif

int Run() {
  const auto* cfg = reinterpret_cast<const volatile full_network_config_t*>(
      FULL_NETWORK_CONFIG_ADDRESS);
  full_network_result.magic = FULL_NETWORK_MAGIC;
  full_network_result.version = FULL_NETWORK_VERSION;
  full_network_result.mode = cfg->mode;
  full_network_result.sample_index = cfg->sample_index;
  full_network_result.trace_enabled = FULL_NETWORK_TRACE_ENABLED;
  full_network_result.first_mismatch = UINT32_MAX;
  if (cfg->magic != FULL_NETWORK_MAGIC || cfg->version != FULL_NETWORK_VERSION)
    return Fail(1);
  if (cfg->mode != FULL_NETWORK_MODE_CPU &&
      cfg->mode != FULL_NETWORK_MODE_CONV_FC &&
      cfg->mode != FULL_NETWORK_MODE_HARDWARE) return Fail(2);
  if (cfg->model_address != FULL_NETWORK_MODEL_ADDRESS || cfg->model_bytes < 8 ||
      cfg->model_bytes > FULL_NETWORK_INPUT_ADDRESS - FULL_NETWORK_MODEL_ADDRESS ||
      cfg->input_address != FULL_NETWORK_INPUT_ADDRESS || !cfg->input_bytes ||
      cfg->input_bytes > FULL_NETWORK_GOLDEN_ADDRESS - FULL_NETWORK_INPUT_ADDRESS ||
      cfg->golden_address != FULL_NETWORK_GOLDEN_ADDRESS || !cfg->output_bytes ||
      cfg->output_bytes > FULL_NETWORK_CONFIG_ADDRESS - FULL_NETWORK_GOLDEN_ADDRESS)
    return Fail(3);
  full_network_mode = cfg->mode;
  dsa_nn_set_accelerators(cfg->mode);
  const uint32_t init_start = soc_get_cycle();
  tflite::InitializeTarget();
  const auto* model = tflite::GetModel(reinterpret_cast<const void*>(cfg->model_address));
  if (model->version() != TFLITE_SCHEMA_VERSION || model->subgraphs()->size() != 1)
    return Fail(4);
  full_network_result.operator_count = model->subgraphs()->Get(0)->operators()->size();
  if (full_network_result.operator_count != cfg->expected_operators) return Fail(5);

  static tflite::MicroMutableOpResolver<8> resolver;
  if (resolver.AddConv2D() != kTfLiteOk || resolver.AddMaxPool2D() != kTfLiteOk ||
      resolver.AddReshape() != kTfLiteOk || resolver.AddFullyConnected() != kTfLiteOk ||
      resolver.AddDepthwiseConv2D() != kTfLiteOk || resolver.AddAveragePool2D() != kTfLiteOk ||
      resolver.AddSoftmax() != kTfLiteOk || resolver.AddAdd() != kTfLiteOk) return Fail(6);
#if FULL_NETWORK_TRACE_ENABLED
  static OutputObserver observer;
  static ObservableInterpreter interpreter(model, resolver, full_network_arena,
      FULL_NETWORK_ARENA_BYTES, nullptr, &observer);
  observer.model = model;
  observer.interpreter = &interpreter;
#else
  static tflite::MicroInterpreter interpreter(model, resolver, full_network_arena,
      FULL_NETWORK_ARENA_BYTES);
#endif
  if (interpreter.AllocateTensors() != kTfLiteOk) return Fail(7);
  full_network_result.arena_used_bytes = interpreter.arena_used_bytes();
  TfLiteTensor* input = interpreter.input(0);
  TfLiteTensor* output = interpreter.output(0);
  if (!input || !output || input->type != kTfLiteInt8 || output->type != kTfLiteInt8 ||
      input->bytes != cfg->input_bytes || output->bytes != cfg->output_bytes)
    return Fail(8);
  memcpy(input->data.int8, reinterpret_cast<const void*>(cfg->input_address), input->bytes);
  full_network_result.input_bytes = input->bytes;
  full_network_result.output_bytes = output->bytes;
  full_network_result.output_address = reinterpret_cast<uintptr_t>(output->data.raw);
  full_network_result.expected_label = cfg->label;
  full_network_result.init_cycles = soc_get_cycle() - init_start;

  Marker(FULL_NETWORK_BEGIN);
  const uint32_t start = soc_get_cycle();
  const TfLiteStatus status = interpreter.Invoke();
  const uint32_t end = soc_get_cycle();
  Marker(FULL_NETWORK_END);
  full_network_result.start_cycle = start;
  full_network_result.end_cycle = end;
  full_network_result.invoke_cycles = end - start;
  full_network_result.status = static_cast<uint32_t>(status);
#if FULL_NETWORK_TRACE_ENABLED
  full_network_result.trace_records = observer.ordinal;
  if (observer.next_operator != cfg->expected_operators) return Fail(22);
#endif
  if (status != kTfLiteOk) return Fail(9, status);
  if (full_network_result.error) return Fail(full_network_result.error);
  const auto* actual = reinterpret_cast<const uint8_t*>(output->data.raw);
  const auto* golden = reinterpret_cast<const uint8_t*>(cfg->golden_address);
  uint32_t prediction = 0;
  for (uint32_t i = 0; i < output->bytes; ++i) {
    if (static_cast<int8_t>(actual[i]) > static_cast<int8_t>(actual[prediction])) prediction = i;
    if (actual[i] != golden[i]) {
      if (!full_network_result.mismatches) {
        full_network_result.first_mismatch = i;
        full_network_result.first_expected = golden[i];
        full_network_result.first_actual = actual[i];
      }
      ++full_network_result.mismatches;
    }
  }
  full_network_result.predicted_label = prediction;
  full_network_result.output_fnv1a = Fnv1a(actual, output->bytes);
  full_network_result.compared_outputs = output->bytes;
  if (full_network_result.mismatches) return Fail(10);
  full_network_result.complete = 1;
  return 0;
}
}  // namespace

extern "C" int main(void) { return Run(); }
