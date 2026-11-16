/* SPDX-License-Identifier: Apache-2.0 */
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sys/mman.h>
#include <vector>
#include "dsa_softmax.h"
#include "riscv_nn_dsa.h"
#include "tensorflow/lite/kernels/internal/reference/softmax.h"
#include "tensorflow/lite/micro/kernels/softmax.h"
#include "tensorflow/lite/micro/micro_context.h"

static std::array<uint32_t,64> registers;
static uint32_t acceleration_mask=32;
static unsigned starts,device_mode;
extern "C" void dsa_nn_set_accelerators(uint32_t mask) {acceleration_mask=mask;}
extern "C" uint32_t dsa_nn_get_accelerators() {return acceleration_mask;}
extern "C" const char* TfLiteTypeGetName(TfLiteType) {return "test";}

static void reset_device() {
  registers.fill(0);starts=0;device_mode=0;
  registers[NPU_REG_ID/4]=0x4e505531;
  registers[NPU_REG_CONFIG_ABI/4]=2;
  registers[NPU_REG_VECTOR_CAPS/4]=DSA_SOFTMAX_CAPABILITY;
  registers[NPU_REG_SOFTMAX_MAX_DEPTH/4]=16;
  acceleration_mask=32;
}

uint32_t dsa_mmio_read(uint32_t address) {
  assert(address>=DSA_MMIO_BASE && address<DSA_MMIO_BASE+256 && !(address&3));
  return registers[(address-DSA_MMIO_BASE)/4];
}

void dsa_mmio_write(uint32_t address,uint32_t value) {
  assert(address>=DSA_MMIO_BASE && address<DSA_MMIO_BASE+256 && !(address&3));
  const uint32_t offset=address-DSA_MMIO_BASE;
  if (offset==NPU_REG_STATUS) registers[offset/4]&=~value;
  else registers[offset/4]=value;
  if (offset==NPU_REG_CTRL && (value&NPU_CTRL_START)) {
    assert(value==(NPU_CTRL_START|NPU_CTRL_IRQ_ENABLE|NPU_CTRL_VECTOR_ENGINE));
    assert(registers[NPU_REG_VECTOR_OP/4]==10);
    assert(registers[NPU_REG_VECTOR_LENGTH/4]>0 && registers[NPU_REG_VECTOR_LENGTH/4]<=16);
    ++starts;
    if (device_mode==2) {registers[NPU_REG_STATUS/4]=2;return;}
    registers[NPU_REG_STATUS/4]=NPU_STATUS_DONE;
    if (device_mode==1) registers[NPU_REG_STATUS/4]|=2u<<NPU_STATUS_ERR_SHIFT;
    else {
      auto* output=reinterpret_cast<int8_t*>(static_cast<uintptr_t>(registers[NPU_REG_DST_BASE/4]));
      std::fill(output,output+registers[NPU_REG_VECTOR_LENGTH/4],42);
    }
  }
}

class TestContext final: public tflite::MicroContext {
 public:
  struct Shape {int size,data[2];} shape{2,{3,10}};
  struct Indices {int size,data[1];} inputs{1,{0}},outputs{1,{1}};
  uint8_t* memory;
  size_t used=0x3000;
  unsigned temp_allocations=0,temp_releases=0;
  unsigned eval_requests=0;
  TfLiteTensor tensors[2]{};
  TfLiteEvalTensor eval[2]{};
  TfLiteContext context{};
  TfLiteNode node{};
  TfLiteSoftmaxParams options{};
  TFLMRegistration registration{};

