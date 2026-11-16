/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GEMMINI_MODEL_TFLM_SUPPORT_H
#define GEMMINI_MODEL_TFLM_SUPPORT_H

#include "backend.h"
#include "riscv_nn_dsa.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/micro_context.h"

namespace tflite {
namespace gemmini_model {

inline bool Enabled(unsigned operation) {
  return (dsa_nn_get_accelerators() & operation) != 0;
}

inline TfLiteStatus PrepareStorage(TfLiteContext *context, GemminiLayer *layer) {
  layer->supported = false;
  if (!gemmini_layer_supported(*layer)) return kTfLiteOk;
  layer->packed_weights = static_cast<int8_t *>(context->AllocatePersistentBuffer(
      context, gemmini_packed_weight_bytes(*layer)));
  layer->weight_sums = static_cast<int32_t *>(context->AllocatePersistentBuffer(
      context, layer->output_channels * sizeof(int32_t)));
  const size_t prefix_bytes = gemmini_kernel_prefix_bytes(*layer);
  if (prefix_bytes)
    layer->kernel_prefix = static_cast<int32_t *>(context->AllocatePersistentBuffer(
        context, prefix_bytes));
  if (!layer->bias)
    layer->zero_bias = static_cast<int32_t *>(context->AllocatePersistentBuffer(
        context, layer->output_channels * sizeof(int32_t)));
  TF_LITE_ENSURE(context, layer->packed_weights && layer->weight_sums &&
      (layer->bias || layer->zero_bias) && (!prefix_bytes || layer->kernel_prefix));
  gemmini_prepare_layer(layer);
  if (!layer->supported) return kTfLiteOk;
  TF_LITE_ENSURE_STATUS(context->RequestScratchBufferInArena(
      context, gemmini_raw_output_bytes(*layer), &layer->scratch_index));
  return kTfLiteOk;
}

inline bool TensorTypesSupported(const TfLiteTensor *input,
                                const TfLiteTensor *weights,
                                const TfLiteTensor *bias,
                                const TfLiteTensor *output) {
  return input && weights && output && input->type == kTfLiteInt8 &&
      weights->type == kTfLiteInt8 && output->type == kTfLiteInt8 &&
      weights->params.zero_point == 0 && (!bias || bias->type == kTfLiteInt32);
}

inline TfLiteStatus Invoke(TfLiteContext *context, TfLiteNode *node,
                           const GemminiLayer &layer, int input_index,
                           int output_index) {
  const TfLiteEvalTensor *input = micro::GetEvalInput(context, node, input_index);
  TfLiteEvalTensor *output = micro::GetEvalOutput(context, node, output_index);
  int32_t *raw = static_cast<int32_t *>(context->GetScratchBuffer(context, layer.scratch_index));
  TF_LITE_ENSURE(context, input && output && raw);
  gemmini_run(layer, micro::GetTensorData<int8_t>(input), raw,
              micro::GetTensorData<int8_t>(output));
  return kTfLiteOk;
}

}  // namespace gemmini_model
}  // namespace tflite
#endif
