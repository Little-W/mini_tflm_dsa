/* SPDX-License-Identifier: Apache-2.0 */
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../../drivers/tflm/tflm/tflite-micro/tensorflow/lite/micro/kernels/nmsis_nn/depthwise_conv.cc"

static unsigned checks, calls, size_queries;
static int requested_bytes, output_channels, batches;
static riscv_nmsis_nn_status selected_status;
static TfLiteTensor tensors[4];
static TfLiteEvalTensor eval_tensors[4];
static const void* expected_scratch;
static const int32_t* expected_bias;
#define CHECK(x) do { ++checks; assert(x); } while (0)

extern "C" void DebugLog(const char*, va_list) {}

namespace tflite {
const int kDepthwiseConvInputTensor=0, kDepthwiseConvWeightsTensor=1;
const int kDepthwiseConvBiasTensor=2, kDepthwiseConvOutputTensor=0;
const int kDepthwiseConvQuantizedDimension=3;
TfLiteStatus CalculateOpDataDepthwiseConv(
    TfLiteContext*, TfLiteNode*, const TfLiteDepthwiseConvParams&, int width,
    int height, int filter_width, int filter_height, int out_width,
    int out_height, const TfLiteType type, OpDataConv* data) {
  CHECK(width==7 && height==6 && filter_width==3 && filter_height==3);
  CHECK(out_width==4 && out_height==3 && type==kTfLiteInt8);
  data->input_zero_point=-19; data->output_zero_point=-7;
  data->padding.height=1; data->padding.width=2;
  data->output_activation_min=-101; data->output_activation_max=109;
  for (int i=0;i<output_channels;++i) {
    data->per_channel_output_multiplier[i]=101+i;
    data->per_channel_output_shift[i]=-1-i;
  }
  return kTfLiteOk;
}
}  // namespace tflite

extern "C" int32_t riscv_depthwise_conv_wrapper_s8_get_buffer_size_acc(
    const nmsis_nn_dw_conv_params* p, const nmsis_nn_dims* in,
    const nmsis_nn_dims* f, const nmsis_nn_dims* out) {
  ++size_queries;
  CHECK(in->n==batches && in->c==1 && in->h==6 && in->w==7);
  CHECK(f->n==1 && f->h==3 && f->w==3 && f->c==output_channels);
  CHECK(out->n==batches && out->h==3 && out->w==4 && out->c==output_channels);
  CHECK(p->ch_mult==output_channels && p->input_offset==19 && p->output_offset==-7);
  CHECK(p->stride.h==2 && p->stride.w==1 && p->dilation.h==1 && p->dilation.w==2);
  CHECK(p->padding.h==1 && p->padding.w==2);
  return requested_bytes;
}
extern "C" int32_t riscv_depthwise_conv_wrapper_s4_get_buffer_size(
    const nmsis_nn_dw_conv_params*, const nmsis_nn_dims*, const nmsis_nn_dims*, const nmsis_nn_dims*) {
  std::abort();
}
extern "C" riscv_nmsis_nn_status riscv_depthwise_conv_wrapper_s8_acc(
    const nmsis_nn_context* ctx, const nmsis_nn_dw_conv_params* p,
    const nmsis_nn_per_channel_quant_params* q, const nmsis_nn_dims* in,
    const int8_t* input, const nmsis_nn_dims* f, const int8_t* filter,
    const nmsis_nn_dims* bd, const int32_t* bias, const nmsis_nn_dims* out, int8_t* output) {
  ++calls;
  CHECK(ctx->size==requested_bytes && ctx->buf==expected_scratch);
  CHECK(in->n==batches && in->c==1 && in->h==6 && in->w==7);
  CHECK(f->n==1 && f->h==3 && f->w==3 && f->c==output_channels);
  CHECK(bd->c==output_channels && out->n==batches && out->c==output_channels);
  CHECK(p->ch_mult==output_channels && p->input_offset==19 && p->output_offset==-7);
  CHECK(p->stride.h==2 && p->stride.w==1 && p->dilation.h==1 && p->dilation.w==2);
  CHECK(p->padding.h==1 && p->padding.w==2 && p->activation.min==-101 && p->activation.max==109);
  CHECK(input==eval_tensors[0].data.int8 && filter==eval_tensors[1].data.int8);
  CHECK(output==eval_tensors[3].data.int8 && bias==expected_bias);
  for (int i=0;i<output_channels;++i) {
    CHECK(q->multiplier[i]==101+i && q->shift[i]==-1-i);
  }
  return selected_status;
}

