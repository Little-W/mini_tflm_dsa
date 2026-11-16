/* SPDX-License-Identifier: Apache-2.0 */
#ifndef TFLITE_MICRO_NMSIS_NN_PREPARED_H_
#define TFLITE_MICRO_NMSIS_NN_PREPARED_H_
#include "riscv_nn_prepared.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/op_macros.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"

namespace tflite {
namespace nmsis_nn {

inline bool PreparedConstant(const TfLiteTensor* tensor) {
  return tensor && !tensor->is_variable &&
         tensor->allocation_type == kTfLiteMmapRo && tensor->data.raw_const &&
         reinterpret_cast<uintptr_t>(tensor->data.raw_const) <= UINT32_MAX;
}

inline uint32_t PreparedAddress(const void* pointer) {
  const uintptr_t address = reinterpret_cast<uintptr_t>(pointer);
  return address <= UINT32_MAX ? static_cast<uint32_t>(address) : 0u;
}

inline bool PreparedPackWeights(TfLiteContext* context, const void* source,
                                uint32_t rows, uint32_t depth,
                                uint32_t* address) {
#if DSA_NN_PACKED_WEIGHTS
  dsa_matrix_limits_t limits;
  dsa_matrix_query(&limits);
  if (!(limits.flags & DSA_MATRIX_CAP_RHS_TILE_PACKED) || limits.tile_size != 16u)
    return false;
  const uint32_t bytes = dsa_matrix_packed_bytes(rows, depth, 1u);
  if (!bytes || depth > 65535u || rows > 65535u) return false;
  void* packed = context->AllocatePersistentBuffer(context, bytes);
  const uint32_t packed_address = PreparedAddress(packed);
  if (!packed_address || (packed_address & 3u) ||
      !dsa_matrix_pack(packed, bytes, source, rows, depth, depth, 1u))
    return false;
  *address = packed_address;
  return true;
#else
  (void)context;
  (void)source;
  (void)rows;
  (void)depth;
  (void)address;
  return false;
#endif
}

inline bool PreparedWeightsMatch(const dsa_prepared_t& prepared,
                                const TfLiteEvalTensor* filter,
                                const TfLiteEvalTensor* bias) {
  return prepared.valid == DSA_PREPARED_VALID && filter &&
         reinterpret_cast<uintptr_t>(filter->data.raw_const) ==
             (prepared.source_filter_base ? prepared.source_filter_base :
              prepared.registers[0].value) &&
         reinterpret_cast<uintptr_t>(bias ? bias->data.raw_const : nullptr) ==
             prepared.registers[1].value;
}

// Eval-tensor objects remain allocated for the interpreter's lifetime. Their
// data pointers are read at Invoke, after the arena memory plan is committed.
struct PreparedTensorBindings {
  const TfLiteEvalTensor* input;
  const TfLiteEvalTensor* filter;
  const TfLiteEvalTensor* bias;
  TfLiteEvalTensor* output;

  void Prepare(TfLiteContext* context, TfLiteNode* node, bool has_weights) {
    input=micro::GetEvalInput(context,node,0);
    filter=has_weights ? micro::GetEvalInput(context,node,1) : nullptr;
    bias=has_weights && node->inputs->size>2 ?
        micro::GetEvalInput(context,node,2) : nullptr;
    output=micro::GetEvalOutput(context,node,0);
  }
};

template <typename Data, TfLiteStatus (*Fallback)(TfLiteContext*,TfLiteNode*),
          uint32_t Accelerator>
TfLiteStatus InvokePrepared(TfLiteContext* context,TfLiteNode* node) {
  const auto& data=*static_cast<const Data*>(node->user_data);
  if (data.prepared.valid==DSA_PREPARED_VALID &&
      dsa_nn_accelerator_enabled(Accelerator)) {
    const auto& tensors=data.bindings;
    if (tensors.input->type==kTfLiteInt8 && tensors.output->type==kTfLiteInt8 &&
        (!tensors.filter || (tensors.filter->type==kTfLiteInt8 &&
          PreparedWeightsMatch(data.prepared,tensors.filter,tensors.bias)))) {
      TF_LITE_ENSURE_EQ(context,dsa_prepared_execute(&data.prepared,
          tensors.input->data.raw_const,tensors.output->data.raw),0u);
      return kTfLiteOk;
    }
  }
  return Fallback(context,node);
}
}  // namespace nmsis_nn
}  // namespace tflite
#endif
