/* SPDX-License-Identifier: Apache-2.0 */
#define Register_FULLY_CONNECTED Register_FULLY_CONNECTED_NMSIS_REFERENCE
#define Register_FULLY_CONNECTED_INT8 Register_FULLY_CONNECTED_INT8_NMSIS_REFERENCE
#define Register_FULLY_CONNECTED_INT4 Register_FULLY_CONNECTED_INT4_NMSIS_REFERENCE
#define Register_FULLY_CONNECTED_INT16 Register_FULLY_CONNECTED_INT16_NMSIS_REFERENCE
#include "tensorflow/lite/micro/kernels/nmsis_nn/fully_connected.cc"
#undef Register_FULLY_CONNECTED
#undef Register_FULLY_CONNECTED_INT8
#undef Register_FULLY_CONNECTED_INT4
#undef Register_FULLY_CONNECTED_INT16

#include <cstring>
#include "tflm_support.h"

namespace tflite {
namespace {
struct GemminiFullyConnectedData {
  OpData reference;
  GemminiLayer layer;
};

void *GemminiInit(TfLiteContext *context, const char *, size_t) {
  void *storage = context->AllocatePersistentBuffer(context, sizeof(GemminiFullyConnectedData));
  if (storage) std::memset(storage, 0, sizeof(GemminiFullyConnectedData));
  return storage;
}

TfLiteStatus GemminiPrepare(TfLiteContext *context, TfLiteNode *node) {
  TF_LITE_ENSURE_STATUS(Prepare(context, node));
  auto *data = static_cast<GemminiFullyConnectedData *>(node->user_data);
  if (!gemmini_model::Enabled(DSA_NN_ACCEL_FC)) return kTfLiteOk;
  auto *micro = GetMicroContext(context);
  TfLiteTensor *input = micro->AllocateTempInputTensor(node, kFullyConnectedInputTensor);
  TfLiteTensor *weights = micro->AllocateTempInputTensor(node, kFullyConnectedWeightsTensor);
  TfLiteTensor *bias = micro->AllocateTempInputTensor(node, kFullyConnectedBiasTensor);
  TfLiteTensor *output = micro->AllocateTempOutputTensor(node, kFullyConnectedOutputTensor);
  TfLiteStatus status = kTfLiteOk;
  if (gemmini_model::TensorTypesSupported(input, weights, bias, output)) {
    const auto &quant = data->reference.reference_op_data;
    GemminiLayer &p = data->layer;
    p.operation = GEMMINI_FULLY_CONNECTED;
    p.batches = data->reference.batches;
    p.input_height = p.input_width = p.output_height = p.output_width = 1;
    p.input_channels = data->reference.accum_depth;
    p.output_channels = data->reference.output_depth;
    p.kernel_height = p.kernel_width = 1;
    p.stride_height = p.stride_width = 1;
    p.dilation_height = p.dilation_width = 1;
    p.input_offset = -input->params.zero_point;
    p.output_offset = output->params.zero_point;
    p.activation_min = quant.output_activation_min;
    p.activation_max = quant.output_activation_max;
    p.weights = weights->data.int8;
    p.bias = bias ? bias->data.i32 : nullptr;
    p.per_channel = quant.is_per_channel;
    p.multiplier = quant.output_multiplier;
    p.shift = quant.output_shift;
    p.multipliers = quant.per_channel_output_multiplier;
    p.shifts = quant.per_channel_output_shift;
    status = gemmini_model::PrepareStorage(context, &p);
  }
  micro->DeallocateTempTfLiteTensor(input);
  micro->DeallocateTempTfLiteTensor(weights);
  if (bias) micro->DeallocateTempTfLiteTensor(bias);
  micro->DeallocateTempTfLiteTensor(output);
  return status;
}

TfLiteStatus GemminiEval(TfLiteContext *context, TfLiteNode *node) {
  const auto &p = static_cast<GemminiFullyConnectedData *>(node->user_data)->layer;
  if (p.supported && gemmini_model::Enabled(DSA_NN_ACCEL_FC))
    return gemmini_model::Invoke(context, node, p, kFullyConnectedInputTensor,
                                kFullyConnectedOutputTensor);
  return Eval(context, node);
}
}  // namespace

TFLMRegistration Register_FULLY_CONNECTED() {
  TFLMRegistration registration = Register_FULLY_CONNECTED_NMSIS_REFERENCE();
  registration.init = GemminiInit;
  registration.prepare = GemminiPrepare;
  registration.invoke = GemminiEval;
  return registration;
}
}  // namespace tflite
