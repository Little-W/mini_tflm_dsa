/* Copyright 2022 The TensorFlow Authors. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
==============================================================================*/

#include "tensorflow/lite/micro/kernels/depthwise_conv.h"

#include "riscv_nnfunctions.h"
#include "tensorflow/lite/micro/kernels/nmsis_nn/prepared.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/kernels/internal/quantization_util.h"
#include "tensorflow/lite/kernels/internal/reference/depthwiseconv_float.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h"
#include "tensorflow/lite/kernels/internal/tensor_ctypes.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/padding.h"
#include "tensorflow/lite/micro/kernels/conv.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/micro_log.h"

namespace tflite {
namespace {

struct OpData {
  OpDataConv reference_op_data;

  // Index to buffer for optimizations if applicable.
  int buffer_idx;
  int32_t buffer_size;
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  dsa_prepared_t* prepared;
  nmsis_nn::PreparedTensorBindings bindings;
#endif
};

// Always inline for optimal code size.
void PopulateDwConvParams(
    nmsis_nn_dw_conv_params* const dw_conv_params,
    nmsis_nn_per_channel_quant_params* const quant_params,
    nmsis_nn_dims* const input_dims, nmsis_nn_dims* const filter_dims,
    nmsis_nn_dims* const bias_dims, nmsis_nn_dims* const output_dims,
    const TfLiteDepthwiseConvParams& params, const OpData& data,
    const TfLiteEvalTensor* input, const TfLiteEvalTensor* filter,
    const TfLiteEvalTensor* bias, TfLiteEvalTensor* output)
    __attribute__((always_inline));

void* Init(TfLiteContext* context, const char* buffer, size_t length) {
  TFLITE_DCHECK(context->AllocatePersistentBuffer != nullptr);
  auto* data = static_cast<OpData*>(
      context->AllocatePersistentBuffer(context, sizeof(OpData)));
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  if (data) data->prepared = nullptr;
#endif
  return data;
}

TfLiteStatus Prepare(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->user_data != nullptr);
  TFLITE_DCHECK(node->builtin_data != nullptr);

  OpData* data = static_cast<OpData*>(node->user_data);
  data->buffer_idx = -1;
  data->buffer_size = 0;
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  dsa_prepared_invalidate(data->prepared);
#endif
  const auto& params =
      *(reinterpret_cast<TfLiteDepthwiseConvParams*>(node->builtin_data));

  MicroContext* micro_context = GetMicroContext(context);

  TfLiteTensor* input =
      micro_context->AllocateTempInputTensor(node, kDepthwiseConvInputTensor);
  TF_LITE_ENSURE(context, input != nullptr);
  TfLiteTensor* filter =
      micro_context->AllocateTempInputTensor(node, kDepthwiseConvWeightsTensor);
  TF_LITE_ENSURE(context, filter != nullptr);
  TfLiteTensor* output =
      micro_context->AllocateTempOutputTensor(node, kDepthwiseConvOutputTensor);
  TF_LITE_ENSURE(context, output != nullptr);

  TF_LITE_ENSURE_EQ(context, input->type, output->type);
  TF_LITE_ENSURE_MSG(context,
                     input->type == kTfLiteFloat32 ||
                         input->type == kTfLiteInt16 ||
                         input->type == kTfLiteInt8,
                     "Input data type not supported");
  TF_LITE_ENSURE_MSG(
      context,
      (input->type == kTfLiteFloat32 && filter->type == kTfLiteFloat32) ||
          (input->type == kTfLiteInt16 && filter->type == kTfLiteInt8) ||
          (input->type == kTfLiteInt8 &&
           (filter->type == kTfLiteInt4 || filter->type == kTfLiteInt8)),
      "Hybrid models are not supported on TFLite Micro.");

  const TfLiteType data_type = input->type;
  int input_width = SizeOfDimension(input, 2);
  int input_height = SizeOfDimension(input, 1);
  int filter_width = SizeOfDimension(filter, 2);
  int filter_height = SizeOfDimension(filter, 1);
  int output_width = SizeOfDimension(output, 2);
  int output_height = SizeOfDimension(output, 1);

