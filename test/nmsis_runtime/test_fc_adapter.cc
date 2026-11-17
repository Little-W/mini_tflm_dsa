/* SPDX-License-Identifier: Apache-2.0 */
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../../drivers/tflm/tflm/tflite-micro/tensorflow/lite/micro/kernels/nmsis_nn/fully_connected.cc"

static unsigned checks, calls, sum_calls, size_queries;
static int requested_bytes;
static riscv_nmsis_nn_status selected_status, sum_status;
static tflite::OpDataFullyConnected reference_data;
static nmsis_nn_fc_params observed_params;
static nmsis_nn_dims observed_input, observed_filter, observed_output;
static bool observed_per_channel;
static int32_t observed_mult[5], observed_shift[5];
static const void *observed_context;
static const int32_t *observed_bias;
static TfLiteTensor tensors[4];
static TfLiteEvalTensor eval_tensors[4];

#define CHECK(x) do { ++checks; assert(x); } while (0)

extern "C" void DebugLog(const char*, va_list) {}

namespace tflite {
const int kFullyConnectedInputTensor=0, kFullyConnectedWeightsTensor=1;
const int kFullyConnectedBiasTensor=2, kFullyConnectedOutputTensor=0;
TfLiteStatus CalculateOpDataFullyConnected(
    TfLiteContext*, TfLiteFusedActivation, TfLiteType, const TfLiteTensor*,
    const TfLiteTensor*, const TfLiteTensor*, TfLiteTensor*, OpDataFullyConnected* data) {
  *data=reference_data;
  return kTfLiteOk;
}
}  // namespace tflite

extern "C" int32_t riscv_fully_connected_s8_get_buffer_size(const nmsis_nn_dims* filter) {
  ++size_queries;
  CHECK(filter->n==4 && filter->c==5);
  return requested_bytes;
}
extern "C" int32_t riscv_fully_connected_s16_get_buffer_size(const nmsis_nn_dims*) {
  std::abort();
}
extern "C" riscv_nmsis_nn_status riscv_vector_sum_s8(
    int32_t* sums, int32_t columns, int32_t rows, const int8_t*,
    int32_t input_offset, int32_t filter_offset, const int32_t* bias) {
  ++sum_calls;
  CHECK(columns==4 && rows==5 && input_offset==7 && filter_offset==-2);
  CHECK(bias==eval_tensors[2].data.i32 || bias==nullptr);
  for (int i=0;i<5;++i) sums[i]=100+i;
  return sum_status;
}
extern "C" riscv_nmsis_nn_status riscv_fully_connected_wrapper_s8_acc(
    const nmsis_nn_context* context, const nmsis_nn_fc_params* params,
    const nmsis_nn_quant_params* quant, const nmsis_nn_dims* input,
    const int8_t* input_data, const nmsis_nn_dims* filter,
    const int8_t* filter_data, const nmsis_nn_dims*, const int32_t* bias,
    const nmsis_nn_dims* output, int8_t* output_data) {
  ++calls;
  CHECK(input_data==eval_tensors[0].data.int8);
  CHECK(filter_data==eval_tensors[1].data.int8);
  CHECK(output_data==eval_tensors[3].data.int8);
  observed_params=*params; observed_input=*input;
  observed_filter=*filter; observed_output=*output;
  observed_context=context->buf; observed_bias=bias;
  observed_per_channel=quant->is_per_channel;
  for (int i=0;i<5;++i) {
    observed_mult[i]=quant->multiplier[quant->is_per_channel?i:0];
    observed_shift[i]=quant->shift[quant->is_per_channel?i:0];
  }
  return selected_status;
}

class TestContext final : public tflite::MicroContext {
 public:
  int scratch_requests=0, persistent_requests=0, released_tensors=0;
  int32_t scratch[5]={}, persistent[5]={};
  bool allocation_fails=false;
  void* AllocatePersistentBuffer(size_t bytes) override {
    CHECK(bytes==sizeof(persistent)); ++persistent_requests;
    return allocation_fails?nullptr:persistent;
  }
  TfLiteStatus RequestScratchBufferInArena(size_t bytes, int* index) override {
    CHECK(bytes==sizeof(scratch)); ++scratch_requests; *index=0;
    return kTfLiteOk;
  }
  void* GetScratchBuffer(int index) override { CHECK(index==0); return scratch; }
  TfLiteTensor* AllocateTempTfLiteTensor(int index) override {
    CHECK(index>=0 && index<4); return &tensors[index];
  }
  void DeallocateTempTfLiteTensor(TfLiteTensor*) override { ++released_tensors; }
  uint8_t* AllocateTempBuffer(size_t,size_t) override { std::abort(); }
  void DeallocateTempBuffer(uint8_t*) override { std::abort(); }
  TfLiteEvalTensor* GetEvalTensor(int index) override {
    CHECK(index>=0 && index<4); return &eval_tensors[index];
  }
  TfLiteStatus set_external_context(void*) override { std::abort(); }
  void* external_context() override { std::abort(); }
  tflite::MicroGraph& graph() override { std::abort(); }
 private:
  TF_LITE_REMOVE_VIRTUAL_DELETE
};

static void report_error(TfLiteContext*,const char*,...) {}

