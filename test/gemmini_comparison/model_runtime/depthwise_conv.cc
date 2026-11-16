/* SPDX-License-Identifier: Apache-2.0 */
#define Register_DEPTHWISE_CONV_2D Register_DEPTHWISE_CONV_2D_NMSIS_REFERENCE
#define Register_DEPTHWISE_CONV_2D_INT8 Register_DEPTHWISE_CONV_2D_INT8_NMSIS_REFERENCE
#define Register_DEPTHWISE_CONV_2D_INT4 Register_DEPTHWISE_CONV_2D_INT4_NMSIS_REFERENCE
#define Register_DEPTHWISE_CONV_2D_INT16 Register_DEPTHWISE_CONV_2D_INT16_NMSIS_REFERENCE
#include "tensorflow/lite/micro/kernels/nmsis_nn/depthwise_conv.cc"
#undef Register_DEPTHWISE_CONV_2D
#undef Register_DEPTHWISE_CONV_2D_INT8
#undef Register_DEPTHWISE_CONV_2D_INT4
#undef Register_DEPTHWISE_CONV_2D_INT16

#include <cstring>
#include "tflm_support.h"

namespace tflite {
namespace {
struct GemminiDepthwiseData {
  OpData reference;
  GemminiLayer layer;
};

void *GemminiInit(TfLiteContext *context, const char *, size_t) {
  void *storage = context->AllocatePersistentBuffer(context, sizeof(GemminiDepthwiseData));
  if (storage) std::memset(storage, 0, sizeof(GemminiDepthwiseData));
  return storage;
}

TfLiteStatus GemminiPrepare(TfLiteContext *context, TfLiteNode *node) {
  TF_LITE_ENSURE_STATUS(Prepare(context, node));
  auto *data = static_cast<GemminiDepthwiseData *>(node->user_data);
  if (!gemmini_model::Enabled(DSA_NN_ACCEL_DW)) return kTfLiteOk;
  auto *micro = GetMicroContext(context);
  TfLiteTensor *input = micro->AllocateTempInputTensor(node, kDepthwiseConvInputTensor);
  TfLiteTensor *weights = micro->AllocateTempInputTensor(node, kDepthwiseConvWeightsTensor);
  TfLiteTensor *bias = micro->AllocateTempInputTensor(node, kDepthwiseConvBiasTensor);
  TfLiteTensor *output = micro->AllocateTempOutputTensor(node, kDepthwiseConvOutputTensor);
  TfLiteStatus status = kTfLiteOk;
  if (gemmini_model::TensorTypesSupported(input, weights, bias, output)) {
    const auto &params = *static_cast<const TfLiteDepthwiseConvParams *>(node->builtin_data);
    const auto &quant = data->reference.reference_op_data;
    GemminiLayer &p = data->layer;
    p.operation = GEMMINI_DEPTHWISE;
    p.batches = input->dims->data[0];
    p.input_height = input->dims->data[1];
    p.input_width = input->dims->data[2];
    p.input_channels = input->dims->data[3];
    p.output_height = output->dims->data[1];
    p.output_width = output->dims->data[2];
    p.output_channels = output->dims->data[3];
    p.kernel_height = weights->dims->data[1];
    p.kernel_width = weights->dims->data[2];
    p.stride_height = params.stride_height;
    p.stride_width = params.stride_width;
    p.dilation_height = params.dilation_height_factor;
    p.dilation_width = params.dilation_width_factor;
    p.padding_height = quant.padding.height;
    p.padding_width = quant.padding.width;
    p.input_offset = -input->params.zero_point;
    p.output_offset = output->params.zero_point;
    p.activation_min = quant.output_activation_min;
    p.activation_max = quant.output_activation_max;
    p.weights = weights->data.int8;
    p.bias = bias ? bias->data.i32 : nullptr;
    p.per_channel = true;
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
  const auto &p = static_cast<GemminiDepthwiseData *>(node->user_data)->layer;
  if (p.supported && gemmini_model::Enabled(DSA_NN_ACCEL_DW))
    return gemmini_model::Invoke(context, node, p, kDepthwiseConvInputTensor,
                                kDepthwiseConvOutputTensor);
  return Eval(context, node);
}
}  // namespace

TFLMRegistration Register_DEPTHWISE_CONV_2D() {
  TFLMRegistration registration = Register_DEPTHWISE_CONV_2D_NMSIS_REFERENCE();
  registration.init = GemminiInit;
  registration.prepare = GemminiPrepare;
  registration.invoke = GemminiEval;
  return registration;
}
}  // namespace tflite
