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
#include "tensorflow/lite/kernels/internal/reference/pooling.h"

#include "riscv_nnfunctions.h"
#include "tensorflow/lite/micro/kernels/nmsis_nn/prepared.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/internal/tensor_ctypes.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/kernels/pooling.h"
#include "tensorflow/lite/micro/micro_log.h"

namespace tflite {

namespace {

struct OpData {
  OpDataPooling reference_op_data;

  // Index to buffer for optimizations if applicable.
  int buffer_idx;
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  dsa_prepared_t* prepared;
  nmsis_nn::PreparedTensorBindings bindings;
#endif
};

#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
TfLiteStatus PrepareSpatial(TfLiteContext* context, TfLiteNode* node,
                    OpData* data, const TfLitePoolParams* params,
                    const TfLiteTensor* input, const TfLiteTensor* output,
                    uint32_t operation) {
  dsa_prepared_invalidate(data->prepared);
  if (input->type != kTfLiteInt8 || output->type != kTfLiteInt8 ||
      input->dims->size != 4 || output->dims->size != 4 ||
      input->dims->data[0] != 1 || output->dims->data[0] != 1 ||
      input->dims->data[3] != output->dims->data[3] ||
      input->params.zero_point != output->params.zero_point ||
      input->params.scale != output->params.scale) return kTfLiteOk;
  dsa_vector_config_t config = {};
  config.operation = operation;
  config.input_h = input->dims->data[1];
  config.input_w = input->dims->data[2];
  config.input_c = input->dims->data[3];
  config.output_h = output->dims->data[1];
  config.output_w = output->dims->data[2];
  config.kernel_h = params->filter_height;
  config.kernel_w = params->filter_width;
  config.stride_h = params->stride_height;
  config.stride_w = params->stride_width;
  config.dilation_h = config.dilation_w = 1u;
  config.pad_top = data->reference_op_data.padding.height;
  config.pad_left = data->reference_op_data.padding.width;
  config.activation_min = data->reference_op_data.activation_min;
  config.activation_max = data->reference_op_data.activation_max;
  TF_LITE_ENSURE_STATUS(nmsis_nn::InitializeLayerConfig(
      context, &data->prepared, [&config](dsa_prepared_t* prepared) {
        return dsa_prepare_spatial_s8(prepared, &config);
      }));
  if (data->prepared->valid==DSA_PREPARED_VALID)
    data->bindings.Prepare(context,node,false);
  return kTfLiteOk;
}
#endif

void PopulateCommonParams(
    TfLiteContext* const context, nmsis_nn_dims* const input_dims,
    nmsis_nn_dims* const output_dims, nmsis_nn_pool_params* const pool_params,
    nmsis_nn_context* const ctx, nmsis_nn_dims* const filter_dims,
    const OpData& data, const RuntimeShape& input_shape,
    const RuntimeShape& output_shape, const TfLitePoolParams* params) {
  const int depth = MatchingDim(input_shape, 3, output_shape, 3);

  input_dims->n = input_shape.Dims(0);
  input_dims->h = input_shape.Dims(1);
  input_dims->w = input_shape.Dims(2);
  input_dims->c = depth;

  output_dims->n = output_shape.Dims(0);
  output_dims->h = output_shape.Dims(1);
  output_dims->w = output_shape.Dims(2);
  output_dims->c = depth;

  pool_params->stride.h = params->stride_height;
  pool_params->stride.w = params->stride_width;
  pool_params->padding.h = data.reference_op_data.padding.height;
  pool_params->padding.w = data.reference_op_data.padding.width;
  pool_params->activation.min = data.reference_op_data.activation_min;
  pool_params->activation.max = data.reference_op_data.activation_max;

  filter_dims->n = 1;
  filter_dims->h = params->filter_height;
  filter_dims->w = params->filter_width;
  filter_dims->c = 1;
  ctx->buf = nullptr;
  ctx->size = 0;
  if (data.buffer_idx > -1) {
    ctx->buf = context->GetScratchBuffer(context, data.buffer_idx);
  }
}

TfLiteStatus AverageEvalQuantized(TfLiteContext* context, const TfLiteNode* node,
                          const TfLitePoolParams* params, const OpData& data,
                          const TfLiteEvalTensor* input,
                          TfLiteEvalTensor* output) {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  if (data.prepared && data.prepared->valid == DSA_PREPARED_VALID &&
      dsa_nn_accelerator_enabled(DSA_NN_ACCEL_POOL)) {
    const auto status = riscv_nn_execute_prepared_s8(
        data.prepared, input->data.int8, output->data.int8);
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
    return kTfLiteOk;
  }
#endif
  TFLITE_DCHECK((input->type == kTfLiteInt8) || (input->type == kTfLiteInt16));

  RuntimeShape input_shape = micro::GetTensorShape(input);
  TFLITE_DCHECK_EQ(input_shape.DimensionsCount(), 4);

  RuntimeShape output_shape = micro::GetTensorShape(output);
  TFLITE_DCHECK_EQ(output_shape.DimensionsCount(), 4);

  nmsis_nn_dims input_dims;
  nmsis_nn_dims output_dims;
  nmsis_nn_pool_params pool_params;
  nmsis_nn_dims filter_dims;
  nmsis_nn_context ctx;

  PopulateCommonParams(context, &input_dims, &output_dims, &pool_params, &ctx,
                       &filter_dims, data, input_shape, output_shape, params);

  if (input->type == kTfLiteInt8) {
    const riscv_nmsis_nn_status status =
        riscv_avgpool_s8(&ctx, &pool_params, &input_dims,
                         micro::GetTensorData<int8_t>(input), &filter_dims,
                         &output_dims, micro::GetTensorData<int8_t>(output));
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
  } else {
    const riscv_nmsis_nn_status status =
        riscv_avgpool_s16(&ctx, &pool_params, &input_dims,
                          micro::GetTensorData<int16_t>(input), &filter_dims,
                          &output_dims, micro::GetTensorData<int16_t>(output));
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
  }
  return kTfLiteOk;
}

TfLiteStatus MaxEvalQuantized(TfLiteContext* context, const TfLiteNode* node,
                              const TfLitePoolParams* params,
                              const OpData& data, const TfLiteEvalTensor* input,
                              TfLiteEvalTensor* output) {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  if (data.prepared && data.prepared->valid == DSA_PREPARED_VALID &&
      dsa_nn_accelerator_enabled(DSA_NN_ACCEL_POOL)) {
    const auto status = riscv_nn_execute_prepared_s8(
        data.prepared, input->data.int8, output->data.int8);
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
    return kTfLiteOk;
  }
#endif
  TFLITE_DCHECK((input->type == kTfLiteInt8) || (input->type == kTfLiteInt16));

  RuntimeShape input_shape = micro::GetTensorShape(input);
  TFLITE_DCHECK_EQ(input_shape.DimensionsCount(), 4);

  RuntimeShape output_shape = micro::GetTensorShape(output);
  TFLITE_DCHECK_EQ(output_shape.DimensionsCount(), 4);

  nmsis_nn_dims input_dims;
  nmsis_nn_dims output_dims;
  nmsis_nn_pool_params pool_params;
  nmsis_nn_dims filter_dims;
  nmsis_nn_context ctx;

  PopulateCommonParams(context, &input_dims, &output_dims, &pool_params, &ctx,
                       &filter_dims, data, input_shape, output_shape, params);

  if (input->type == kTfLiteInt8) {
    const riscv_nmsis_nn_status status =
        riscv_max_pool_s8(&ctx, &pool_params, &input_dims,
                          micro::GetTensorData<int8_t>(input), &filter_dims,
                          &output_dims, micro::GetTensorData<int8_t>(output));
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
  } else {
    const riscv_nmsis_nn_status status =
        riscv_max_pool_s16(&ctx, &pool_params, &input_dims,
                           micro::GetTensorData<int16_t>(input), &filter_dims,
                           &output_dims, micro::GetTensorData<int16_t>(output));
    TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
  }

  return kTfLiteOk;
}

void* Init(TfLiteContext* context, const char* buffer, size_t length) {
  TFLITE_DCHECK(context->AllocatePersistentBuffer != nullptr);
  auto* data = static_cast<OpData*>(
      context->AllocatePersistentBuffer(context, sizeof(OpData)));
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  if (data) data->prepared = nullptr;
#endif
  return data;
}

TfLiteStatus MaxPrepare(TfLiteContext* context, TfLiteNode* node) {
  TF_LITE_ENSURE_STATUS(PoolingPrepare(context, node));
  // Set buffer index to a reset value
  static_cast<OpData*>(node->user_data)->buffer_idx = -1;
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  MicroContext* micro_context = GetMicroContext(context);
  TfLiteTensor* input =
      micro_context->AllocateTempInputTensor(node, kPoolingInputTensor);
  TfLiteTensor* output =
      micro_context->AllocateTempOutputTensor(node, kPoolingOutputTensor);
  TF_LITE_ENSURE(context, input && output);
  TF_LITE_ENSURE_STATUS(PrepareSpatial(context,node,static_cast<OpData*>(node->user_data),
                 static_cast<const TfLitePoolParams*>(node->builtin_data),
                 input, output, DSA_VECTOR_OP_MAXPOOL_S8));
  micro_context->DeallocateTempTfLiteTensor(output);
  micro_context->DeallocateTempTfLiteTensor(input);
#endif
  return kTfLiteOk;
}

TfLiteStatus AveragePrepare(TfLiteContext* context, TfLiteNode* node) {
  TF_LITE_ENSURE_STATUS(PoolingPrepare(context, node));

  MicroContext* micro_context = GetMicroContext(context);

  TfLiteTensor* input =
      micro_context->AllocateTempInputTensor(node, kPoolingInputTensor);
  TfLiteTensor* output =
      micro_context->AllocateTempOutputTensor(node, kPoolingOutputTensor);

  if (input->type == kTfLiteInt8 || input->type == kTfLiteInt16) {
    RuntimeShape input_shape = GetTensorShape(input);
    TFLITE_DCHECK_EQ(input_shape.DimensionsCount(), 4);

    RuntimeShape output_shape = GetTensorShape(output);
    TFLITE_DCHECK_EQ(output_shape.DimensionsCount(), 4);

    const int depth = MatchingDim(input_shape, 3, output_shape, 3);
    const int output_width = output_shape.Dims(2);

    const int32_t buffer_size =
        input->type == kTfLiteInt16
            ? riscv_avgpool_s16_get_buffer_size(output_width, depth)
            : riscv_avgpool_s8_get_buffer_size(output_width, depth);

    auto* data = static_cast<OpData*>(node->user_data);
    if (buffer_size > 0) {
      TF_LITE_ENSURE_STATUS(context->RequestScratchBufferInArena(
          context, buffer_size, &data->buffer_idx));
    } else {
      data->buffer_idx = -1;
    }
  }

#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  TF_LITE_ENSURE_STATUS(PrepareSpatial(context,node,static_cast<OpData*>(node->user_data),
                 static_cast<const TfLitePoolParams*>(node->builtin_data),
                 input, output, DSA_VECTOR_OP_AVGPOOL_S8));
#endif
  micro_context->DeallocateTempTfLiteTensor(output);
  micro_context->DeallocateTempTfLiteTensor(input);
  return kTfLiteOk;
}