  if (input->type == kTfLiteInt8 || input->type == kTfLiteInt16) {
    TF_LITE_ENSURE_EQ(context, filter->quantization.type,
                      kTfLiteAffineQuantization);

    if (input->type == kTfLiteInt16) {
      TF_LITE_ENSURE_EQ(context, input->params.zero_point, 0);
      TF_LITE_ENSURE_EQ(context, output->params.zero_point, 0);
    }

    // All per-channel quantized tensors need valid zero point and scale arrays.
    const auto* affine_quantization =
        reinterpret_cast<TfLiteAffineQuantization*>(
            filter->quantization.params);
    TF_LITE_ENSURE(context, affine_quantization);
    TF_LITE_ENSURE(context, affine_quantization->scale);
    TF_LITE_ENSURE(context, affine_quantization->zero_point);
    TF_LITE_ENSURE(
        context, affine_quantization->scale->size == 1 ||
                     affine_quantization->scale->size ==
                         filter->dims->data[kDepthwiseConvQuantizedDimension]);
    TF_LITE_ENSURE_EQ(context, affine_quantization->scale->size,
                      affine_quantization->zero_point->size);

    // Allocate memory for per-channel quantization parameters
    const int num_channels =
        filter->dims->data[kDepthwiseConvQuantizedDimension];

    data->reference_op_data.per_channel_output_multiplier =
        reinterpret_cast<int32_t*>(context->AllocatePersistentBuffer(
            context, num_channels * sizeof(int32_t)));
    data->reference_op_data.per_channel_output_shift =
        reinterpret_cast<int32_t*>(context->AllocatePersistentBuffer(
            context, num_channels * sizeof(int32_t)));
  }

  TF_LITE_ENSURE_STATUS(CalculateOpDataDepthwiseConv(
      context, node, params, input_width, input_height, filter_width,
      filter_height, output_width, output_height, data_type,
      &data->reference_op_data));