int main() {
  int8_t input[24]={}, filter[20]={}, output[30]={};
  int32_t bias[5]={}, multipliers[5]={101,102,103,104,105};
  int32_t shifts[5]={-1,-2,-3,-4,-5};
  int filter_shape[]={2,5,4}, bias_shape[]={1,5};
  int inputs[]={3,0,1,2}, outputs[]={1,3};
  int input_shapes[3][5]={{2,6,4,0,0},{3,2,3,4,0},{4,2,1,3,4}};
  int output_shapes[3][5]={{2,6,5,0,0},{3,2,3,5,0},{4,2,1,3,5}};
  TfLiteFullyConnectedParams params={};
  TfLiteNode node={};
  node.inputs=reinterpret_cast<TfLiteIntArray*>(inputs);
  node.outputs=reinterpret_cast<TfLiteIntArray*>(outputs);
  node.builtin_data=&params;
  reference_data.input_zero_point=-7; reference_data.filter_zero_point=2;
  reference_data.output_zero_point=-3;
  reference_data.output_activation_min=-101; reference_data.output_activation_max=109;
  reference_data.output_multiplier=123456; reference_data.output_shift=-6;
  reference_data.per_channel_output_multiplier=multipliers;
  reference_data.per_channel_output_shift=shifts;
  eval_tensors[0].data.int8=input; eval_tensors[1].data.int8=filter;
  eval_tensors[2].data.i32=bias; eval_tensors[3].data.int8=output;
  for (int rank=0;rank<3;++rank) for (int per_channel=0;per_channel<2;++per_channel)
    for (int has_bias=0;has_bias<2;++has_bias) for (int buffer=0;buffer<2;++buffer) {
      TestContext micro;
      TfLiteContext context={};
      context.impl_=&micro; context.ReportError=report_error;
      context.AllocatePersistentBuffer=tflite::MicroContextAllocatePersistentBuffer;
      context.RequestScratchBufferInArena=tflite::MicroContextRequestScratchBufferInArena;
      context.GetScratchBuffer=tflite::MicroContextGetScratchBuffer;
      context.GetEvalTensor=tflite::MicroContextGetEvalTensor;
      eval_tensors[0].dims=reinterpret_cast<TfLiteIntArray*>(input_shapes[rank]);
      eval_tensors[1].dims=reinterpret_cast<TfLiteIntArray*>(filter_shape);
      eval_tensors[2].dims=reinterpret_cast<TfLiteIntArray*>(bias_shape);
      eval_tensors[3].dims=reinterpret_cast<TfLiteIntArray*>(output_shapes[rank]);
      for (int i=0;i<4;++i) {
        eval_tensors[i].type=i==2?kTfLiteInt32:kTfLiteInt8;
        tensors[i].dims=eval_tensors[i].dims;
        tensors[i].data=eval_tensors[i].data;
        tensors[i].type=eval_tensors[i].type;
      }
      inputs[3]=has_bias?2:kTfLiteOptionalTensor;
      tflite::OpData data;
      std::memset(&data,0x5a,sizeof(data));
#if DSA_NN_PREPARED_ENABLE && DSA_NN_FC_ENABLE
      data.prepared = nullptr;
#endif
      node.user_data=&data;
      reference_data.is_per_channel=per_channel;
      requested_bytes=buffer?sizeof(micro.scratch):0;
      size_queries=calls=sum_calls=0;
      sum_status=RISCV_NMSIS_NN_SUCCESS;
      CHECK(tflite::Prepare(&context,&node)==kTfLiteOk);
      CHECK(size_queries==1 && calls==0);
      CHECK(data.batches==6 && data.accum_depth==4 && data.output_depth==5);
      CHECK(micro.released_tensors==(has_bias?4:3));
#ifdef KERNELS_OPTIMIZED_FOR_SPEED
      CHECK(data.buffer_idx==-1 && data.kernel_sums==(buffer?micro.persistent:nullptr));
      CHECK(micro.persistent_requests==buffer && micro.scratch_requests==0);
      CHECK(sum_calls==static_cast<unsigned>(buffer));
#else
      CHECK(data.buffer_idx==(buffer?0:-1) && data.kernel_sums==nullptr);
      CHECK(micro.persistent_requests==0 && micro.scratch_requests==buffer && sum_calls==0);
#endif
      for (int error=0;error<2;++error) {
        calls=sum_calls=0;
        selected_status=error?RISCV_NMSIS_NN_NO_IMPL_ERROR:RISCV_NMSIS_NN_SUCCESS;
        CHECK(tflite::EvalInt8(&context,&node)==(error?kTfLiteError:kTfLiteOk));
        CHECK(calls==1);
        CHECK(observed_input.n==6 && observed_input.h==1 && observed_input.w==1 && observed_input.c==4);
        CHECK(observed_filter.n==4 && observed_filter.c==5);
        CHECK(observed_output.n==6 && observed_output.h==1 && observed_output.w==1 && observed_output.c==5);
        CHECK(observed_params.input_offset==7 && observed_params.filter_offset==-2 && observed_params.output_offset==-3);
        CHECK(observed_params.activation.min==-101 && observed_params.activation.max==109);
        CHECK(observed_bias==(has_bias?bias:nullptr) && observed_per_channel==static_cast<bool>(per_channel));
        for (int i=0;i<5;++i) {
          CHECK(observed_mult[i]==(per_channel?multipliers[i]:reference_data.output_multiplier));
          CHECK(observed_shift[i]==(per_channel?shifts[i]:reference_data.output_shift));
        }
#ifdef KERNELS_OPTIMIZED_FOR_SPEED
        CHECK(sum_calls==0 && observed_context==(buffer?micro.persistent:nullptr));
#else
        CHECK(sum_calls==static_cast<unsigned>(buffer) && observed_context==(buffer?micro.scratch:nullptr));
#endif
      }
    }
  std::printf("TFLM_FC_ADAPTER_PASS ranks=2,3,4 checks=%u\n",checks);
  return 0;
}
