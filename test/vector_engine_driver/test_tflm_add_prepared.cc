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
extern "C" {
#include "dsa_accel.h"
}
#include "riscv_nn_prepared.h"
#include "tensorflow/lite/micro/kernels/add.h"
#include "tensorflow/lite/micro/micro_context.h"

namespace tflite {
TfLiteStatus EvalAddQuantized(TfLiteContext*, TfLiteNode*, TfLiteAddParams*,
    const OpDataAdd*, const TfLiteEvalTensor*, const TfLiteEvalTensor*, TfLiteEvalTensor*);
}

static std::array<uint32_t,128> registers;
static uint32_t acceleration_mask;
static unsigned starts,device_mode,capability_reads;
extern "C" void dsa_nn_set_accelerators(uint32_t mask) {acceleration_mask=mask;}
extern "C" uint32_t dsa_nn_get_accelerators() {return acceleration_mask;}

static void reset_device() {
  registers.fill(0);starts=device_mode=capability_reads=0;
  registers[NPU_REG_ID/4]=0x4e505531;
  registers[NPU_REG_CONFIG_ABI/4]=2;
  registers[NPU_REG_VECTOR_CAPS/4]=(1u<<24)|(16u<<8)|DSA_VECTOR_CAP_ADD_S8;
  acceleration_mask=DSA_NN_ACCEL_ADD;
}

extern "C" uint32_t dsa_mmio_read(uint32_t address) {
  assert(address>=DSA_MMIO_BASE && address<DSA_MMIO_BASE+512 && !(address&3));
  if (address==DSA_MMIO_BASE+NPU_REG_VECTOR_CAPS) ++capability_reads;
  return registers[(address-DSA_MMIO_BASE)/4];
}

extern "C" void dsa_mmio_write(uint32_t address,uint32_t value) {
  assert(address>=DSA_MMIO_BASE && address<DSA_MMIO_BASE+512 && !(address&3));
  const uint32_t offset=address-DSA_MMIO_BASE;
  if (offset==NPU_REG_STATUS) registers[offset/4]&=~value;
  else registers[offset/4]=value;
  if (offset==NPU_REG_CTRL && (value&NPU_CTRL_START)) {
    assert(value==(NPU_CTRL_START|NPU_CTRL_IRQ_ENABLE|NPU_CTRL_VECTOR_ENGINE));
    assert(registers[NPU_REG_VECTOR_OP/4]==DSA_VECTOR_OP_ADD_S8);
    assert(registers[NPU_REG_VECTOR_LENGTH/4]==30);
    ++starts;
    if (device_mode==2) {registers[NPU_REG_STATUS/4]=2;return;}
    registers[NPU_REG_STATUS/4]=NPU_STATUS_DONE;
    if (device_mode==1) registers[NPU_REG_STATUS/4]|=2u<<NPU_STATUS_ERR_SHIFT;
    else {
      auto* output=reinterpret_cast<int8_t*>(static_cast<uintptr_t>(registers[NPU_REG_DST_BASE/4]));
      std::fill_n(output,registers[NPU_REG_VECTOR_LENGTH/4],42);
    }
  }
}

class TestContext final: public tflite::MicroContext {
 public:
  struct Shape {int size,data[2];} shape{2,{3,10}},scalar_shape{2,{1,1}};
  struct InputIndices {int size,data[2];} inputs{2,{0,1}};
  struct OutputIndices {int size,data[1];} outputs{1,{2}};
  uint8_t* memory;
  size_t used=0x5000;
  unsigned temp_allocations=0,temp_releases=0,eval_requests=0;
  unsigned persistent_requests=0,fail_allocation=0;
  std::vector<void*> allocations;
  TfLiteTensor tensors[3]{};
  TfLiteEvalTensor eval[3]{};
  TfLiteContext context{};
  TfLiteNode node{};
  TfLiteAddParams options{};
  TFLMRegistration registration{};