TfLiteStatus AverageEval(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->builtin_data != nullptr);
  auto* params = reinterpret_cast<TfLitePoolParams*>(node->builtin_data);

  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  const TfLiteEvalTensor* input =
      micro::GetEvalInput(context, node, kPoolingInputTensor);
  TfLiteEvalTensor* output =
      micro::GetEvalOutput(context, node, kPoolingOutputTensor);

  // Inputs and outputs share the same type, guaranteed by the converter.
  if (input->type == kTfLiteFloat32) {
    AveragePoolingEvalFloat(context, node, params, &data.reference_op_data,
                            input, output);
  } else if (input->type == kTfLiteInt8 || input->type == kTfLiteInt16) {
    return AverageEvalQuantized(context, node, params, data, input, output);
  } else {
    MicroPrintf("Input type %s is not currently supported",
                TfLiteTypeGetName(input->type));
    return kTfLiteError;
  }

  return kTfLiteOk;
}

TfLiteStatus AverageEvalInt8(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->builtin_data != nullptr);
  auto* params = reinterpret_cast<TfLitePoolParams*>(node->builtin_data);

  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  const TfLiteEvalTensor* input =
      micro::GetEvalInput(context, node, kPoolingInputTensor);
  TFLITE_DCHECK(input->type == kTfLiteInt8);
  TfLiteEvalTensor* output =
      micro::GetEvalOutput(context, node, kPoolingOutputTensor);

  return AverageEvalQuantized(context, node, params, data, input, output);
}