  if (input->type == kTfLiteInt8) {
    RuntimeShape input_shape = GetTensorShape(input);
    RuntimeShape output_shape = GetTensorShape(output);
    RuntimeShape filter_shape = GetTensorShape(filter);
    TFLITE_DCHECK_EQ(input_shape.DimensionsCount(), 4);
    TFLITE_DCHECK_EQ(filter_shape.DimensionsCount(), 4);
    TFLITE_DCHECK_EQ(output_shape.DimensionsCount(), 4);

    const int batch_size = MatchingDim(input_shape, 0, output_shape, 0);
    const int output_depth = MatchingDim(output_shape, 3, filter_shape, 3);

    nmsis_nn_dims input_dims;
    input_dims.n = batch_size;
    input_dims.h = input_height;
    input_dims.w = input_width;
    input_dims.c = input_shape.Dims(3);

    nmsis_nn_dims filter_dims;
    filter_dims.n = 1;
    filter_dims.h = filter_height;
    filter_dims.w = filter_width;
    filter_dims.c = output_depth;

    nmsis_nn_dims output_dims;
    output_dims.n = batch_size;
    output_dims.h = output_height;
    output_dims.w = output_width;
    output_dims.c = output_depth;

    nmsis_nn_dw_conv_params dw_conv_params;
    dw_conv_params.input_offset = -input->params.zero_point;
    dw_conv_params.output_offset = output->params.zero_point;
    dw_conv_params.ch_mult = params.depth_multiplier;
    dw_conv_params.stride.h = params.stride_height;
    dw_conv_params.stride.w = params.stride_width;
    dw_conv_params.padding.h = data->reference_op_data.padding.height;
    dw_conv_params.padding.w = data->reference_op_data.padding.width;
    dw_conv_params.dilation.h = params.dilation_height_factor;
    dw_conv_params.dilation.w = params.dilation_width_factor;
    dw_conv_params.activation.min =
        data->reference_op_data.output_activation_min;
    dw_conv_params.activation.max =
        data->reference_op_data.output_activation_max;

    int32_t buf_size = 0;
    if (filter->type == kTfLiteInt8) {
      buf_size = riscv_depthwise_conv_wrapper_s8_get_buffer_size_acc(
          &dw_conv_params, &input_dims, &filter_dims, &output_dims);
    } else if (filter->type == kTfLiteInt4) {
      buf_size = riscv_depthwise_conv_wrapper_s4_get_buffer_size(
          &dw_conv_params, &input_dims, &filter_dims, &output_dims);
    } else {
      MicroPrintf("Filter type %s (%d) not supported.",
                  TfLiteTypeGetName(filter->type), filter->type);
      return kTfLiteError;
    }

    TF_LITE_ENSURE(context, buf_size >= 0);
    data->buffer_size = buf_size;
    if (buf_size > 0) {
      TF_LITE_ENSURE_STATUS(context->RequestScratchBufferInArena(
          context, buf_size, &data->buffer_idx));
    } else {
      data->buffer_idx = -1;
    }
  }

#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  if (input->type == kTfLiteInt8 && filter->type == kTfLiteInt8 &&
      input->dims->size == 4 && output->dims->size == 4 &&
      input->dims->data[0] == 1 && output->dims->data[0] == 1 &&
      params.depth_multiplier == 1 && filter->params.zero_point == 0 &&
      input->dims->data[3] == output->dims->data[3] &&
      nmsis_nn::PreparedConstant(filter)) {
    TfLiteTensor* bias =
        micro_context->AllocateTempInputTensor(node, kDepthwiseConvBiasTensor);
    if (!bias || (bias->type == kTfLiteInt32 && nmsis_nn::PreparedConstant(bias))) {
      dsa_vector_config_t config = {};
      config.operation = DSA_VECTOR_OP_DW_S8;
      config.rhs_base = nmsis_nn::PreparedAddress(filter->data.raw_const);
      config.bias_base = bias ? nmsis_nn::PreparedAddress(bias->data.raw_const) : 0u;
      config.multiplier_base = nmsis_nn::PreparedAddress(
          data->reference_op_data.per_channel_output_multiplier);
      config.shift_base = nmsis_nn::PreparedAddress(
          data->reference_op_data.per_channel_output_shift);
      config.input_h = input_height;
      config.input_w = input_width;
      config.input_c = input->dims->data[3];
      config.kernel_h = filter_height;
      config.kernel_w = filter_width;
      config.output_h = output_height;
      config.output_w = output_width;
      config.stride_h = params.stride_height;
      config.stride_w = params.stride_width;
      config.dilation_h = params.dilation_height_factor;
      config.dilation_w = params.dilation_width_factor;
      config.pad_top = data->reference_op_data.padding.height;
      config.pad_left = data->reference_op_data.padding.width;
      config.input_offset = -data->reference_op_data.input_zero_point;
      config.output_offset = data->reference_op_data.output_zero_point;
      config.activation_min = data->reference_op_data.output_activation_min;
      config.activation_max = data->reference_op_data.output_activation_max;
      TF_LITE_ENSURE_STATUS(nmsis_nn::InitializeLayerConfig(
          context, &data->prepared, [&config](dsa_prepared_t* prepared) {
            return dsa_prepare_spatial_s8(prepared, &config);
          }));
    }
    if (bias) micro_context->DeallocateTempTfLiteTensor(bias);
  }
#endif

#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  if (data->prepared && data->prepared->valid==DSA_PREPARED_VALID)
    data->bindings.Prepare(context,node,true);
#endif

  micro_context->DeallocateTempTfLiteTensor(output);
  micro_context->DeallocateTempTfLiteTensor(input);
  micro_context->DeallocateTempTfLiteTensor(filter);

  return kTfLiteOk;
}