class TestContext final : public tflite::MicroContext {
 public:
  int scratch_requests=0, persistent_requests=0, released_tensors=0;
  int32_t parameters[2][16]={};
  uint8_t scratch[784]={};
  void* AllocatePersistentBuffer(size_t bytes) override {
    CHECK(bytes==static_cast<size_t>(output_channels*4) && persistent_requests<2);
    return parameters[persistent_requests++];
  }
  TfLiteStatus RequestScratchBufferInArena(size_t bytes, int* index) override {
    CHECK(bytes==static_cast<size_t>(requested_bytes) && bytes<=sizeof(scratch));
    ++scratch_requests; *index=0; return kTfLiteOk;
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
  int8_t input[84]={}, filter[144]={}, output[384]={};
  int32_t bias[16]={};
  int input_shape[]={4,2,6,7,1}, filter_shape[]={4,1,3,3,8};
  int output_shape[]={4,2,3,4,8}, bias_shape[]={1,8};
  int inputs[]={3,0,1,2}, outputs[]={1,3};
  struct {int size; float data[16];} scales={};
  struct {int size; int data[16];} zeros={};
  TfLiteAffineQuantization affine={};
  affine.scale=reinterpret_cast<TfLiteFloatArray*>(&scales);
  affine.zero_point=reinterpret_cast<TfLiteIntArray*>(&zeros);
  affine.quantized_dimension=3;
  TfLiteDepthwiseConvParams params={};
  params.stride_height=2; params.stride_width=1;
  params.dilation_height_factor=1; params.dilation_width_factor=2;
  TfLiteNode node={};
  node.inputs=reinterpret_cast<TfLiteIntArray*>(inputs);
  node.outputs=reinterpret_cast<TfLiteIntArray*>(outputs); node.builtin_data=&params;
  eval_tensors[0].data.int8=input; eval_tensors[1].data.int8=filter;
  eval_tensors[2].data.i32=bias; eval_tensors[3].data.int8=output;
  eval_tensors[0].dims=reinterpret_cast<TfLiteIntArray*>(input_shape);
  eval_tensors[1].dims=reinterpret_cast<TfLiteIntArray*>(filter_shape);
  eval_tensors[2].dims=reinterpret_cast<TfLiteIntArray*>(bias_shape);
  eval_tensors[3].dims=reinterpret_cast<TfLiteIntArray*>(output_shape);
  const int channels[]={2,3,8,16};
  for (int channel:channels) for (batches=1;batches<=2;++batches)
    for (int per_channel=0;per_channel<2;++per_channel)
      for (int has_bias=0;has_bias<2;++has_bias) for (int buffer=0;buffer<2;++buffer) {
        output_channels=channel; params.depth_multiplier=channel;
        filter_shape[4]=output_shape[4]=bias_shape[1]=channel;
        input_shape[1]=output_shape[1]=batches; inputs[0]=has_bias?3:2;
        scales.size=zeros.size=per_channel?channel:1;
        for (int i=0;i<scales.size;++i) {scales.data[i]=0.5f; zeros.data[i]=0;}
        for (int i=0;i<4;++i) {
          eval_tensors[i].type=i==2?kTfLiteInt32:kTfLiteInt8;
          tensors[i].type=eval_tensors[i].type;
          tensors[i].data=eval_tensors[i].data; tensors[i].dims=eval_tensors[i].dims;
        }
        tensors[0].params.zero_point=-19; tensors[3].params.zero_point=-7;
        tensors[1].quantization.type=kTfLiteAffineQuantization;
        tensors[1].quantization.params=&affine;
        TestContext micro;
        TfLiteContext context={}; context.impl_=&micro; context.ReportError=report_error;
        context.AllocatePersistentBuffer=tflite::MicroContextAllocatePersistentBuffer;
        context.RequestScratchBufferInArena=tflite::MicroContextRequestScratchBufferInArena;
        context.GetScratchBuffer=tflite::MicroContextGetScratchBuffer;
        context.GetEvalTensor=tflite::MicroContextGetEvalTensor;
        tflite::OpData data; std::memset(&data,0x5a,sizeof(data)); node.user_data=&data;
        requested_bytes=buffer?9*channel:0;
        expected_scratch=buffer?micro.scratch:nullptr;
        expected_bias=has_bias?bias:nullptr;
        size_queries=calls=0;
        CHECK(tflite::Prepare(&context,&node)==kTfLiteOk);
        CHECK(size_queries==1 && calls==0 && micro.persistent_requests==2);
        CHECK(micro.scratch_requests==buffer && micro.released_tensors==3);
        CHECK(data.buffer_size==requested_bytes && data.buffer_idx==(buffer?0:-1));
        for (int failure=0;failure<2;++failure) {
          calls=0; selected_status=failure?RISCV_NMSIS_NN_NO_IMPL_ERROR:RISCV_NMSIS_NN_SUCCESS;
          CHECK(tflite::EvalInt8(&context,&node)==(failure?kTfLiteError:kTfLiteOk));
          CHECK(calls==1);
        }
      }
  std::printf("TFLM_DW_ADAPTER_PASS channels=2,3,8,16 batches=1,2 checks=%u\n",checks);
  return 0;
}