  explicit TestContext(int depth=10,int rows=3) {
    memory=static_cast<uint8_t*>(mmap(nullptr,65536,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0));
    assert(memory!=MAP_FAILED && reinterpret_cast<uintptr_t>(memory)+65536<UINT32_MAX);
    shape.data[0]=rows;shape.data[1]=depth;
    for (int i=0;i<2;i++) {
      tensors[i].type=eval[i].type=kTfLiteInt8;
      tensors[i].dims=eval[i].dims=reinterpret_cast<TfLiteIntArray*>(&shape);
      tensors[i].data.int8=eval[i].data.int8=reinterpret_cast<int8_t*>(memory+0x1000*(i+1));
    }
    tensors[0].params.scale=0.125f;tensors[0].params.zero_point=13;
    tensors[1].params.scale=1.0f/256;tensors[1].params.zero_point=-128;
    context.impl_=this;context.AllocatePersistentBuffer=tflite::MicroContextAllocatePersistentBuffer;
    context.GetEvalTensor=tflite::MicroContextGetEvalTensor;
    context.GetTensor=tflite::MicroContextGetTensor;
    node.inputs=reinterpret_cast<TfLiteIntArray*>(&inputs);
    node.outputs=reinterpret_cast<TfLiteIntArray*>(&outputs);
    options.beta=1;node.builtin_data=&options;
    registration=tflite::Register_SOFTMAX();
    node.user_data=registration.init(&context,nullptr,0);
    assert(node.user_data);
    for(int i=0;i<rows*depth;i++) eval[0].data.int8[i]=static_cast<int8_t>(i*17-100);
  }
  ~TestContext() override {munmap(memory,65536);}
  void* AllocatePersistentBuffer(size_t bytes) override {
    used=(used+15)&~size_t(15);assert(used+bytes<=65536);
    void* result=memory+used;used+=bytes;return result;
  }
  TfLiteStatus RequestScratchBufferInArena(size_t,int*) override {return kTfLiteError;}
  void* GetScratchBuffer(int) override {std::abort();}
  TfLiteTensor* AllocateTempTfLiteTensor(int index) override {
    assert(index==0 || index==1);++temp_allocations;return &tensors[index];
  }
  void DeallocateTempTfLiteTensor(TfLiteTensor*) override {++temp_releases;}
  uint8_t* AllocateTempBuffer(size_t,size_t) override {std::abort();}
  void DeallocateTempBuffer(uint8_t*) override {std::abort();}
  TfLiteEvalTensor* GetEvalTensor(int index) override {assert(index==0 || index==1);++eval_requests;return &eval[index];}
  TfLiteStatus set_external_context(void*) override {return kTfLiteError;}
  void* external_context() override {return nullptr;}
  tflite::MicroGraph& graph() override {std::abort();}
  void prepare() {assert(registration.prepare(&context,&node)==kTfLiteOk);assert(temp_allocations==temp_releases);}
  TfLiteStatus invoke() {return registration.invoke(&context,&node);}
  std::vector<int8_t> expected() {
    std::vector<int8_t> result(shape.data[0]*shape.data[1]);
    const tflite::RuntimeShape dimensions(shape.size,shape.data);
    tflite::reference_ops::Softmax(*static_cast<tflite::SoftmaxParams*>(node.user_data),
        dimensions,eval[0].data.int8,dimensions,result.data());
    return result;
  }
  void compare(const std::vector<int8_t>& result) {
    assert(std::equal(result.begin(),result.end(),eval[1].data.int8));
  }
};

