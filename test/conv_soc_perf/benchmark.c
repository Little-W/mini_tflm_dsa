/* SPDX-License-Identifier: Apache-2.0 */
/* Executed by the production PicoRV32 CPU. No host MMIO replacement, timing
 * wrappers, CPU reference MACs, or tensor initialization occur inside the
 * measured complete NMSIS call. The external SoC runner checks every output
 * again and checks actual NPU START kind/count to reject silent fallbacks.
 */
#include "benchmark.h"
#include "dsa_accel.h"
#include "riscv_nnfunctions.h"
#include <stddef.h>

_Static_assert(sizeof(benchmark_config_t) == 38u * 4u, "config ABI");
_Static_assert(sizeof(benchmark_result_t) == 24u * 4u, "result ABI");

volatile benchmark_result_t benchmark_result;

typedef riscv_nmsis_nn_status (*benchmark_conv_fn)(
    const nmsis_nn_context *, const nmsis_nn_conv_params *,
    const nmsis_nn_per_channel_quant_params *, const nmsis_nn_dims *,
    const int8_t *, const nmsis_nn_dims *, const int8_t *,
    const nmsis_nn_dims *, const int32_t *, const nmsis_nn_dims *, int8_t *);

extern riscv_nmsis_nn_status benchmark_legacy_convolve_wrapper_s8(
    const nmsis_nn_context *, const nmsis_nn_conv_params *,
    const nmsis_nn_per_channel_quant_params *, const nmsis_nn_dims *,
    const int8_t *, const nmsis_nn_dims *, const int8_t *,
    const nmsis_nn_dims *, const int32_t *, const nmsis_nn_dims *, int8_t *);

static inline uint32_t benchmark_cycle(void)
{
    uint32_t value;
    __asm__ volatile("rdcycle %0" : "=r"(value) :: "memory");
    return value;
}

static inline void benchmark_marker(uint32_t value)
{
    *(volatile uint32_t *)(uintptr_t)BENCH_PROGRESS_ADDRESS = value;
    __asm__ volatile("fence rw, rw" ::: "memory");
}

static int benchmark_error(uint32_t code)
{
    benchmark_result.error = code;
    benchmark_result.complete = 1u;
    __asm__ volatile("fence rw, rw" ::: "memory");
    return (int)code;
}