  explicit TestContext(bool broadcast=false) {
    memory=static_cast<uint8_t*>(mmap(nullptr,65536,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_32BIT,-1,0));
    assert(memory!=MAP_FAILED && reinterpret_cast<uintptr_t>(memory)+65536<UINT32_MAX);
    for (int i=0;i<3;i++) {
      tensors[i].type=eval[i].type=kTfLiteInt8;
      tensors[i].dims=eval[i].dims=reinterpret_cast<TfLiteIntArray*>(&shape);
      tensors[i].data.int8=eval[i].data.int8=reinterpret_cast<int8_t*>(memory+0x1000*(i+1));
      tensors[i].params.scale=0.125f;tensors[i].params.zero_point=0;
      tensors[i].quantization.type=kTfLiteAffineQuantization;
    }
    if (broadcast) tensors[1].dims=eval[1].dims=reinterpret_cast<TfLiteIntArray*>(&scalar_shape);
    context.impl_=this;context.AllocatePersistentBuffer=tflite::MicroContextAllocatePersistentBuffer;
    context.GetEvalTensor=tflite::MicroContextGetEvalTensor;
    context.GetTensor=tflite::MicroContextGetTensor;
    node.inputs=reinterpret_cast<TfLiteIntArray*>(&inputs);
    node.outputs=reinterpret_cast<TfLiteIntArray*>(&outputs);
    options.activation=kTfLiteActNone;node.builtin_data=&options;
    registration=tflite::Register_ADD();
    node.user_data=registration.init(&context,nullptr,0);
    assert(node.user_data);
    for (int i=0;i<30;i++) {
      eval[0].data.int8[i]=static_cast<int8_t>(i*3-80);
      eval[1].data.int8[i]=static_cast<int8_t>(i*2+11);
    }
  }
  ~TestContext() override {munmap(memory,65536);}
  void* AllocatePersistentBuffer(size_t bytes) override {
    ++persistent_requests;if (persistent_requests==fail_allocation) return nullptr;
    used=(used+15)&~size_t(15);assert(used+bytes<=65536);
    void* result=memory+used;used+=bytes;allocations.push_back(result);return result;
  }
  TfLiteStatus RequestScratchBufferInArena(size_t,int*) override {return kTfLiteError;}
  void* GetScratchBuffer(int) override {std::abort();}
  TfLiteTensor* AllocateTempTfLiteTensor(int index) override {
    assert(index>=0 && index<3);++temp_allocations;return &tensors[index];
  }
  void DeallocateTempTfLiteTensor(TfLiteTensor*) override {++temp_releases;}
  uint8_t* AllocateTempBuffer(size_t,size_t) override {std::abort();}
  void DeallocateTempBuffer(uint8_t*) override {std::abort();}
  TfLiteEvalTensor* GetEvalTensor(int index) override {
    assert(index>=0 && index<3);++eval_requests;return &eval[index];
  }
  TfLiteStatus set_external_context(void*) override {return kTfLiteError;}
  void* external_context() override {return nullptr;}
  tflite::MicroGraph& graph() override {std::abort();}
  void prepare() {
    assert(registration.prepare(&context,&node)==kTfLiteOk);
    assert(temp_allocations==temp_releases);
  }
  TfLiteStatus invoke() {return registration.invoke(&context,&node);}
  std::vector<int8_t> expected() {
    std::vector<int8_t> result(30);TfLiteEvalTensor output=eval[2];output.data.int8=result.data();
    assert(tflite::EvalAddQuantized(&context,&node,&options,
        static_cast<const tflite::OpDataAdd*>(node.user_data),&eval[0],&eval[1],&output)==kTfLiteOk);
    return result;
  }
  void compare(const std::vector<int8_t>& result) {
    assert(std::equal(result.begin(),result.end(),eval[2].data.int8));
  }
};