inline void PopulateDwConvParams(
    nmsis_nn_dw_conv_params* const dw_conv_params,
    nmsis_nn_per_channel_quant_params* const quant_params,
    nmsis_nn_dims* const input_dims, nmsis_nn_dims* const filter_dims,
    nmsis_nn_dims* const bias_dims, nmsis_nn_dims* const output_dims,
    const TfLiteDepthwiseConvParams& params, const OpData& data,
    const TfLiteEvalTensor* input, const TfLiteEvalTensor* filter,
    const TfLiteEvalTensor* bias, TfLiteEvalTensor* output) {
  dw_conv_params->dilation.h = params.dilation_height_factor;
  dw_conv_params->dilation.w = params.dilation_width_factor;

  dw_conv_params->input_offset = -data.reference_op_data.input_zero_point;
  dw_conv_params->output_offset = data.reference_op_data.output_zero_point;
  dw_conv_params->stride.h = params.stride_height;
  dw_conv_params->stride.w = params.stride_width;
  dw_conv_params->padding.h = data.reference_op_data.padding.height;
  dw_conv_params->padding.w = data.reference_op_data.padding.width;

  dw_conv_params->activation.min = data.reference_op_data.output_activation_min;
  dw_conv_params->activation.max = data.reference_op_data.output_activation_max;

  dw_conv_params->ch_mult = params.depth_multiplier;

  quant_params->multiplier =
      data.reference_op_data.per_channel_output_multiplier;
  quant_params->shift = data.reference_op_data.per_channel_output_shift;

  RuntimeShape filter_shape = tflite::micro::GetTensorShape(filter);
  RuntimeShape input_shape = tflite::micro::GetTensorShape(input);
  RuntimeShape output_shape = tflite::micro::GetTensorShape(output);
  RuntimeShape bias_shape = tflite::micro::GetTensorShape(bias);

  TFLITE_DCHECK_LE(dw_conv_params->activation.min,
                   dw_conv_params->activation.max);

  const int batch_size = MatchingDim(input_shape, 0, output_shape, 0);
  const int output_depth = MatchingDim(filter_shape, 3, output_shape, 3);

  if (tflite::micro::GetOptionalTensorData<int8_t>(bias)) {
    TFLITE_DCHECK_EQ(bias_shape.FlatSize(), output_depth);
  }

  input_dims->n = batch_size;
  input_dims->h = input_shape.Dims(1);
  input_dims->w = input_shape.Dims(2);
  input_dims->c = input_shape.Dims(3);

  filter_dims->n = filter_shape.Dims(0);
  filter_dims->h = filter_shape.Dims(1);
  filter_dims->w = filter_shape.Dims(2);
  filter_dims->c = output_depth;

  bias_dims->n = 1;
  bias_dims->h = 1;
  bias_dims->w = 1;
  bias_dims->c = output_depth;

  output_dims->n = batch_size;
  output_dims->h = output_shape.Dims(1);
  output_dims->w = output_shape.Dims(2);
  output_dims->c = output_depth;
}

TfLiteStatus EvalQuantizedPerChannel(TfLiteContext* context, TfLiteNode* node,
                             const TfLiteDepthwiseConvParams& params,
                             const OpData& data, const TfLiteEvalTensor* input,
                             const TfLiteEvalTensor* filter,
                             const TfLiteEvalTensor* bias,
                             TfLiteEvalTensor* output) {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  if (nmsis_nn::PreparedWeightsMatch(data.prepared, filter, bias) &&
      dsa_nn_accelerator_enabled(DSA_NN_ACCEL_DW)) {
    const auto status = riscv_nn_execute_prepared_s8(
        data.prepared, input->data.int8, output->data.int8);
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
    return kTfLiteOk;
  }
#endif
  nmsis_nn_dw_conv_params dw_conv_params;
  nmsis_nn_per_channel_quant_params quant_params;
  nmsis_nn_dims input_dims;
  nmsis_nn_dims filter_dims;
  nmsis_nn_dims bias_dims;
  nmsis_nn_dims output_dims;

  PopulateDwConvParams(&dw_conv_params, &quant_params, &input_dims,
                       &filter_dims, &bias_dims, &output_dims, params, data,
                       input, filter, bias, output);

  nmsis_nn_context ctx;
  ctx.buf = nullptr;
  ctx.size = data.buffer_size;

  if (data.buffer_idx > -1) {
    ctx.buf = context->GetScratchBuffer(context, data.buffer_idx);
  }

  const riscv_nmsis_nn_status status =
      riscv_depthwise_conv_wrapper_s8_acc(
          &ctx, &dw_conv_params, &quant_params, &input_dims,
          tflite::micro::GetTensorData<int8_t>(input), &filter_dims,
          tflite::micro::GetTensorData<int8_t>(filter), &bias_dims,
          tflite::micro::GetOptionalTensorData<int32_t>(bias), &output_dims,
          tflite::micro::GetTensorData<int8_t>(output));
  TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
  return kTfLiteOk;
}

