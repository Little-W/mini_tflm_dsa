/* SPDX-License-Identifier: Apache-2.0 */
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "tensorflow/lite/micro/kernels/nmsis_nn/prepared.h"

namespace {
struct Data {
  dsa_prepared_t prepared;
  tflite::nmsis_nn::PreparedTensorBindings bindings;
};
TfLiteEvalTensor tensors[4]{};
unsigned queries, submissions, fallbacks;
uint32_t mask=DSA_NN_ACCEL_FC, result;
const void* observed_input;
void* observed_output;

TfLiteEvalTensor* GetTensor(const TfLiteContext*, int index) {
  assert(index>=0 && index<4);
  ++queries;
  return &tensors[index];
}
TfLiteStatus Fallback(TfLiteContext*,TfLiteNode*) {
  ++fallbacks;
  return kTfLiteOk;
}
TfLiteStatus Invoke(TfLiteContext* context,TfLiteNode* node) {
  return tflite::nmsis_nn::InvokePrepared<Data,Fallback,DSA_NN_ACCEL_FC>(context,node);
}
}  // namespace

extern "C" uint32_t dsa_nn_get_accelerators() {return mask;}
extern "C" uint32_t dsa_prepared_execute(const dsa_prepared_t*,const void* input,void* output) {
  ++submissions;
  observed_input=input;
  observed_output=output;
  return result;
}

int main() {
  struct {int size;int data[3];} inputs{3,{0,1,2}},outputs{1,{3,0,0}};
  TfLiteContext context{};
  context.GetEvalTensor=GetTensor;
  TfLiteNode node{};
  node.inputs=reinterpret_cast<TfLiteIntArray*>(&inputs);
  node.outputs=reinterpret_cast<TfLiteIntArray*>(&outputs);
  Data data{};
  node.user_data=&data;
  for (unsigned i=0;i<4;i++) {
    tensors[i].type=kTfLiteInt8;
    tensors[i].data.raw=reinterpret_cast<char*>(uintptr_t(0x1000+0x1000*i));
  }
  tensors[2].type=kTfLiteInt32;
  data.prepared.valid=DSA_PREPARED_VALID;
  data.prepared.source_filter_base=0x2000;
  data.prepared.registers[0].value=0x5000;
  data.prepared.registers[1].value=0x3000;
  data.bindings.Prepare(&context,&node,true);
  const unsigned prepared_queries=queries;
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==1 && !fallbacks);
  assert(queries==prepared_queries);
  assert(observed_input==tensors[0].data.raw && observed_output==tensors[3].data.raw);

  tensors[0].data.raw=reinterpret_cast<char*>(uintptr_t(0x6000));
  tensors[3].data.raw=reinterpret_cast<char*>(uintptr_t(0x7000));
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && !fallbacks);
  assert(observed_input==tensors[0].data.raw && observed_output==tensors[3].data.raw);
  assert(queries==prepared_queries);

  mask=0;
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && fallbacks==1);
  mask=DSA_NN_ACCEL_FC;
  tensors[1].data.raw=reinterpret_cast<char*>(uintptr_t(0x8000));
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && fallbacks==2);
  tensors[1].data.raw=reinterpret_cast<char*>(uintptr_t(0x2000));
  tensors[2].data.raw=reinterpret_cast<char*>(uintptr_t(0x9000));
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && fallbacks==3);
  tensors[2].data.raw=reinterpret_cast<char*>(uintptr_t(0x3000));
  tensors[3].type=kTfLiteInt16;
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && fallbacks==4);
  tensors[3].type=kTfLiteInt8;
  data.prepared.valid=0;
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && fallbacks==5);
  data.prepared.valid=DSA_PREPARED_VALID;
  result=DSA_ERR_BUSY;
  assert(Invoke(&context,&node)==kTfLiteError && submissions==3 && fallbacks==5);
  result=0u;

  inputs.size=2;
  data.prepared.registers[1].value=0;
  data.bindings.Prepare(&context,&node,true);
  assert(!data.bindings.bias);
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==4 && fallbacks==5);
  inputs.size=1;
  data.bindings.Prepare(&context,&node,false);
  assert(!data.bindings.filter && !data.bindings.bias);
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==5 && fallbacks==5);
  std::puts("PREPARED_BINDINGS_PASS checks=10");
}