TfLiteStatus AverageEvalInt16(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->builtin_data != nullptr);
  auto* params = reinterpret_cast<TfLitePoolParams*>(node->builtin_data);

  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  const TfLiteEvalTensor* input =
      micro::GetEvalInput(context, node, kPoolingInputTensor);
  TFLITE_DCHECK(input->type == kTfLiteInt16);
  TfLiteEvalTensor* output =
      micro::GetEvalOutput(context, node, kPoolingOutputTensor);

  return AverageEvalQuantized(context, node, params, data, input, output);
}
TfLiteStatus MaxEval(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->builtin_data != nullptr);
  auto* params = reinterpret_cast<TfLitePoolParams*>(node->builtin_data);

  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  const TfLiteEvalTensor* input =
      micro::GetEvalInput(context, node, kPoolingInputTensor);
  TfLiteEvalTensor* output =
      micro::GetEvalOutput(context, node, kPoolingOutputTensor);

  if (input->type == kTfLiteFloat32) {
    MaxPoolingEvalFloat(context, node, params, &data.reference_op_data, input,
                        output);
  } else if (input->type == kTfLiteInt8 || input->type == kTfLiteInt16) {
    return MaxEvalQuantized(context, node, params, data, input, output);
  } else {
    MicroPrintf("Input type %s is not currently supported",
                TfLiteTypeGetName(input->type));
    return kTfLiteError;
  }

  return kTfLiteOk;
}