void EvalQuantizedPerChannelInt4(TfLiteContext* context, TfLiteNode* node,
                                 const TfLiteDepthwiseConvParams& params,
                                 const OpData& data,
                                 const TfLiteEvalTensor* input,
                                 const TfLiteEvalTensor* filter,
                                 const TfLiteEvalTensor* bias,
                                 TfLiteEvalTensor* output) {
  nmsis_nn_dw_conv_params dw_conv_params;
  nmsis_nn_per_channel_quant_params quant_params;
  nmsis_nn_dims input_dims;
  nmsis_nn_dims filter_dims;
  nmsis_nn_dims bias_dims;
  nmsis_nn_dims output_dims;

  PopulateDwConvParams(&dw_conv_params, &quant_params, &input_dims,
                       &filter_dims, &bias_dims, &output_dims, params, data,
                       input, filter, bias, output);

  nmsis_nn_context ctx;
  ctx.buf = nullptr;
  ctx.size = data.buffer_size;

  if (data.buffer_idx > -1) {
    ctx.buf = context->GetScratchBuffer(context, data.buffer_idx);
  }

  TFLITE_DCHECK_EQ(
      riscv_depthwise_conv_wrapper_s4(
          &ctx, &dw_conv_params, &quant_params, &input_dims,
          tflite::micro::GetTensorData<int8_t>(input), &filter_dims,
          tflite::micro::GetTensorData<int8_t>(filter), &bias_dims,
          tflite::micro::GetOptionalTensorData<int32_t>(bias), &output_dims,
          tflite::micro::GetTensorData<int8_t>(output)),
      RISCV_NMSIS_NN_SUCCESS);
}

void EvalQuantizedPerChannel16x8(TfLiteContext* context, TfLiteNode* node,
                                 const TfLiteDepthwiseConvParams& params,
                                 const OpData& data,
                                 const TfLiteEvalTensor* input,
                                 const TfLiteEvalTensor* filter,
                                 const TfLiteEvalTensor* bias,
                                 TfLiteEvalTensor* output) {
  nmsis_nn_dw_conv_params dw_conv_params;
  nmsis_nn_per_channel_quant_params quant_params;
  nmsis_nn_dims input_dims;
  nmsis_nn_dims filter_dims;
  nmsis_nn_dims bias_dims;
  nmsis_nn_dims output_dims;

  PopulateDwConvParams(&dw_conv_params, &quant_params, &input_dims,
                       &filter_dims, &bias_dims, &output_dims, params, data,
                       input, filter, bias, output);

  nmsis_nn_context ctx;
  ctx.buf = nullptr;
  /* 'size' is unused */
  ctx.size = 0;

  TFLITE_DCHECK_EQ(
      riscv_depthwise_conv_s16(
          &ctx, &dw_conv_params, &quant_params, &input_dims,
          tflite::micro::GetTensorData<int16_t>(input), &filter_dims,
          tflite::micro::GetTensorData<int8_t>(filter), &bias_dims,
          tflite::micro::GetOptionalTensorData<int64_t>(bias), &output_dims,
          tflite::micro::GetTensorData<int16_t>(output)),
      RISCV_NMSIS_NN_SUCCESS);
}