static void test_driver() {
  reset_device();TestContext storage;
  auto* table=reinterpret_cast<int32_t*>(storage.memory+0x4000);
  auto* input=reinterpret_cast<int8_t*>(storage.memory+0x1000);
  auto* output=reinterpret_cast<int8_t*>(storage.memory+0x2000);
  dsa_softmax_plan_t plan{};
  assert(dsa_softmax_prepare(nullptr,10,table)==DSA_ERR_NULL_PTR);
  assert(dsa_softmax_prepare(&plan,0,table)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_prepare(&plan,10,nullptr)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_prepare(&plan,10,reinterpret_cast<int32_t*>(storage.memory+1))==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_prepare(&plan,17,table)==DSA_ERR_UNSUPPORTED && !plan.valid);
  registers[NPU_REG_VECTOR_CAPS/4]=0;
  assert(dsa_softmax_prepare(&plan,10,table)==DSA_ERR_UNSUPPORTED && !plan.valid);
  registers[NPU_REG_VECTOR_CAPS/4]=DSA_SOFTMAX_CAPABILITY;
  registers[NPU_REG_CONFIG_ABI/4]=1;
  assert(dsa_softmax_prepare(&plan,10,table)==DSA_ERR_UNSUPPORTED);
  registers[NPU_REG_CONFIG_ABI/4]=2;
  registers[NPU_REG_ID/4]=0;
  assert(dsa_softmax_prepare(&plan,10,table)==DSA_ERR_UNSUPPORTED);
  registers[NPU_REG_ID/4]=0x4e505531;
  assert(dsa_softmax_prepare(&plan,10,table)==DSA_SUCCESS);
  assert(dsa_softmax_execute(nullptr,input,output)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_execute(&plan,nullptr,output)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_execute(&plan,input,input)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_execute(&plan,input,input+9)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_execute(&plan,input,reinterpret_cast<int8_t*>(table)+1020)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_execute(&plan,reinterpret_cast<int8_t*>(UINTPTR_MAX-5),output)==DSA_ERR_INVALID_DIM);
  assert(dsa_softmax_span(reinterpret_cast<int8_t*>(UINT32_MAX-10u),10));
  assert(!dsa_softmax_span(reinterpret_cast<int8_t*>(UINT32_MAX-9u),10));
  assert(!dsa_softmax_span(reinterpret_cast<int8_t*>(UINTPTR_MAX),1));
  assert(!dsa_softmax_span(input,0));
  registers[NPU_REG_STATUS/4]=2;
  assert(dsa_softmax_execute(&plan,input,output)==DSA_ERR_BUSY && starts==0);
  registers[NPU_REG_STATUS/4]=0;
  assert(dsa_softmax_execute(&plan,input,output)==DSA_SUCCESS && starts==1);
  assert(registers[NPU_REG_LHS_BASE/4]==reinterpret_cast<uintptr_t>(input));
  assert(registers[NPU_REG_RHS_BASE/4]==reinterpret_cast<uintptr_t>(table));
  assert(registers[NPU_REG_DST_BASE/4]==reinterpret_cast<uintptr_t>(output));
  assert(registers[NPU_REG_VECTOR_LENGTH/4]==10 && output[9]==42);
  device_mode=1;assert(dsa_softmax_execute(&plan,input,output)==2);
  registers[NPU_REG_STATUS/4]=0;device_mode=2;
  assert(dsa_softmax_execute(&plan,input,output)==DSA_ERR_TIMEOUT);
}

int main() {
  test_driver();
  reset_device();{
    TestContext test;test.prepare();const auto expected=test.expected();
    const unsigned prepared_requests=test.eval_requests;
    assert(test.invoke()==kTfLiteOk);
#if DSA_NN_VECTOR_ENABLE
    assert(test.eval_requests==prepared_requests);
    assert(starts==3);test.compare(std::vector<int8_t>(30,42));
    acceleration_mask=0;starts=0;assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
    acceleration_mask=32;device_mode=1;
    assert(test.invoke()==kTfLiteError && starts==1);
#else
    assert(starts==0);test.compare(expected);
#endif
  }
  reset_device();{
    TestContext test;test.prepare();
    std::copy_n(test.eval[0].data.int8,30,reinterpret_cast<int8_t*>(test.memory+0x5000));
    test.eval[0].data.int8=reinterpret_cast<int8_t*>(test.memory+0x5000);
    test.eval[1].data.int8=reinterpret_cast<int8_t*>(test.memory+0x6000);
    const auto expected=test.expected();
    assert(test.invoke()==kTfLiteOk);
#if DSA_NN_VECTOR_ENABLE
    assert(starts==3);test.compare(std::vector<int8_t>(30,42));
    assert(registers[NPU_REG_LHS_BASE/4]==reinterpret_cast<uintptr_t>(test.eval[0].data.int8+20));
    assert(registers[NPU_REG_DST_BASE/4]==reinterpret_cast<uintptr_t>(test.eval[1].data.int8+20));
    acceleration_mask=0;assert(test.invoke()==kTfLiteOk);test.compare(expected);
#else
    test.compare(expected);
#endif
  }
  reset_device();{
    TestContext test(17,2);test.prepare();const auto expected=test.expected();
    assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
  }
  reset_device();{
    registers[NPU_REG_VECTOR_CAPS/4]=0;
    TestContext test;test.prepare();const auto expected=test.expected();
    assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
  }
  reset_device();{
    TestContext test;test.prepare();const auto expected=test.expected();
    test.eval[1].data.int8=test.eval[0].data.int8;
    assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
  }
  reset_device();{
    acceleration_mask=0;
    TestContext test;test.prepare();const auto expected=test.expected();
    assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
  }
  std::cout<<"SOFTMAX_TFLM_DRIVER_PASS hardware_compiled="<<DSA_NN_VECTOR_ENABLE<<'\n';
}
