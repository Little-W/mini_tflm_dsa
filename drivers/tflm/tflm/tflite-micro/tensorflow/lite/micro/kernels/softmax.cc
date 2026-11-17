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

#include "tensorflow/lite/micro/kernels/softmax.h"

#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/kernels/internal/quantization_util.h"
#include "tensorflow/lite/kernels/internal/reference/softmax.h"
#include "tensorflow/lite/kernels/internal/tensor_ctypes.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/op_macros.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/micro_log.h"

#ifndef DSA_NN_VECTOR_ENABLE
#define DSA_NN_VECTOR_ENABLE 1
#endif
#if DSA_NN_VECTOR_ENABLE
#include "dsa_softmax.h"
#include "riscv_nn_dsa.h"
#include "tensorflow/lite/micro/kernels/nmsis_nn/prepared.h"
#include "tensorflow/lite/micro/kernels/softmax_vce.h"
#include "tensorflow/lite/micro/micro_context.h"
#include "tensorflow/lite/micro/micro_utils.h"
#endif

namespace tflite {
namespace {

#if DSA_NN_VECTOR_ENABLE
struct SoftmaxVceData {
  SoftmaxParams reference;
  nmsis_nn_prepared_softmax_s8_t* prepared;
  int32_t* table;
  // Shapes and eval-tensor objects persist after Prepare. Tensor data addresses
  // are read from those objects and validated for each invocation.
  const TfLiteEvalTensor* input;
  TfLiteEvalTensor* output;
};

void* SoftmaxVceInit(TfLiteContext* context, const char*, size_t) {
  auto* data=static_cast<SoftmaxVceData*>(
      context->AllocatePersistentBuffer(context,sizeof(SoftmaxVceData)));
  if (data) *data={};
  return data;
}

TfLiteStatus SoftmaxVcePrepare(TfLiteContext* context, TfLiteNode* node) {
  TF_LITE_ENSURE_STATUS(SoftmaxPrepare(context,node));
  auto* data=static_cast<SoftmaxVceData*>(node->user_data);
  if (data->prepared) *data->prepared={};
  data->input=tflite::micro::GetEvalInput(context,node,0);
  data->output=tflite::micro::GetEvalOutput(context,node,0);
  MicroContext* micro_context=GetMicroContext(context);
  TfLiteTensor* input=micro_context->AllocateTempInputTensor(node,0);
  TfLiteTensor* output=micro_context->AllocateTempOutputTensor(node,0);
  if (!input || !output) {
    if (output) micro_context->DeallocateTempTfLiteTensor(output);
    if (input) micro_context->DeallocateTempTfLiteTensor(input);
    return kTfLiteError;
  }
  TfLiteStatus preparation_status=kTfLiteOk;
  const int depth=input->dims->data[input->dims->size-1];
  if (input->type==kTfLiteInt8 && output->type==kTfLiteInt8 &&
      depth>0 && dsa_nn_accelerator_enabled(DSA_NN_ACCEL_SOFTMAX) &&
      dsa_softmax_supported(static_cast<uint32_t>(depth))) {
    uint64_t elements=1;
    for (int i=0;i<input->dims->size;i++) {
      if (input->dims->data[i]<=0 ||
          elements>UINT32_MAX/static_cast<uint32_t>(input->dims->data[i])) {
        elements=0;
        break;
      }
      elements*=static_cast<uint32_t>(input->dims->data[i]);
    }
    if (elements && elements%static_cast<uint32_t>(depth)==0) {
      if (!data->table)
        data->table=static_cast<int32_t*>(context->AllocatePersistentBuffer(context,256*sizeof(int32_t)));
      if (!data->table) preparation_status=kTfLiteError;
      else {
        PopulateSoftmaxVceTable(data->reference,data->table);
        const uint32_t rows=static_cast<uint32_t>(elements)/static_cast<uint32_t>(depth);
        preparation_status=nmsis_nn::InitializeLayerConfig(
            context,&data->prepared,[&](nmsis_nn_prepared_softmax_s8_t* configuration) {
              return riscv_nn_prepare_softmax_s8(configuration,rows,
                                                 static_cast<uint32_t>(depth),data->table);
            });
      }
    }
  }
  micro_context->DeallocateTempTfLiteTensor(input);
  micro_context->DeallocateTempTfLiteTensor(output);
  return preparation_status;
}
#endif

void SoftmaxQuantized(const TfLiteEvalTensor* input, TfLiteEvalTensor* output,
                      const SoftmaxParams& op_data) {
  if (input->type == kTfLiteInt8) {
    if (output->type == kTfLiteInt16) {
      tflite::reference_ops::Softmax(
          op_data, tflite::micro::GetTensorShape(input),
          tflite::micro::GetTensorData<int8_t>(input),
          tflite::micro::GetTensorShape(output),
          tflite::micro::GetTensorData<int16_t>(output));
    } else {
      tflite::reference_ops::Softmax(
          op_data, tflite::micro::GetTensorShape(input),
          tflite::micro::GetTensorData<int8_t>(input),
          tflite::micro::GetTensorShape(output),
          tflite::micro::GetTensorData<int8_t>(output));
    }
  } else {
    tflite::reference_ops::SoftmaxInt16(
        op_data, tflite::micro::GetTensorShape(input),
        tflite::micro::GetTensorData<int16_t>(input),
        tflite::micro::GetTensorShape(output),
        tflite::micro::GetTensorData<int16_t>(output));
  }
}

TfLiteStatus SoftmaxEval(TfLiteContext* context, TfLiteNode* node) {
  TFLITE_DCHECK(node->user_data != nullptr);
#if DSA_NN_VECTOR_ENABLE
  const auto* accelerated=static_cast<const SoftmaxVceData*>(node->user_data);
  const TfLiteEvalTensor* input=accelerated->input;
  TfLiteEvalTensor* output=accelerated->output;
  const nmsis_nn_prepared_softmax_s8_t* prepared=accelerated->prepared;
  if (input->type==kTfLiteInt8 && output->type==kTfLiteInt8 &&
      prepared && prepared->plan.valid && dsa_nn_accelerator_enabled(DSA_NN_ACCEL_SOFTMAX)) {
    const uint32_t count=prepared->elements;
    const int8_t* in=tflite::micro::GetTensorData<int8_t>(input);
    int8_t* out=tflite::micro::GetTensorData<int8_t>(output);
    const uintptr_t ia=reinterpret_cast<uintptr_t>(in), oa=reinterpret_cast<uintptr_t>(out);
    if (dsa_softmax_span(in,count) && dsa_softmax_span(out,count) &&
        (ia+count<=oa || oa+count<=ia)) {
      TF_LITE_ENSURE_EQ(context,riscv_nn_execute_prepared_softmax_s8(prepared,in,out),
                       RISCV_NMSIS_NN_SUCCESS);
      return kTfLiteOk;
    }
  }
#else
  const TfLiteEvalTensor* input=tflite::micro::GetEvalInput(context,node,0);
  TfLiteEvalTensor* output=tflite::micro::GetEvalOutput(context,node,0);
#endif
  const SoftmaxParams& op_data=*static_cast<const SoftmaxParams*>(node->user_data);

  switch (input->type) {
    case kTfLiteFloat32: {
      tflite::reference_ops::Softmax(
          op_data, tflite::micro::GetTensorShape(input),
          tflite::micro::GetTensorData<float>(input),
          tflite::micro::GetTensorShape(output),
          tflite::micro::GetTensorData<float>(output));
      return kTfLiteOk;
    }
    case kTfLiteInt8:
    case kTfLiteInt16: {
      SoftmaxQuantized(input, output, op_data);
      return kTfLiteOk;
    }
    default:
      MicroPrintf("Type %s (%d) not supported.", TfLiteTypeGetName(input->type),
                  input->type);
      return kTfLiteError;
  }
}
}  // namespace

TFLMRegistration Register_SOFTMAX() {
#if DSA_NN_VECTOR_ENABLE
  return tflite::micro::RegisterOp(SoftmaxVceInit, SoftmaxVcePrepare, SoftmaxEval);
#else
  return tflite::micro::RegisterOp(SoftmaxInit, SoftmaxPrepare, SoftmaxEval);
#endif
}

}  // namespace tflite
