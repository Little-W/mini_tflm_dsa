/* SPDX-License-Identifier: Apache-2.0 */
#include <cassert>
#include <cstdint>
#include <cstring>
#include "riscv_vector_acc.h"
#include "tensorflow/lite/micro/kernels/add.h"
#include "tensorflow/lite/micro/kernels/kernel_util.h"

namespace tflite {
TfLiteStatus EvalAddQuantized(TfLiteContext*, TfLiteNode*, TfLiteAddParams*,
    const OpDataAdd*, const TfLiteEvalTensor*, const TfLiteEvalTensor*, TfLiteEvalTensor*);
namespace micro {
const RuntimeShape GetTensorShape(const TfLiteEvalTensor* tensor) {
  return RuntimeShape(tensor->dims->size, tensor->dims->data);
}
}
}
extern "C" const char* TfLiteTypeGetName(TfLiteType) { return "test"; }
static int calls, device_mode;
extern "C" int riscv_add_s8_try_dsa(const dsa_vector_add_params_t *p,
    const int8_t*, const int8_t*, int8_t* output, int32_t n, int32_t offset,
    int32_t minimum, int32_t maximum, riscv_nmsis_nn_status* status) {
  ++calls;
  assert(p->left_shift==1 && p->input1_multiplier==1073741824 && p->output_shift==1);
  assert(offset==0 && minimum==-128 && maximum==127);
  if (device_mode==0) return 0;
  if (device_mode==2) { *status=RISCV_NMSIS_NN_NO_IMPL_ERROR;return 1; }
  for(int i=0;i<n;++i)output[i]=42;
  *status=RISCV_NMSIS_NN_SUCCESS;return 1;
}
int main() {
  struct Shape { int size; int data[2]; } vector_shape={2,{1,3}},scalar_shape={2,{1,1}};
  int8_t a[3]={-3,4,120},b[3]={1,-1,30},output[3]={};
  TfLiteEvalTensor first={},second={},result={};
  first.type=second.type=result.type=kTfLiteInt8;
  first.dims=second.dims=result.dims=reinterpret_cast<TfLiteIntArray*>(&vector_shape);
  first.data.int8=a;second.data.int8=b;result.data.int8=output;
  tflite::OpDataAdd data={};
  data.input1_multiplier=data.input2_multiplier=data.output_multiplier=1073741824;
  data.left_shift=data.output_shift=1;data.output_activation_min=-128;data.output_activation_max=127;
  TfLiteContext context={};TfLiteNode node={};TfLiteAddParams params={};
  auto invoke=[&](){return tflite::EvalAddQuantized(&context,&node,&params,&data,&first,&second,&result);};
  device_mode=0;calls=0;assert(invoke()==kTfLiteOk);
  assert(output[0]==-2 && output[1]==3 && output[2]==127);
  assert(calls==DSA_NN_VECTOR_ENABLE);
  device_mode=1;calls=0;assert(invoke()==kTfLiteOk);
#if DSA_NN_VECTOR_ENABLE
  assert(calls==1 && output[0]==42 && output[1]==42 && output[2]==42);
  device_mode=2;calls=0;assert(invoke()==kTfLiteError && calls==1);
#else
  assert(calls==0 && output[0]==-2 && output[1]==3 && output[2]==127);
#endif
  device_mode=1;calls=0;second.dims=reinterpret_cast<TfLiteIntArray*>(&scalar_shape);
  b[0]=5;assert(invoke()==kTfLiteOk && calls==0);
  assert(output[0]==2 && output[1]==9 && output[2]==125);
  second.dims=reinterpret_cast<TfLiteIntArray*>(&vector_shape);b[0]=1;
  device_mode=0;calls=0;result.data.int8=a;assert(invoke()==kTfLiteOk);
  assert(a[0]==-2 && a[1]==3 && a[2]==127);
  return 0;
}