TfLiteStatus Eval(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->user_data != nullptr);
  TFLITE_DCHECK(node->builtin_data != nullptr);

  const auto& params =
      *(reinterpret_cast<TfLiteDepthwiseConvParams*>(node->builtin_data));
  const OpData& data = *(static_cast<OpData*>(node->user_data));

  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kDepthwiseConvOutputTensor);
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kDepthwiseConvBiasTensor)
          : nullptr;

  switch (input->type) {  // Already know in/out types are same.
    case kTfLiteFloat32: {
      tflite::reference_ops::DepthwiseConv(
          DepthwiseConvParamsFloat(params, data.reference_op_data),
          tflite::micro::GetTensorShape(input),
          tflite::micro::GetTensorData<float>(input),
          tflite::micro::GetTensorShape(filter),
          tflite::micro::GetTensorData<float>(filter),
          tflite::micro::GetTensorShape(bias),
          tflite::micro::GetOptionalTensorData<float>(bias),
          tflite::micro::GetTensorShape(output),
          tflite::micro::GetTensorData<float>(output));
      break;
    }
    case kTfLiteInt8:
      switch (filter->type) {
        case kTfLiteInt8: {
          return EvalQuantizedPerChannel(context, node, params, data, input,
                                          filter, bias, output);
        }
        case kTfLiteInt4: {
          EvalQuantizedPerChannelInt4(context, node, params, data, input,
                                      filter, bias, output);
          break;
        }
        default: {
          MicroPrintf("Filter type %s (%d) not supported.",
                      TfLiteTypeGetName(filter->type), filter->type);
          return kTfLiteError;
        }
      }
      break;
    case kTfLiteInt16:
      EvalQuantizedPerChannel16x8(context, node, params, data, input, filter,
                                  bias, output);
      break;
    default:
      MicroPrintf("Type %s (%d) not supported.", TfLiteTypeGetName(input->type),
                  input->type);
      return kTfLiteError;
  }
  return kTfLiteOk;
}

TfLiteStatus EvalInt8(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->user_data != nullptr);
  TFLITE_DCHECK(node->builtin_data != nullptr);

  const auto& params =
      *(reinterpret_cast<TfLiteDepthwiseConvParams*>(node->builtin_data));
  const OpData& data = *(static_cast<OpData*>(node->user_data));

  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kDepthwiseConvOutputTensor);
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kDepthwiseConvBiasTensor)
          : nullptr;

  return EvalQuantizedPerChannel(context, node, params, data, input, filter,
                                  bias, output);
}

TfLiteStatus EvalInt16x8(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->user_data != nullptr);
  TFLITE_DCHECK(node->builtin_data != nullptr);

  const auto& params =
      *(reinterpret_cast<TfLiteDepthwiseConvParams*>(node->builtin_data));
  const OpData& data = *(static_cast<OpData*>(node->user_data));

  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kDepthwiseConvOutputTensor);
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kDepthwiseConvBiasTensor)
          : nullptr;

  EvalQuantizedPerChannel16x8(context, node, params, data, input, filter, bias,
                              output);
  return kTfLiteOk;
}

TfLiteStatus EvalInt4(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->user_data != nullptr);
  TFLITE_DCHECK(node->builtin_data != nullptr);

  const auto& params =
      *(reinterpret_cast<TfLiteDepthwiseConvParams*>(node->builtin_data));
  const OpData& data = *(static_cast<OpData*>(node->user_data));

  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kDepthwiseConvOutputTensor);
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kDepthwiseConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kDepthwiseConvBiasTensor)
          : nullptr;

  EvalQuantizedPerChannelInt4(context, node, params, data, input, filter, bias,
                              output);
  return kTfLiteOk;
}

}  // namespace

TFLMRegistration Register_DEPTHWISE_CONV_2D() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(Init, Prepare, nmsis_nn::InvokePrepared<OpData,Eval,DSA_NN_ACCEL_DW>);
#else
  return tflite::micro::RegisterOp(Init, Prepare, Eval);
#endif
}

TFLMRegistration Register_DEPTHWISE_CONV_2D_INT8() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(Init, Prepare, nmsis_nn::InvokePrepared<OpData,EvalInt8,DSA_NN_ACCEL_DW>);
#else
  return tflite::micro::RegisterOp(Init, Prepare, EvalInt8);
#endif
}

TFLMRegistration Register_DEPTHWISE_CONV_2D_INT16() {
  return tflite::micro::RegisterOp(Init, Prepare, EvalInt16x8);
}

TFLMRegistration Register_DEPTHWISE_CONV_2D_INT4() {
  return tflite::micro::RegisterOp(Init, Prepare, EvalInt4);
}

}  // namespace tflite