int benchmark_run(void)
{
    const benchmark_config_t *c = (const benchmark_config_t *)(uintptr_t)BENCH_CONFIG_ADDRESS;
    nmsis_nn_context ctx = {0};
    nmsis_nn_conv_params params = {0};
    nmsis_nn_per_channel_quant_params quant = {0};
    nmsis_nn_dims input_dims = {0}, filter_dims = {0}, bias_dims = {0}, output_dims = {0};
    benchmark_conv_fn function;
    uint32_t begin, end, required_caps, hash = 2166136261u;
    int8_t *output;
    const int8_t *golden;
    riscv_nmsis_nn_status status;

    benchmark_result.magic = BENCH_RESULT_MAGIC;
    benchmark_result.version = BENCH_ABI_VERSION;
    benchmark_result.mode = c->mode;
    benchmark_result.compiled_dataflow = DSA_NN_CONV_DATAFLOW_MODE;
    benchmark_result.case_id = c->case_id;
    benchmark_result.first_mismatch = UINT32_MAX;
    benchmark_result.nmsis_status = RISCV_NMSIS_NN_ARG_ERROR;
    if (c->magic != BENCH_CONFIG_MAGIC || c->version != BENCH_ABI_VERSION ||
        c->mode > BENCH_MODE_HW_IS || c->batches != 1u ||
        !c->input_h || !c->input_w || !c->input_c ||
        !c->kernel_h || !c->kernel_w || c->group_c != c->input_c ||
        !c->output_h || !c->output_w || !c->output_c ||
        !c->stride_h || !c->stride_w || !c->dilation_h || !c->dilation_w ||
        !c->input_base || !c->filter_base || !c->bias_base ||
        !c->multiplier_base || !c->shift_base || !c->output_base ||
        !c->scratch_base || !c->golden_base ||
        c->input_bytes != c->input_h * c->input_w * c->input_c ||
        c->filter_bytes != c->kernel_h * c->kernel_w * c->group_c * c->output_c ||
        c->output_bytes != c->output_h * c->output_w * c->output_c ||
        c->scratch_bytes < 32u * ((c->kernel_h * c->kernel_w * c->group_c + 3u) & ~3u))
        return benchmark_error(BENCH_ERROR_CONFIG);
    if ((c->mode == BENCH_MODE_HW_WS && DSA_NN_CONV_DATAFLOW_MODE != 0) ||
        (c->mode == BENCH_MODE_HW_IS && DSA_NN_CONV_DATAFLOW_MODE != 1))
        return benchmark_error(BENCH_ERROR_COMPILED_MODE);

    benchmark_result.conv_caps = dsa_conv_capabilities();
    required_caps = DSA_CONV_CAP_S8 | DSA_CONV_CAP_NARROW_READ;
    if (c->mode == BENCH_MODE_HW_IS) required_caps |= DSA_CONV_CAP_IS;
    if (c->mode != BENCH_MODE_LEGACY &&
        (benchmark_result.conv_caps & required_caps) != required_caps)
        return benchmark_error(BENCH_ERROR_CAPABILITY);

    input_dims.n = output_dims.n = (int32_t)c->batches;
    input_dims.h = (int32_t)c->input_h; input_dims.w = (int32_t)c->input_w;
    input_dims.c = (int32_t)c->input_c;
    filter_dims.n = (int32_t)c->output_c;
    filter_dims.h = (int32_t)c->kernel_h; filter_dims.w = (int32_t)c->kernel_w;
    filter_dims.c = (int32_t)c->group_c;
    output_dims.h = (int32_t)c->output_h; output_dims.w = (int32_t)c->output_w;
    output_dims.c = bias_dims.c = (int32_t)c->output_c;
    params.stride.h = (int32_t)c->stride_h; params.stride.w = (int32_t)c->stride_w;
    params.dilation.h = (int32_t)c->dilation_h; params.dilation.w = (int32_t)c->dilation_w;
    params.padding.h = (int32_t)c->pad_top; params.padding.w = (int32_t)c->pad_left;
    params.input_offset = c->input_offset; params.output_offset = c->output_offset;
    params.activation.min = c->activation_min; params.activation.max = c->activation_max;
    quant.multiplier = (int32_t *)(uintptr_t)c->multiplier_base;
    quant.shift = (int32_t *)(uintptr_t)c->shift_base;
    output = (int8_t *)(uintptr_t)c->output_base;
    golden = (const int8_t *)(uintptr_t)c->golden_base;
    function = c->mode == BENCH_MODE_LEGACY ? benchmark_legacy_convolve_wrapper_s8 :
                                            riscv_convolve_wrapper_s8_acc;
    if (c->mode == BENCH_MODE_LEGACY) {
        ctx.buf = (void *)(uintptr_t)c->scratch_base;
        ctx.size = (int32_t)c->scratch_bytes;
    }
    /* Hardware gets NULL scratch. The original baseline gets its original
     * 32-row s8 allocation. Both runs initialize guards outside timing. */
    for (uint32_t i = 0; i < c->scratch_bytes; ++i)
        ((volatile uint8_t *)(uintptr_t)c->scratch_base)[i] = 0u;
    for (uint32_t i = 0; i < c->output_bytes + 32u; ++i)
        ((volatile uint8_t *)output)[(int32_t)i - 16] = 0xa5u;
    benchmark_result.input_bytes = c->input_bytes;
    benchmark_result.filter_bytes = c->filter_bytes;
    benchmark_result.output_bytes = c->output_bytes;
    benchmark_result.scratch_bytes = c->scratch_bytes;

    benchmark_marker(BENCH_PROGRESS_BEGIN);
    begin = benchmark_cycle();
    status = function(&ctx, &params, &quant, &input_dims,
        (const int8_t *)(uintptr_t)c->input_base, &filter_dims,
        (const int8_t *)(uintptr_t)c->filter_base, &bias_dims,
        (const int32_t *)(uintptr_t)c->bias_base, &output_dims, output);
    end = benchmark_cycle();
    benchmark_marker(BENCH_PROGRESS_END);

    benchmark_result.start_cycle = begin;
    benchmark_result.end_cycle = end;
    benchmark_result.total_call_cycles = end - begin;
    benchmark_result.nmsis_status = status;
    /* This register updates only for hardware Conv. Legacy GEMM has no such
     * reading (UINT32_MAX means N/A); the testbench separately sums its actual
     * NPU busy intervals. This MMIO read is outside the measured call. */
    benchmark_result.npu_cycles_last = c->mode == BENCH_MODE_LEGACY ? UINT32_MAX :
                                     dsa_reg_read(NPU_REG_CONV_CYCLES);
    for (uint32_t i = 0; i < c->output_bytes; ++i) {
        const int32_t actual = output[i], expected = golden[i];
        hash = (hash ^ (uint8_t)actual) * 16777619u;
        if (actual != expected) {
            if (benchmark_result.mismatches == 0u) {
                benchmark_result.first_mismatch = i;
                benchmark_result.first_expected = expected;
                benchmark_result.first_actual = actual;
            }
            ++benchmark_result.mismatches;
        }
    }
    benchmark_result.output_fnv1a = hash;
    benchmark_result.compared_outputs = c->output_bytes;
    for (uint32_t i = 0; i < 16u; ++i) {
        if (((volatile uint8_t *)output)[(int32_t)i - 16] != 0xa5u)
            ++benchmark_result.guard_errors;
        if (((volatile uint8_t *)output)[c->output_bytes + i] != 0xa5u)
            ++benchmark_result.guard_errors;
    }
    if (status != RISCV_NMSIS_NN_SUCCESS) return benchmark_error(BENCH_ERROR_NMSIS);
    if (benchmark_result.guard_errors) return benchmark_error(BENCH_ERROR_GUARD);
    if (benchmark_result.mismatches) return benchmark_error(BENCH_ERROR_OUTPUT);
    return benchmark_error(BENCH_ERROR_NONE);
}

int main(void)
{
    return benchmark_run();
}
