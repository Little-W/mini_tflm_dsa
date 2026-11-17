/* Copyright 2024 The TensorFlow Authors. All Rights Reserved.

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

#include "tensorflow/lite/micro/kernels/conv.h"

#include "riscv_nnfunctions.h"
#include "tensorflow/lite/micro/kernels/nmsis_nn/prepared.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/kernels/internal/quantization_util.h"
#include "tensorflow/lite/kernels/internal/reference/conv.h"
#include "tensorflow/lite/kernels/internal/tensor_ctypes.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/padding.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/micro_log.h"

namespace tflite {
namespace {

struct OpData {
  OpDataConv reference_op_data;

  // Index to buffer for optimizations if applicable.
  int buffer_idx;
#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  dsa_prepared_t* prepared;
  nmsis_nn::PreparedTensorBindings bindings;
#endif
};

void* Init(TfLiteContext* context, const char* buffer, size_t length) {
  TFLITE_DCHECK(context->AllocatePersistentBuffer != nullptr);
  auto* data = static_cast<OpData*>(
      context->AllocatePersistentBuffer(context, sizeof(OpData)));
#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  if (data) data->prepared = nullptr;
#endif
  return data;
}

TfLiteStatus Prepare(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->user_data != nullptr);
  TFLITE_DCHECK(node->builtin_data != nullptr);

  int32_t buf_size = 0;
  const auto& params =
      *(static_cast<const TfLiteConvParams*>(node->builtin_data));
  OpData* data = static_cast<OpData*>(node->user_data);
#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  dsa_prepared_invalidate(data->prepared);
#endif

  MicroContext* micro_context = GetMicroContext(context);

  TfLiteTensor* input =
      micro_context->AllocateTempInputTensor(node, kConvInputTensor);
  TF_LITE_ENSURE(context, input != nullptr);
  TfLiteTensor* filter =
      micro_context->AllocateTempInputTensor(node, kConvWeightsTensor);
  TF_LITE_ENSURE(context, filter != nullptr);
  TfLiteTensor* output =
      micro_context->AllocateTempOutputTensor(node, kConvOutputTensor);
  TF_LITE_ENSURE(context, output != nullptr);
  TfLiteTensor* bias =
      micro_context->AllocateTempInputTensor(node, kConvBiasTensor);
  TfLiteType bias_type = bias != nullptr ? bias->type : kTfLiteNoType;

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

  // Consistency check tensor dims
  // Dimensionality
  TF_LITE_ENSURE_EQ(context, input->dims->size, 4);
  TF_LITE_ENSURE_EQ(context, filter->dims->size, 4);
  TF_LITE_ENSURE_EQ(context, output->dims->size, 4);
  // Equal batch size in input and output
  TF_LITE_ENSURE_EQ(context, input->dims->data[0], output->dims->data[0]);
  // Input channels should be an even multiple of filter channels
  TF_LITE_ENSURE(context, filter->dims->data[3] > 0);
  TF_LITE_ENSURE_EQ(context, input->dims->data[3] % filter->dims->data[3], 0);
  // Output channels should be an even multiple of the number of groups
  const int groups = input->dims->data[3] / filter->dims->data[3];
  TFLITE_DCHECK_EQ(output->dims->data[3] % groups, 0);
  // Bias size equal to output channels
  if (bias != nullptr) {
    const int bias_size = NumElements(bias->dims);
    TF_LITE_ENSURE_EQ(context, bias_size, output->dims->data[3]);
  }

  // Initialize nmsis_nn dimensions
  nmsis_nn_dims input_dims;
  input_dims.n = input->dims->data[0];
  input_dims.h = input->dims->data[1];
  input_dims.w = input->dims->data[2];
  input_dims.c = input->dims->data[3];

  nmsis_nn_dims filter_dims;
  filter_dims.n = 1;
  filter_dims.h = filter->dims->data[1];
  filter_dims.w = filter->dims->data[2];
  filter_dims.c = filter->dims->data[3];

  nmsis_nn_dims output_dims;
  output_dims.n = output->dims->data[0];
  output_dims.h = output->dims->data[1];
  output_dims.w = output->dims->data[2];
  output_dims.c = output->dims->data[3];

  if (input->type == kTfLiteInt8 || input->type == kTfLiteInt16) {
    const int num_channels = filter->dims->data[kConvQuantizedDimension];
    data->reference_op_data.per_channel_output_multiplier =
        static_cast<int32_t*>(context->AllocatePersistentBuffer(
            context, num_channels * sizeof(int32_t)));
    data->reference_op_data.per_channel_output_shift =
        static_cast<int32_t*>(context->AllocatePersistentBuffer(
            context, num_channels * sizeof(int32_t)));
  }

  TF_LITE_ENSURE_STATUS(CalculateOpDataConv(
      context, node, params, input_dims.w, input_dims.h, filter_dims.w,
      filter_dims.h, output_dims.w, output_dims.h, input->type,
      &data->reference_op_data));

  // NMSIS_NN allows INT64 or nullptr bias data pointer
  if (input->type == kTfLiteInt8 ||
      (input->type == kTfLiteInt16 &&
       (bias_type == kTfLiteInt64 || bias_type == kTfLiteNoType))) {
    // Initialize nmsis_nn convolution parameters
    nmsis_nn_conv_params conv_params;
    conv_params.input_offset = -input->params.zero_point;
    conv_params.output_offset = output->params.zero_point;
    conv_params.stride.h = params.stride_height;
    conv_params.stride.w = params.stride_width;
    conv_params.dilation.h = params.dilation_height_factor;
    conv_params.dilation.w = params.dilation_width_factor;
    conv_params.padding.h = data->reference_op_data.padding.height;
    conv_params.padding.w = data->reference_op_data.padding.width;
    conv_params.activation.min = data->reference_op_data.output_activation_min;
    conv_params.activation.max = data->reference_op_data.output_activation_max;

    if (input->type == kTfLiteInt8) {
      buf_size = riscv_convolve_wrapper_s8_get_buffer_size_acc(
          &conv_params, &input_dims, &filter_dims, &output_dims);
    } else if (input->type == kTfLiteInt16) {
      TF_LITE_ENSURE_EQ(context, input->params.zero_point, 0);
      TF_LITE_ENSURE_EQ(context, output->params.zero_point, 0);
      buf_size = riscv_convolve_wrapper_s16_get_buffer_size(
          &conv_params, &input_dims, &filter_dims, &output_dims);
    }

    if (buf_size > 0) {
      TF_LITE_ENSURE_STATUS(context->RequestScratchBufferInArena(
          context, buf_size, &data->buffer_idx));
    } else {
      data->buffer_idx = -1;
    }
  }

#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  if (input->type == kTfLiteInt8 && filter->type == kTfLiteInt8 &&
      input_dims.n == 1 && groups == 1 && filter->params.zero_point == 0 &&
      nmsis_nn::PreparedConstant(filter) &&
      (!bias || (bias->type == kTfLiteInt32 && nmsis_nn::PreparedConstant(bias)))) {
    dsa_conv_s8_config_t config = {};
    config.filter_base = nmsis_nn::PreparedAddress(filter->data.raw_const);
    config.bias_base = bias ? nmsis_nn::PreparedAddress(bias->data.raw_const) : 0u;
    config.multiplier_base = nmsis_nn::PreparedAddress(
        data->reference_op_data.per_channel_output_multiplier);
    config.shift_base = nmsis_nn::PreparedAddress(
        data->reference_op_data.per_channel_output_shift);
    config.input_h = input_dims.h;
    config.input_w = input_dims.w;
    config.input_c = config.group_c = input_dims.c;
    config.kernel_h = filter_dims.h;
    config.kernel_w = filter_dims.w;
    config.output_h = output_dims.h;
    config.output_w = output_dims.w;
    config.output_channels = config.dst_row_stride = output_dims.c;
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
    config.dataflow_mode = DSA_NN_CONV_DATAFLOW_MODE;
    const uint32_t source_filter_base = config.filter_base;
    config.rhs_tile_packed = nmsis_nn::PreparedPackWeights(
        context, filter->data.raw_const, config.output_channels,
        config.kernel_h * config.kernel_w * config.group_c, &config.filter_base);
    TF_LITE_ENSURE_STATUS(nmsis_nn::InitializeLayerConfig(
        context, &data->prepared, [&config](dsa_prepared_t* prepared) {
          return dsa_prepare_conv_s8(prepared, &config);
        }));
    if (data->prepared->valid == DSA_PREPARED_VALID)
      data->prepared->source_filter_base = source_filter_base;
  }
#endif

#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  if (data->prepared && data->prepared->valid==DSA_PREPARED_VALID)
    data->bindings.Prepare(context,node,true);
#endif

  micro_context->DeallocateTempTfLiteTensor(output);
  micro_context->DeallocateTempTfLiteTensor(input);
  micro_context->DeallocateTempTfLiteTensor(filter);
  if (bias != nullptr) {
    micro_context->DeallocateTempTfLiteTensor(bias);
  }

  return kTfLiteOk;
}

template <class ActType, class BiasType, class WeigthsType>
riscv_nmsis_nn_status convolve_wrapper(
    const nmsis_nn_context* ctx, const nmsis_nn_conv_params* conv_params,
    const nmsis_nn_per_channel_quant_params* quant_params,
    const nmsis_nn_dims* input_dims, const ActType* input,
    const nmsis_nn_dims* filter_dims, const int8_t* filter,
    const nmsis_nn_dims* bias_dims, const BiasType* bias,
    const nmsis_nn_dims* output_dims, ActType* output, WeigthsType weightsT) {
  return RISCV_NMSIS_NN_ARG_ERROR;
}

template <>
riscv_nmsis_nn_status convolve_wrapper(
    const nmsis_nn_context* ctx, const nmsis_nn_conv_params* conv_params,
    const nmsis_nn_per_channel_quant_params* quant_params,
    const nmsis_nn_dims* input_dims, const int8_t* input,
    const nmsis_nn_dims* filter_dims, const int8_t* filter,
    const nmsis_nn_dims* bias_dims, const int32_t* bias,
    const nmsis_nn_dims* output_dims, int8_t* output, TfLiteType weightsT) {
  if (weightsT == kTfLiteInt8) {
    return riscv_convolve_wrapper_s8_acc(ctx, conv_params, quant_params, input_dims,
                                     input, filter_dims, filter, bias_dims,
                                     bias, output_dims, output);
  } else if (weightsT == kTfLiteInt4) {
    return riscv_convolve_wrapper_s4(ctx, conv_params, quant_params, input_dims,
                                     input, filter_dims, filter, bias_dims,
                                     bias, output_dims, output);
  } else {
    return RISCV_NMSIS_NN_ARG_ERROR;
  }
}

template <>
riscv_nmsis_nn_status convolve_wrapper(
    const nmsis_nn_context* ctx, const nmsis_nn_conv_params* conv_params,
    const nmsis_nn_per_channel_quant_params* quant_params,
    const nmsis_nn_dims* input_dims, const int16_t* input,
    const nmsis_nn_dims* filter_dims, const int8_t* filter,
    const nmsis_nn_dims* bias_dims, const int64_t* bias,
    const nmsis_nn_dims* output_dims, int16_t* output, TfLiteType weightsT) {
  const nmsis_nn_bias_data bias_data = {bias, false};

  return riscv_convolve_wrapper_s16(ctx, conv_params, quant_params, input_dims,
                                    input, filter_dims, filter, bias_dims,
                                    &bias_data, output_dims, output);
}

template <>
riscv_nmsis_nn_status convolve_wrapper(
    const nmsis_nn_context* ctx, const nmsis_nn_conv_params* conv_params,
    const nmsis_nn_per_channel_quant_params* quant_params,
    const nmsis_nn_dims* input_dims, const int16_t* input,
    const nmsis_nn_dims* filter_dims, const int8_t* filter,
    const nmsis_nn_dims* bias_dims, const int32_t* bias,
    const nmsis_nn_dims* output_dims, int16_t* output, TfLiteType weightsT) {
  const nmsis_nn_bias_data bias_data = {bias, true};

  return riscv_convolve_wrapper_s16(ctx, conv_params, quant_params, input_dims,
                                    input, filter_dims, filter, bias_dims,
                                    &bias_data, output_dims, output);
}

template <typename ActType, typename BiasType, TfLiteType type>
TfLiteStatus EvalQuantizedPerChannel(TfLiteContext* context, TfLiteNode* node,
                                     const TfLiteConvParams& params,
                                     const OpData& data,
                                     const TfLiteEvalTensor* input,
                                     const TfLiteEvalTensor* filter,
                                     const TfLiteEvalTensor* bias,
                                     TfLiteEvalTensor* output) {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  if (type == kTfLiteInt8 &&
      nmsis_nn::PreparedWeightsMatch(data.prepared, filter, bias) &&
      dsa_nn_accelerator_enabled(DSA_NN_ACCEL_CONV)) {
    const auto status = riscv_nn_execute_prepared_s8(
        data.prepared, input->data.int8, output->data.int8);
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
    return kTfLiteOk;
  }
#endif
  nmsis_nn_conv_params conv_params;
  conv_params.dilation.h = params.dilation_height_factor;
  conv_params.dilation.w = params.dilation_width_factor;

  // Initialize nmsis_nn convolution parameters
  conv_params.input_offset = -data.reference_op_data.input_zero_point;
  conv_params.output_offset = data.reference_op_data.output_zero_point;
  conv_params.stride.h = params.stride_height;
  conv_params.stride.w = params.stride_width;
  conv_params.padding.h = data.reference_op_data.padding.height;
  conv_params.padding.w = data.reference_op_data.padding.width;
  conv_params.activation.min = data.reference_op_data.output_activation_min;
  conv_params.activation.max = data.reference_op_data.output_activation_max;

  // Initialize nmsis_nn per channel quantization parameters
  nmsis_nn_per_channel_quant_params quant_params;
  quant_params.multiplier = const_cast<int32_t*>(
      data.reference_op_data.per_channel_output_multiplier);
  quant_params.shift =
      const_cast<int32_t*>(data.reference_op_data.per_channel_output_shift);

  // Initialize nmsis_nn dimension structs, consistency is checked in the
  // prepare stage
  nmsis_nn_dims input_dims;
  input_dims.n = input->dims->data[0];
  input_dims.h = input->dims->data[1];
  input_dims.w = input->dims->data[2];
  input_dims.c = input->dims->data[3];

  nmsis_nn_dims filter_dims;
  filter_dims.n = 1;
  filter_dims.h = filter->dims->data[1];
  filter_dims.w = filter->dims->data[2];
  filter_dims.c = filter->dims->data[3];

  nmsis_nn_dims bias_dims;
  bias_dims.n = 1;
  bias_dims.h = 1;
  bias_dims.w = 1;
  bias_dims.c = output->dims->data[3];

  nmsis_nn_dims output_dims;
  output_dims.n = output->dims->data[0];
  output_dims.h = output->dims->data[1];
  output_dims.w = output->dims->data[2];
  output_dims.c = output->dims->data[3];

  // Initialize nmsis_nn context
  nmsis_nn_context ctx;
  ctx.buf = nullptr;
  ctx.size = 0;

  if (data.buffer_idx > -1) {
    ctx.buf = context->GetScratchBuffer(context, data.buffer_idx);
    // Note: ctx.size is currently not used in nmsis_nn.
    // The buffer should be allocated in the prepare function through
    // the corresponding riscv_convolve_wrapper_[type]_get_buffer_size
  }

  // riscv_convolve_wrapper_[type] dispatches the optimized kernel accordingly
  // with the parameters passed
  const riscv_nmsis_nn_status status =
      convolve_wrapper(
          &ctx, &conv_params, &quant_params, &input_dims,
          tflite::micro::GetTensorData<ActType>(input), &filter_dims,
          tflite::micro::GetTensorData<int8_t>(filter), &bias_dims,
          tflite::micro::GetOptionalTensorData<BiasType>(bias), &output_dims,
          tflite::micro::GetTensorData<ActType>(output), type);
  TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);

  return kTfLiteOk;
}

TfLiteStatus EvalInt4(TfLiteContext* context, TfLiteNode* node) {
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kConvBiasTensor)
          : nullptr;
  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kConvOutputTensor);

  TFLITE_DCHECK(node->builtin_data != nullptr);
  const auto& params =
      *(reinterpret_cast<TfLiteConvParams*>(node->builtin_data));
  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  return EvalQuantizedPerChannel<int8_t, int32_t, kTfLiteInt4>(
      context, node, params, data, input, filter, bias, output);
}

TfLiteStatus EvalInt8(TfLiteContext* context, TfLiteNode* node) {
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kConvBiasTensor)
          : nullptr;
  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kConvOutputTensor);

  TFLITE_DCHECK(node->builtin_data != nullptr);
  const auto& params =
      *(reinterpret_cast<TfLiteConvParams*>(node->builtin_data));
  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  return EvalQuantizedPerChannel<int8_t, int32_t, kTfLiteInt8>(
      context, node, params, data, input, filter, bias, output);
}

TfLiteStatus EvalInt16x8(TfLiteContext* context, TfLiteNode* node) {
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kConvBiasTensor)
          : nullptr;
  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kConvOutputTensor);

  TFLITE_DCHECK(node->builtin_data != nullptr);
  const auto& params =
      *(reinterpret_cast<TfLiteConvParams*>(node->builtin_data));
  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  if (bias == nullptr || bias->type == kTfLiteInt32) {
    return EvalQuantizedPerChannel<int16_t, int32_t, kTfLiteInt16>(
        context, node, params, data, input, filter, bias, output);
  } else if (bias->type == kTfLiteInt64) {
    return EvalQuantizedPerChannel<int16_t, int64_t, kTfLiteInt16>(
        context, node, params, data, input, filter, bias, output);
  } else {
    MicroPrintf("Bias type %s (%d) not supported.",
                TfLiteTypeGetName(bias->type), bias->type);
    return kTfLiteError;
  }
}

TfLiteStatus Eval(TfLiteContext* context, TfLiteNode* node) {
  const TfLiteEvalTensor* input =
      tflite::micro::GetEvalInput(context, node, kConvInputTensor);
  const TfLiteEvalTensor* filter =
      tflite::micro::GetEvalInput(context, node, kConvWeightsTensor);
  const TfLiteEvalTensor* bias =
      (NumInputs(node) == 3)
          ? tflite::micro::GetEvalInput(context, node, kConvBiasTensor)
          : nullptr;
  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kConvOutputTensor);

  TFLITE_DCHECK(node->builtin_data != nullptr);
  const auto& params =
      *(reinterpret_cast<TfLiteConvParams*>(node->builtin_data));
  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  TF_LITE_ENSURE_EQ(context, input->type, output->type);
  TF_LITE_ENSURE_MSG(
      context,
      input->type == filter->type ||
          (input->type == kTfLiteInt16 && filter->type == kTfLiteInt8) ||
          (input->type == kTfLiteInt8 && filter->type == kTfLiteInt4),
      "Hybrid models are not supported on TFLite Micro.");

  switch (input->type) {  // Already know in/out types are same.
    case kTfLiteFloat32: {
      tflite::reference_ops::Conv(
          ConvParamsFloat(params, data.reference_op_data),
          tflite::micro::GetTensorShape(input),
          tflite::micro::GetTensorData<float>(input),
          tflite::micro::GetTensorShape(filter),
          tflite::micro::GetTensorData<float>(filter),
          tflite::micro::GetTensorShape(bias),
          tflite::micro::GetOptionalTensorData<float>(bias),
          tflite::micro::GetTensorShape(output),
          tflite::micro::GetTensorData<float>(output),
          tflite::micro::GetTensorShape(nullptr), nullptr);
      break;
    }
    case kTfLiteInt8: {
      switch (filter->type) {
        case kTfLiteInt4: {
          return EvalQuantizedPerChannel<int8_t, int32_t, kTfLiteInt4>(
              context, node, params, data, input, filter, bias, output);
        }
        case kTfLiteInt8: {
          return EvalQuantizedPerChannel<int8_t, int32_t, kTfLiteInt8>(
              context, node, params, data, input, filter, bias, output);
        }
        default: {
          MicroPrintf("Filter type %s (%d) not supported.",
                      TfLiteTypeGetName(filter->type), filter->type);
          return kTfLiteError;
        }
      }
      break;
    }
    case kTfLiteInt16: {
      if (bias == nullptr || bias->type == kTfLiteInt32) {
        return EvalQuantizedPerChannel<int16_t, int32_t, kTfLiteInt16>(
            context, node, params, data, input, filter, bias, output);
      } else if (bias->type == kTfLiteInt64) {
        return EvalQuantizedPerChannel<int16_t, int64_t, kTfLiteInt16>(
            context, node, params, data, input, filter, bias, output);
      } else {
        MicroPrintf("Bias type %s (%d) not supported.",
                    TfLiteTypeGetName(bias->type), bias->type);
        return kTfLiteError;
      }
      break;
    }
    default:
      MicroPrintf("Type %s (%d) not supported.", TfLiteTypeGetName(input->type),
                  input->type);
      return kTfLiteError;
  }

  return kTfLiteOk;
}

}  // namespace

TFLMRegistration Register_CONV_2D() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  return tflite::micro::RegisterOp(Init, Prepare, nmsis_nn::InvokePrepared<OpData,Eval,DSA_NN_ACCEL_CONV>);
#else
  return tflite::micro::RegisterOp(Init, Prepare, Eval);
#endif
}

TFLMRegistration Register_CONV_2D_INT4() {
  return tflite::micro::RegisterOp(Init, Prepare, EvalInt4);
}

TFLMRegistration Register_CONV_2D_INT8() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_CONV_ENABLE
  return tflite::micro::RegisterOp(Init, Prepare, nmsis_nn::InvokePrepared<OpData,EvalInt8,DSA_NN_ACCEL_CONV>);
#else
  return tflite::micro::RegisterOp(Init, Prepare, EvalInt8);
#endif
}

TFLMRegistration Register_CONV_2D_INT16() {
  return tflite::micro::RegisterOp(Init, Prepare, EvalInt16x8);
}

}  // namespace tflite
