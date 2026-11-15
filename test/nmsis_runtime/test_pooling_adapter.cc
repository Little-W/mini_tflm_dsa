/* SPDX-License-Identifier: Apache-2.0 */
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "../../drivers/tflm/tflm/tflite-micro/tensorflow/lite/micro/kernels/nmsis_nn/pooling.cc"

static riscv_nmsis_nn_status selected_status;
static int calls, observed_input_batches, observed_output_batches;
static TfLiteEvalTensor tensors[2];

#define POOL_RESULT(name, type) \
extern "C" riscv_nmsis_nn_status name(const nmsis_nn_context*, \
    const nmsis_nn_pool_params*, const nmsis_nn_dims* input, const type*, \
    const nmsis_nn_dims*, const nmsis_nn_dims* output, type*) { \
    ++calls; observed_input_batches=input->n; observed_output_batches=output->n; \
    return selected_status; \
}
POOL_RESULT(riscv_avgpool_s8, int8_t)
POOL_RESULT(riscv_avgpool_s16, int16_t)
POOL_RESULT(riscv_max_pool_s8, int8_t)
POOL_RESULT(riscv_max_pool_s16, int16_t)

static TfLiteEvalTensor* get_tensor(const TfLiteContext*, int index)
{
    assert(index >= 0 && index < 2);
    return &tensors[index];
}

static void report_error(TfLiteContext*, const char*, ...) {}

int main()
{
    int input_dims[] = {4, 2, 4, 4, 3}, output_dims[] = {4, 2, 2, 2, 3};
    int input_indices[] = {1,0}, output_indices[] = {1,1};
    int16_t input[96] = {}, output[24] = {};
    tensors[0].dims = reinterpret_cast<TfLiteIntArray*>(input_dims);
    tensors[1].dims = reinterpret_cast<TfLiteIntArray*>(output_dims);
    tensors[0].data.i16 = input; tensors[1].data.i16 = output;
    TfLiteContext context = {};
    context.GetEvalTensor = get_tensor;
    context.ReportError = report_error;
    TfLitePoolParams params = {};
    params.filter_height = params.filter_width = 2;
    params.stride_height = params.stride_width = 2;
    tflite::OpData data = {};
    data.buffer_idx = -1;
    data.reference_op_data.activation_min = -128;
    data.reference_op_data.activation_max = 127;
    TfLiteNode node = {};
    node.inputs = reinterpret_cast<TfLiteIntArray*>(input_indices);
    node.outputs = reinterpret_cast<TfLiteIntArray*>(output_indices);
    node.builtin_data = &params;
    node.user_data = &data;
    int checks = 0;
    for (int type = 0; type < 2; ++type) {
        tensors[0].type = tensors[1].type = type ? kTfLiteInt16 : kTfLiteInt8;
        for (int kind = 0; kind < 2; ++kind) for (int error = 0; error < 2; ++error) {
            selected_status = error ? RISCV_NMSIS_NN_NO_IMPL_ERROR : RISCV_NMSIS_NN_SUCCESS;
            calls = 0;
            TfLiteStatus result;
            if (kind) result = type ? tflite::MaxEvalInt16(&context,&node) : tflite::MaxEvalInt8(&context,&node);
            else result = type ? tflite::AverageEvalInt16(&context,&node) : tflite::AverageEvalInt8(&context,&node);
            assert(result == (error ? kTfLiteError : kTfLiteOk)); ++checks;
            assert(calls == 1); ++checks;
            assert(observed_input_batches == 2 && observed_output_batches == 2); ++checks;
        }
    }
    std::printf("TFLM_POOLING_ADAPTER_PASS checks=%d\n",checks);
    return 0;
}
