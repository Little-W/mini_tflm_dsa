/* Copyright 2023 The TensorFlow Authors. All Rights Reserved.

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

#include "tensorflow/lite/micro/kernels/reshape.h"

#include <cstring>

#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/kernels/internal/tensor_ctypes.h"
#include "tensorflow/lite/kernels/kernel_util.h"
#include "tensorflow/lite/kernels/op_macros.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"
#include "tensorflow/lite/micro/memory_helpers.h"
#include "tensorflow/lite/micro/micro_utils.h"

namespace tflite {
namespace {

struct ReshapeOpData {
  const TfLiteEvalTensor* input;
  TfLiteEvalTensor* output;
  size_t input_bytes;
};

void* InitReshape(TfLiteContext* context, const char*, size_t) {
  return context->AllocatePersistentBuffer(context, sizeof(ReshapeOpData));
}

TfLiteStatus PrepareReshape(TfLiteContext* context, TfLiteNode* node) {
  TF_LITE_ENSURE_STATUS(PrepareReshapeReference(context, node));
  auto* data = static_cast<ReshapeOpData*>(node->user_data);
  TF_LITE_ENSURE(context, data != nullptr);
  data->input = tflite::micro::GetEvalInput(context, node, kReshapeInputTensor);
  data->output = tflite::micro::GetEvalOutput(context, node, kReshapeOutputTensor);
  TF_LITE_ENSURE(context, data->input != nullptr && data->output != nullptr);
  TF_LITE_ENSURE_STATUS(TfLiteTypeSizeOf(data->input->type, &data->input_bytes));
  data->input_bytes *= ElementCount(*data->input->dims);
  return kTfLiteOk;
}

TfLiteStatus EvalReshapeReference(TfLiteContext*, TfLiteNode* node) {
  const auto* data = static_cast<const ReshapeOpData*>(node->user_data);
  // 张量描述符在准备阶段固定，数据地址在分配完成后从描述符读取。
  const char* input = data->input->data.raw;
  char* output = data->output->data.raw;
  if (input != output) memcpy(output, input, data->input_bytes);
  return kTfLiteOk;
}

}  // namespace

TFLMRegistration Register_RESHAPE() {
  return tflite::micro::RegisterOp(InitReshape, PrepareReshape,
                                   EvalReshapeReference);
}

}  // namespace tflite
