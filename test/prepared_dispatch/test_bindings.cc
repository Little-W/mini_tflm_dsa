/* SPDX-License-Identifier: Apache-2.0 */
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "tensorflow/lite/micro/kernels/nmsis_nn/prepared.h"

namespace {
struct Data {
  dsa_prepared_t* prepared;
  tflite::nmsis_nn::PreparedTensorBindings bindings;
};
TfLiteEvalTensor tensors[4]{};
unsigned queries, submissions, fallbacks, allocations, initializations;
uint32_t mask=DSA_NN_ACCEL_FC, result;
alignas(16) unsigned char arena[2*sizeof(dsa_prepared_t)+64]{};
size_t arena_used;
bool allocation_failure;
const dsa_prepared_t* observed_configuration;
const void* observed_input;
void* observed_output;

void* Allocate(TfLiteContext*,size_t bytes) {
  const size_t start=(arena_used+15u)&~size_t(15u);
  if (allocation_failure || bytes>sizeof(arena)-start) return nullptr;
  arena_used=start+bytes;
  ++allocations;
  return arena+start;
}

uint32_t PrepareConfiguration(dsa_prepared_t* prepared) {
  ++initializations;
  prepared->valid=DSA_PREPARED_VALID;
  prepared->source_filter_base=0x2000;
  prepared->registers[0].value=0x5000;
  prepared->registers[1].value=0x3000;
  prepared->memory_policy_valid=1u;
  prepared->ia_bank_count=1u;
  prepared->ps_control=DSA_PS_CTRL_BOUND_S24;
  return DSA_SUCCESS;
}

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
extern "C" uint32_t dsa_prepared_execute(const dsa_prepared_t* configuration,const void* input,void* output) {
  ++submissions;
  observed_configuration=configuration;
  observed_input=input;
  observed_output=output;
  return result;
}

int main() {
  struct {int size;int data[3];} inputs{3,{0,1,2}},outputs{1,{3,0,0}};
  TfLiteContext context{};
  context.GetEvalTensor=GetTensor;
  context.AllocatePersistentBuffer=Allocate;
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
  tensors[0].data.raw=nullptr;
  tensors[3].data.raw=nullptr;
  assert(tflite::nmsis_nn::InitializeLayerConfig(
      &context,&data.prepared,PrepareConfiguration)==kTfLiteOk);
  assert(allocations==1 && initializations==1);
  assert(reinterpret_cast<unsigned char*>(data.prepared)>=arena &&
         reinterpret_cast<unsigned char*>(data.prepared)+sizeof(*data.prepared)<=arena+sizeof(arena));
  const dsa_prepared_t snapshot=*data.prepared;
  data.bindings.Prepare(&context,&node,true);
  const unsigned prepared_queries=queries;
  tensors[0].data.raw=reinterpret_cast<char*>(uintptr_t(0x1000));
  tensors[3].data.raw=reinterpret_cast<char*>(uintptr_t(0x4000));
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==1 && !fallbacks);
  assert(queries==prepared_queries);
  assert(observed_configuration==data.prepared);
  assert(observed_input==tensors[0].data.raw && observed_output==tensors[3].data.raw);

  tensors[0].data.raw=reinterpret_cast<char*>(uintptr_t(0x6000));
  tensors[3].data.raw=reinterpret_cast<char*>(uintptr_t(0x7000));
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && !fallbacks);
  assert(observed_input==tensors[0].data.raw && observed_output==tensors[3].data.raw);
  assert(queries==prepared_queries);
  assert(initializations==1 && allocations==1);
  assert(std::memcmp(&snapshot,data.prepared,sizeof(snapshot))==0);

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
  data.prepared->valid=0;
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==2 && fallbacks==5);
  data.prepared->valid=DSA_PREPARED_VALID;
  result=DSA_ERR_BUSY;
  assert(Invoke(&context,&node)==kTfLiteError && submissions==3 && fallbacks==5);
  result=0u;

  inputs.size=2;
  data.prepared->registers[1].value=0;
  data.bindings.Prepare(&context,&node,true);
  assert(!data.bindings.bias);
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==4 && fallbacks==5);
  inputs.size=1;
  data.bindings.Prepare(&context,&node,false);
  assert(!data.bindings.filter && !data.bindings.bias);
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==5 && fallbacks==5);
  assert(initializations==1 && allocations==1);

  auto* saved=data.prepared;
  assert(tflite::nmsis_nn::InitializeLayerConfig(
      &context,&data.prepared,PrepareConfiguration)==kTfLiteOk);
  assert(data.prepared==saved && allocations==1 && initializations==2);
  assert(std::memcmp(&snapshot,data.prepared,sizeof(snapshot))==0);
  assert(tflite::nmsis_nn::InitializeLayerConfig(
      &context,&data.prepared,[](dsa_prepared_t* configuration) {
        ++initializations;
        configuration->valid=DSA_PREPARED_VALID;
        return DSA_ERR_UNSUPPORTED;
      })==kTfLiteOk);
  const dsa_prepared_t empty{};
  assert(data.prepared==saved && std::memcmp(&empty,data.prepared,sizeof(empty))==0);
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==5 && fallbacks==6);
  data.prepared=nullptr;
  assert(Invoke(&context,&node)==kTfLiteOk && submissions==5 && fallbacks==7);
  allocation_failure=true;
  assert(tflite::nmsis_nn::InitializeLayerConfig(
      &context,&data.prepared,PrepareConfiguration)==kTfLiteError);
  assert(!data.prepared && allocations==1 && initializations==3);
  allocation_failure=false;

  nmsis_nn_prepared_softmax_s8_t* softmax=nullptr;
  assert(tflite::nmsis_nn::InitializeLayerConfig(
      &context,&softmax,[](nmsis_nn_prepared_softmax_s8_t* configuration) {
        configuration->rows=2u;
        configuration->elements=20u;
        configuration->plan.depth=10u;
        configuration->plan.valid=0x534d5831u;
        return RISCV_NMSIS_NN_SUCCESS;
      })==kTfLiteOk);
  assert(softmax && softmax->rows==2u && allocations==2);
  const auto* softmax_address=softmax;
  assert(tflite::nmsis_nn::InitializeLayerConfig(
      &context,&softmax,[](nmsis_nn_prepared_softmax_s8_t*) {
        return RISCV_NMSIS_NN_NO_IMPL_ERROR;
      })==kTfLiteOk);
  assert(softmax==softmax_address && !softmax->plan.valid && !softmax->rows && allocations==2);
  std::printf("PREPARED_BINDINGS_PASS allocations=%u initializations=%u submissions=%u fallbacks=%u\n",
              allocations,initializations,submissions,fallbacks);
}