int main() {
  reset_device();{
    TestContext test;test.prepare();
    assert(test.allocations.size()==2 && capability_reads==1);
    auto* configuration=static_cast<dsa_prepared_add_s8_t*>(test.allocations.back());
    assert(configuration->valid==DSA_PREPARED_VALID && configuration->length==30);
    const auto saved=*configuration;
    const size_t arena_used=test.used;const auto allocations=test.allocations;
    test.prepare();
    assert(test.used==arena_used && test.allocations==allocations);
    assert(!std::memcmp(configuration,&saved,sizeof(saved)));
    const unsigned eval_requests=test.eval_requests,persistent_requests=test.persistent_requests;
    const unsigned prepared_capability_reads=capability_reads;
    for (auto& tensor:test.eval) tensor.dims=nullptr;
    assert(test.invoke()==kTfLiteOk && starts==1);test.compare(std::vector<int8_t>(30,42));
    for (auto& tensor:test.eval) tensor.dims=reinterpret_cast<TfLiteIntArray*>(&test.shape);
    acceleration_mask=0;const auto expected=test.expected();
    assert(test.invoke()==kTfLiteOk && starts==1);test.compare(expected);
    assert(test.eval_requests==eval_requests && test.persistent_requests==persistent_requests);
    assert(capability_reads==prepared_capability_reads);
    assert(test.used==arena_used && !std::memcmp(configuration,&saved,sizeof(saved)));
  }
  reset_device();{
    TestContext test;test.prepare();
    std::copy_n(test.eval[0].data.int8,30,reinterpret_cast<int8_t*>(test.memory+0x7000));
    std::copy_n(test.eval[1].data.int8,30,reinterpret_cast<int8_t*>(test.memory+0x8000));
    test.eval[0].data.int8=reinterpret_cast<int8_t*>(test.memory+0x7000);
    test.eval[1].data.int8=reinterpret_cast<int8_t*>(test.memory+0x8000);
    test.eval[2].data.int8=reinterpret_cast<int8_t*>(test.memory+0x9000);
    assert(test.invoke()==kTfLiteOk && starts==1);test.compare(std::vector<int8_t>(30,42));
    assert(registers[NPU_REG_LHS_BASE/4]==reinterpret_cast<uintptr_t>(test.eval[0].data.int8));
    assert(registers[NPU_REG_RHS_BASE/4]==reinterpret_cast<uintptr_t>(test.eval[1].data.int8));
    assert(registers[NPU_REG_DST_BASE/4]==reinterpret_cast<uintptr_t>(test.eval[2].data.int8));
  }
  for (unsigned failure: {0u,1u,2u}) {
    reset_device();TestContext test;test.prepare();std::fill_n(test.eval[2].data.int8,30,7);
    if (!failure) registers[NPU_REG_STATUS/4]=2;
    else device_mode=failure;
    assert(test.invoke()==kTfLiteError && starts==(!failure ? 0u:1u));
    test.compare(std::vector<int8_t>(30,7));
  }
  reset_device();{
    registers[NPU_REG_VECTOR_CAPS/4]=0;
    TestContext test;test.prepare();const auto expected=test.expected();
    const unsigned eval_requests=test.eval_requests;
    assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
    assert(test.eval_requests==eval_requests);
    assert(!static_cast<dsa_prepared_add_s8_t*>(test.allocations.back())->valid);
  }
  reset_device();{
    TestContext test(true);test.prepare();const auto expected=test.expected();
    assert(test.allocations.size()==1);
    const unsigned eval_requests=test.eval_requests;
    assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
    assert(test.eval_requests==eval_requests);
  }
  for (unsigned alias: {0u,1u}) {
    reset_device();TestContext test;test.prepare();const auto expected=test.expected();
    test.eval[2].data.int8=test.eval[alias].data.int8;
    assert(test.invoke()==kTfLiteOk && !starts);test.compare(expected);
  }
  reset_device();{
    TestContext test;test.prepare();test.eval[2].data.int8=test.eval[0].data.int8+1;
    assert(test.invoke()==kTfLiteError && !starts);
  }
  reset_device();{
    TestContext test;test.fail_allocation=2;
    assert(test.registration.prepare(&test.context,&test.node)==kTfLiteError);
    assert(test.temp_allocations==test.temp_releases && !starts);
    test.fail_allocation=0;test.prepare();assert(test.invoke()==kTfLiteOk && starts==1);
  }
  std::cout<<"TFLM_ADD_PREPARED_PASS scenarios=11 elements=30\n";
}
