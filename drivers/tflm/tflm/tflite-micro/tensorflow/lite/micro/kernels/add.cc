/* Copyright 2021 The TensorFlow Authors. All Rights Reserved.

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

#include "tensorflow/lite/kernels/internal/reference/add.h"

#include <limits>

#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/internal/quantization_util.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/add.h"
#include "tensorflow/lite/kernels/internal/reference/process_broadcast_shapes.h"
#include "tensorflow/lite/kernels/internal/tensor_ctypes.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/op_macros.h"
#include "tensorflow/lite/micro/kernels/add.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/memory_helpers.h"
#include "tensorflow/lite/micro/micro_log.h"

#if defined(NMSIS_NN)
#include "riscv_vector_acc.h"
#include "riscv_nn_prepared.h"
#include "tensorflow/lite/micro/micro_context.h"
#endif

namespace tflite {

#if defined(NMSIS_NN) && DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
struct OpDataAddPrepared {
  OpDataAdd reference;
  dsa_prepared_add_s8_t prepared;
};

TfLiteStatus AddPreparePrepared(TfLiteContext* context, TfLiteNode* node) {
  auto* data = static_cast<OpDataAddPrepared*>(node->user_data);
  data->prepared.valid = 0u;
  TF_LITE_ENSURE_STATUS(AddPrepare(context, node));
  MicroContext* micro_context = GetMicroContext(context);
  TfLiteTensor* input1 =
      micro_context->AllocateTempInputTensor(node, kAddInputTensor1);
  TfLiteTensor* input2 =
      micro_context->AllocateTempInputTensor(node, kAddInputTensor2);
  TfLiteTensor* output =
      micro_context->AllocateTempOutputTensor(node, kAddOutputTensor);
  TF_LITE_ENSURE(context, input1 && input2 && output);
  if (input1->type == kTfLiteInt8 && input2->type == kTfLiteInt8 &&
      output->type == kTfLiteInt8 && !data->reference.requires_broadcast) {
    const OpDataAdd& reference = data->reference;
    const dsa_vector_add_params_t quantization = {
        reference.input1_offset, reference.input2_offset,
        reference.input1_multiplier, reference.input1_shift,
        reference.input2_multiplier, reference.input2_shift,
        reference.left_shift, reference.output_multiplier, reference.output_shift};
    const int length = NumElements(output->dims);
    if (length > 0 && NumElements(input1->dims) == length &&
        NumElements(input2->dims) == length) {
      (void)dsa_prepare_add_s8(&data->prepared, static_cast<uint32_t>(length),
                             &quantization, reference.output_offset,
                             reference.output_activation_min,
                             reference.output_activation_max);
    }
  }
  micro_context->DeallocateTempTfLiteTensor(output);
  micro_context->DeallocateTempTfLiteTensor(input2);
  micro_context->DeallocateTempTfLiteTensor(input1);
  return kTfLiteOk;
}
#endif

TfLiteStatus EvalAdd(TfLiteContext* context, TfLiteNode* node,
                     TfLiteAddParams* params, const OpDataAdd* data,
                     const TfLiteEvalTensor* input1,
                     const TfLiteEvalTensor* input2, TfLiteEvalTensor* output) {
  switch (output->type) {
    case kTfLiteFloat32: {
      tflite::ArithmeticParams op_params = {};
      SetActivationParams(data->output_activation_min_f32,
                          data->output_activation_max_f32, &op_params);
      if (data->requires_broadcast) {
        reference_ops::BroadcastAdd4DSlow(
            op_params, tflite::micro::GetTensorShape(input1),
            tflite::micro::GetTensorData<float>(input1),
            tflite::micro::GetTensorShape(input2),
            tflite::micro::GetTensorData<float>(input2),
            tflite::micro::GetTensorShape(output),
            tflite::micro::GetTensorData<float>(output));
      } else {
        reference_ops::Add(op_params, tflite::micro::GetTensorShape(input1),
                           tflite::micro::GetTensorData<float>(input1),
                           tflite::micro::GetTensorShape(input2),
                           tflite::micro::GetTensorData<float>(input2),
                           tflite::micro::GetTensorShape(output),
                           tflite::micro::GetTensorData<float>(output));
      }
    } break;
    case kTfLiteInt32: {
      tflite::ArithmeticParams op_params = {};
      SetActivationParams(std::numeric_limits<int32_t>::lowest(),
                          std::numeric_limits<int32_t>::max(), &op_params);
      if (data->requires_broadcast) {
        reference_ops::BroadcastAdd4DSlow(
            op_params, tflite::micro::GetTensorShape(input1),
            tflite::micro::GetTensorData<int32_t>(input1),
            tflite::micro::GetTensorShape(input2),
            tflite::micro::GetTensorData<int32_t>(input2),
            tflite::micro::GetTensorShape(output),
            tflite::micro::GetTensorData<int32_t>(output));
      } else {
        reference_ops::Add(op_params, tflite::micro::GetTensorShape(input1),
                           tflite::micro::GetTensorData<int32_t>(input1),
                           tflite::micro::GetTensorShape(input2),
                           tflite::micro::GetTensorData<int32_t>(input2),
                           tflite::micro::GetTensorShape(output),
                           tflite::micro::GetTensorData<int32_t>(output));
      }
    } break;
    default:
      MicroPrintf("Type %s (%d) not supported.",
                  TfLiteTypeGetName(output->type), output->type);
      return kTfLiteError;
  }

  return kTfLiteOk;
}

TfLiteStatus EvalAddQuantized(TfLiteContext* context, TfLiteNode* node,
                              TfLiteAddParams* params, const OpDataAdd* data,
                              const TfLiteEvalTensor* input1,
                              const TfLiteEvalTensor* input2,
                              TfLiteEvalTensor* output) {
  tflite::ArithmeticParams op_params = {};
  op_params.left_shift = data->left_shift;
  op_params.input1_offset = data->input1_offset;
  op_params.input1_multiplier = data->input1_multiplier;
  op_params.input1_shift = data->input1_shift;
  op_params.input2_offset = data->input2_offset;
  op_params.input2_multiplier = data->input2_multiplier;
  op_params.input2_shift = data->input2_shift;
  op_params.output_offset = data->output_offset;
  op_params.output_multiplier = data->output_multiplier;
  op_params.output_shift = data->output_shift;
  SetActivationParams(data->output_activation_min, data->output_activation_max,
                      &op_params);
  bool need_broadcast = reference_ops::ProcessBroadcastShapes(
      tflite::micro::GetTensorShape(input1),
      tflite::micro::GetTensorShape(input2), &op_params);

  switch (output->type) {
    case kTfLiteInt8: {
      if (need_broadcast) {
        reference_integer_ops::BroadcastAdd4DSlow(
            op_params, tflite::micro::GetTensorShape(input1),
            tflite::micro::GetTensorData<int8_t>(input1),
            tflite::micro::GetTensorShape(input2),
            tflite::micro::GetTensorData<int8_t>(input2),
            tflite::micro::GetTensorShape(output),
            tflite::micro::GetTensorData<int8_t>(output));
      } else {
#if defined(NMSIS_NN) && DSA_NN_VECTOR_ENABLE
        const dsa_vector_add_params_t quant = {
            data->input1_offset, data->input2_offset,
            data->input1_multiplier, data->input1_shift,
            data->input2_multiplier, data->input2_shift,
            data->left_shift, data->output_multiplier, data->output_shift};
        riscv_nmsis_nn_status status;
        if (riscv_add_s8_try_dsa(&quant,
                tflite::micro::GetTensorData<int8_t>(input1),
                tflite::micro::GetTensorData<int8_t>(input2),
                tflite::micro::GetTensorData<int8_t>(output),
                tflite::micro::GetTensorShape(output).FlatSize(), data->output_offset,
                data->output_activation_min, data->output_activation_max, &status)) {
          TF_LITE_ENSURE_EQ(context, status, RISCV_NMSIS_NN_SUCCESS);
          break;
        }
#endif
        reference_integer_ops::Add(
            op_params, tflite::micro::GetTensorShape(input1),
            tflite::micro::GetTensorData<int8_t>(input1),
            tflite::micro::GetTensorShape(input2),
            tflite::micro::GetTensorData<int8_t>(input2),
            tflite::micro::GetTensorShape(output),
            tflite::micro::GetTensorData<int8_t>(output));
      }
      break;
    }
    case kTfLiteInt16: {
      if (need_broadcast) {
        reference_ops::BroadcastAdd4DSlow(
            op_params, tflite::micro::GetTensorShape(input1),
            tflite::micro::GetTensorData<int16_t>(input1),
            tflite::micro::GetTensorShape(input2),
            tflite::micro::GetTensorData<int16_t>(input2),
            tflite::micro::GetTensorShape(output),
            tflite::micro::GetTensorData<int16_t>(output));
      } else {
        reference_ops::Add(op_params, tflite::micro::GetTensorShape(input1),
                           tflite::micro::GetTensorData<int16_t>(input1),
                           tflite::micro::GetTensorShape(input2),
                           tflite::micro::GetTensorData<int16_t>(input2),
                           tflite::micro::GetTensorShape(output),
                           tflite::micro::GetTensorData<int16_t>(output),
                           false);
      }
      break;
    }
    default:
      MicroPrintf("Type %s (%d) not supported.",
                  TfLiteTypeGetName(output->type), output->type);
      return kTfLiteError;
  }

  return kTfLiteOk;
}

void* AddInit(TfLiteContext* context, const char* buffer, size_t length) {
  TFLITE_DCHECK(context->AllocatePersistentBuffer != nullptr);
#if defined(NMSIS_NN) && DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return context->AllocatePersistentBuffer(context, sizeof(OpDataAddPrepared));
#else
  return context->AllocatePersistentBuffer(context, sizeof(OpDataAdd));
#endif
}

TfLiteStatus AddEval(TfLiteContext* context, TfLiteNode* node) {
  auto* params = reinterpret_cast<TfLiteAddParams*>(node->builtin_data);

  TFLITE_DCHECK(node->user_data != nullptr);
  const OpDataAdd* data = static_cast<const OpDataAdd*>(node->user_data);

  const TfLiteEvalTensor* input1 =
      tflite::micro::GetEvalInput(context, node, kAddInputTensor1);
  const TfLiteEvalTensor* input2 =
      tflite::micro::GetEvalInput(context, node, kAddInputTensor2);
  TfLiteEvalTensor* output =
      tflite::micro::GetEvalOutput(context, node, kAddOutputTensor);

#if defined(NMSIS_NN) && DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  const auto& prepared =
      static_cast<const OpDataAddPrepared*>(node->user_data)->prepared;
  if (prepared.valid == DSA_PREPARED_VALID &&
      dsa_nn_accelerator_enabled(DSA_NN_ACCEL_ADD) &&
      input1->data.raw_const != output->data.raw &&
      input2->data.raw_const != output->data.raw) {
    const uint32_t status = dsa_prepared_add_s8_execute(
        &prepared, input1->data.int8, input2->data.int8, output->data.int8);
    TF_LITE_ENSURE_EQ(context, status, 0u);
    return kTfLiteOk;
  }
#endif

  if (output->type == kTfLiteFloat32 || output->type == kTfLiteInt32) {
    TF_LITE_ENSURE_OK(
        context, EvalAdd(context, node, params, data, input1, input2, output));
  } else if (output->type == kTfLiteInt8 || output->type == kTfLiteInt16) {
    TF_LITE_ENSURE_OK(context, EvalAddQuantized(context, node, params, data,
                                                input1, input2, output));
  } else {
    MicroPrintf("Type %s (%d) not supported.", TfLiteTypeGetName(output->type),
                output->type);
    return kTfLiteError;
  }

  return kTfLiteOk;
}

TFLMRegistration Register_ADD() {
#if defined(NMSIS_NN) && DSA_NN_PREPARED_ENABLE && DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(AddInit, AddPreparePrepared, AddEval);
#else
  return tflite::micro::RegisterOp(AddInit, AddPrepare, AddEval);
#endif
}

}  // namespace tflite