TfLiteStatus MaxEvalInt8(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->builtin_data != nullptr);
  auto* params = reinterpret_cast<TfLitePoolParams*>(node->builtin_data);

  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  const TfLiteEvalTensor* input =
      micro::GetEvalInput(context, node, kPoolingInputTensor);
  TFLITE_DCHECK(input->type == kTfLiteInt8);
  TfLiteEvalTensor* output =
      micro::GetEvalOutput(context, node, kPoolingOutputTensor);

  return MaxEvalQuantized(context, node, params, data, input, output);
}

TfLiteStatus MaxEvalInt16(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->builtin_data != nullptr);
  auto* params = reinterpret_cast<TfLitePoolParams*>(node->builtin_data);

  TFLITE_DCHECK(node->user_data != nullptr);
  const OpData& data = *(static_cast<const OpData*>(node->user_data));

  const TfLiteEvalTensor* input =
      micro::GetEvalInput(context, node, kPoolingInputTensor);
  TFLITE_DCHECK(input->type == kTfLiteInt16);
  TfLiteEvalTensor* output =
      micro::GetEvalOutput(context, node, kPoolingOutputTensor);

  return MaxEvalQuantized(context, node, params, data, input, output);
}

}  // namespace

TFLMRegistration Register_AVERAGE_POOL_2D_INT8() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(Init, AveragePrepare, nmsis_nn::InvokePrepared<OpData,AverageEvalInt8,DSA_NN_ACCEL_POOL>);
#else
  return tflite::micro::RegisterOp(Init, AveragePrepare, AverageEvalInt8);
#endif
}

TFLMRegistration Register_AVERAGE_POOL_2D_INT16() {
  return tflite::micro::RegisterOp(Init, AveragePrepare, AverageEvalInt16);
}

TFLMRegistration Register_AVERAGE_POOL_2D() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(Init, AveragePrepare, nmsis_nn::InvokePrepared<OpData,AverageEval,DSA_NN_ACCEL_POOL>);
#else
  return tflite::micro::RegisterOp(Init, AveragePrepare, AverageEval);
#endif
}

TFLMRegistration Register_MAX_POOL_2D_INT8() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(Init, MaxPrepare, nmsis_nn::InvokePrepared<OpData,MaxEvalInt8,DSA_NN_ACCEL_POOL>);
#else
  return tflite::micro::RegisterOp(Init, MaxPrepare, MaxEvalInt8);
#endif
}

TFLMRegistration Register_MAX_POOL_2D_INT16() {
  return tflite::micro::RegisterOp(Init, MaxPrepare, MaxEvalInt16);
}

TFLMRegistration Register_MAX_POOL_2D() {
#if DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(Init, MaxPrepare, nmsis_nn::InvokePrepared<OpData,MaxEval,DSA_NN_ACCEL_POOL>);
#else
  return tflite::micro::RegisterOp(Init, MaxPrepare, MaxEval);
#endif
}

}  // namespace tflite
