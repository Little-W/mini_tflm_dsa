/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "riscv_nnfunctions.h"
#include "dsa_accel.h"

static uint32_t regs[128], reads, writes, starts;
static uint32_t completion_status, completion_result;
static unsigned checks;
#define CHECK(x) do { ++checks; assert(x); } while (0)

static void reset_device(void)
{
    memset(regs, 0, sizeof(regs));
    regs[NPU_REG_ID / 4] = 0x4e505531u;
    regs[NPU_REG_CONFIG_ABI / 4] = 2;
    regs[NPU_REG_CONV_CAPS / 4] = 0x00010007;
    regs[NPU_REG_VECTOR_CAPS / 4] = 0x0131083f;
    regs[NPU_REG_POOL_MAX_TAPS / 4] = DSA_POOL_MAX_TAPS;
    regs[NPU_REG_STATUS / 4] = 1;
    reads = writes = starts = 0;
    completion_status = 5;
    completion_result = 0;
}

void dsa_mmio_write(uint32_t address, uint32_t value)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    CHECK(offset < sizeof(regs) && !(offset & 3u));
    ++writes;
    if (offset == NPU_REG_STATUS) { regs[offset / 4] &= ~(value & 4u); return; }
    regs[offset / 4] = value;
    if (offset == NPU_REG_CTRL && (value & 1u)) {
        ++starts;
        regs[NPU_REG_STATUS / 4] = completion_status;
        regs[NPU_REG_WB_DATA / 4] = completion_result;
    }
}

uint32_t dsa_mmio_read(uint32_t address)
{
    const uint32_t offset = address - DSA_MMIO_BASE;
    CHECK(offset < sizeof(regs) && !(offset & 3u));
    ++reads;
    return regs[offset / 4];
}

static int64_t divide_rne(int64_t value, int64_t divisor)
{
    int64_t quotient=value/divisor;
    const int64_t remainder=value%divisor;
    const int64_t magnitude=remainder<0?-remainder:remainder;
    if(magnitude>divisor-magnitude || (magnitude==divisor-magnitude && quotient%2))
        quotient+=value<0?-1:1;
    return quotient;
}

static int32_t quantize(int32_t value, int32_t multiplier, int32_t shift,
                        int offset, int lo, int hi)
{
    int64_t result=divide_rne((int64_t)value*multiplier,INT64_C(1)<<(31-shift))+offset;
    if(result<lo)result=lo;
    if(result>hi)result=hi;
    return (int32_t)result;
}

static void check_values(const int8_t *actual, const int8_t *expected, int count)
{
    for (int i = 0; i < count; ++i) CHECK(actual[i] == expected[i]);
}

static void check_dispatch(uint32_t mask, uint32_t bit, unsigned commands,
                           const int8_t *output, const int8_t *expected, int count)
{
    if (mask & bit) CHECK(starts == commands && writes > 0 && reads > 0);
    else {
        CHECK(starts == 0 && writes == 0 && reads == 0);
        check_values(output, expected, count);
    }
}

int main(void)
{
    uint8_t *memory = mmap(NULL, 65536, PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    CHECK(memory != MAP_FAILED && (uintptr_t)memory < UINT32_MAX - 65536u);
    int8_t *input = (int8_t *)memory, *filter = (int8_t *)(memory + 4096);
    int8_t *output = (int8_t *)(memory + 8192);
    int32_t *bias = (int32_t *)(memory + 12288);
    int32_t *mult = (int32_t *)(memory + 16384);
    int32_t *shift = (int32_t *)(memory + 20480);
    nmsis_nn_context context = {memory + 24576, 8192};
    int8_t expected[256];
    for (int i = 0; i < 256; ++i) input[i] = (int8_t)((i * 19) % 71 - 35);
    for (int i = 0; i < 256; ++i) filter[i] = (int8_t)((i * 7) % 13 - 6);
    for (int i = 0; i < 16; ++i) { bias[i] = i * 11 - 29; mult[i] = 1073741824 + i * 1000; shift[i] = -2; }
    nmsis_nn_per_channel_quant_params q = {mult, shift};
    nmsis_nn_dims bd = {1, 1, 1, 5};
    CHECK(dsa_nn_get_accelerators() == DSA_NN_ACCEL_ALL);
    dsa_nn_set_accelerators(UINT32_MAX);
    CHECK(dsa_nn_get_accelerators() == DSA_NN_ACCEL_ALL);

    for (uint32_t mask = 0; mask <= DSA_NN_ACCEL_ALL; ++mask) {
        dsa_nn_set_accelerators(mask);
        nmsis_nn_dims in = {2, 2, 3, 3}, f = {5, 1, 1, 3}, out = {2, 2, 3, 5};
        nmsis_nn_conv_params p = {.input_offset=7, .output_offset=-3,
            .stride={1,1}, .padding={0,0}, .dilation={1,1}, .activation={-100,100}};
        for (int pos = 0; pos < 12; ++pos) for (int c = 0; c < 5; ++c) {
            int32_t sum = bias[c];
            for (int k = 0; k < 3; ++k) sum += (input[pos * 3 + k] + 7) * filter[c * 3 + k];
            expected[pos * 5 + c] = (int8_t)quantize(sum, mult[c], shift[c], -3, -100, 100);
        }
        reset_device(); memset(output, 0x55, 256);
        CHECK(riscv_convolve_wrapper_s8_acc(&context, &p, &q, &in, input,
              &f, filter, &bd, bias, &out, output) == RISCV_NMSIS_NN_SUCCESS);
        check_dispatch(mask, DSA_NN_ACCEL_CONV, 2, output, expected, 60);

        in = (nmsis_nn_dims){2,4,3,3}; f = (nmsis_nn_dims){1,3,2,3};
        out = (nmsis_nn_dims){2,4,2,3};
        nmsis_nn_dw_conv_params dw = {.input_offset=7, .output_offset=-3, .ch_mult=1,
            .stride={1,1}, .padding={0,1}, .dilation={1,1}, .activation={-100,100}};
        for (int batch=0; batch<2; ++batch) for (int y=0; y<4; ++y)
            for (int x=0; x<2; ++x) for (int c=0; c<3; ++c) {
                int32_t sum=bias[c];
                for (int ky=0; ky<3; ++ky) for (int kx=0; kx<2; ++kx) {
                    int iy=y+ky-1, ix=x+kx;
                    if (iy>=0 && iy<4) sum += (input[((batch*4+iy)*3+ix)*3+c]+7)*filter[(ky*2+kx)*3+c];
                }
                expected[((batch*4+y)*2+x)*3+c]=(int8_t)quantize(sum,mult[c],shift[c],-3,-100,100);
            }
        reset_device(); memset(output,0x55,256);
        CHECK(riscv_depthwise_conv_wrapper_s8_acc(&context,&dw,&q,&in,input,&f,filter,&bd,bias,&out,output)==RISCV_NMSIS_NN_SUCCESS);
        check_dispatch(mask,DSA_NN_ACCEL_DW,2,output,expected,48);

        f=(nmsis_nn_dims){1,2,2,1}; out=(nmsis_nn_dims){2,3,2,3};
        nmsis_nn_pool_params pool={.stride={1,1},.padding={0,0},.activation={-100,100}};
        for(int kind=0;kind<2;++kind) {
            for(int b=0;b<2;++b)for(int y=0;y<3;++y)for(int x=0;x<2;++x)for(int c=0;c<3;++c) {
                int value=kind?-128:0;
                for(int ky=0;ky<2;++ky)for(int kx=0;kx<2;++kx) {
                    int v=input[((b*4+y+ky)*3+x+kx)*3+c];
                    if(kind) {if(v>value)value=v;} else value+=v;
                }
                if(!kind)value=(int)divide_rne(value,4);
                expected[((b*3+y)*2+x)*3+c]=(int8_t)value;
            }
            reset_device();memset(output,0x55,256);
            riscv_nmsis_nn_status status=kind?riscv_max_pool_s8(&context,&pool,&in,input,&f,&out,output):
                riscv_avgpool_s8(&context,&pool,&in,input,&f,&out,output);
            CHECK(status==RISCV_NMSIS_NN_SUCCESS);
            check_dispatch(mask,DSA_NN_ACCEL_POOL,2,output,expected,36);
        }

        in=(nmsis_nn_dims){2,1,1,7}; f=(nmsis_nn_dims){7,1,1,5}; out=(nmsis_nn_dims){2,1,1,5};
        for(int per_channel=0;per_channel<2;++per_channel) for(int filter_offset=0;filter_offset>=-2;filter_offset-=2) {
            nmsis_nn_fc_params fc={.input_offset=7,.filter_offset=filter_offset,.output_offset=-3,.activation={-100,100}};
            nmsis_nn_quant_params fq={.multiplier=mult,.shift=shift,.is_per_channel=per_channel};
            for(int b=0;b<2;++b)for(int c=0;c<5;++c) {
                int32_t sum=bias[c];
                for(int k=0;k<7;++k)sum+=(input[b*7+k]+7)*(filter[c*7+k]+filter_offset);
                int qi=per_channel?c:0;
                expected[b*5+c]=(int8_t)quantize(sum,mult[qi],shift[qi],-3,-100,100);
            }
            reset_device();memset(output,0x55,256);
            CHECK(riscv_fully_connected_wrapper_s8_acc(NULL,&fc,&fq,&in,input,&f,filter,&bd,bias,&out,output)==RISCV_NMSIS_NN_SUCCESS);
            check_dispatch(mask,DSA_NN_ACCEL_FC,1,output,expected,10);
        }
        const dsa_vector_add_params_t aq[3]={
            {128,-4,1623821475,-2,1073741824,0,20,1098017566,-17},
            {17,-4,1699529983,-2,1073741824,0,20,1140768826,-17},
            {-38,2,1657902019,-2,1073741824,0,20,1835721671,-18}};
        for(int parameter=0;parameter<3;++parameter) {
            const dsa_vector_add_params_t *a=&aq[parameter];
            for(int i=0;i<137;++i) {
                int32_t first=quantize((input[i]+a->input1_offset)*(1<<a->left_shift),a->input1_multiplier,a->input1_shift,0,INT32_MIN,INT32_MAX);
                int32_t second=quantize((filter[i]+a->input2_offset)*(1<<a->left_shift),a->input2_multiplier,a->input2_shift,0,INT32_MIN,INT32_MAX);
                expected[i]=(int8_t)quantize(first+second,a->output_multiplier,a->output_shift,-128,-128,127);
            }
            reset_device();memset(output,0x55,256);
            CHECK(riscv_elementwise_add_s8(input,filter,a->input1_offset,a->input1_multiplier,a->input1_shift,
                a->input2_offset,a->input2_multiplier,a->input2_shift,a->left_shift,output,-128,
                a->output_multiplier,a->output_shift,-128,127,137)==RISCV_NMSIS_NN_SUCCESS);
            check_dispatch(mask,DSA_NN_ACCEL_ADD,1,output,expected,137);
            if(mask&DSA_NN_ACCEL_ADD) {
                CHECK(regs[NPU_REG_VECTOR_OP/4]==DSA_VECTOR_OP_ADD_S8);
                CHECK(regs[NPU_REG_VECTOR_LENGTH/4]==137u);
                CHECK(regs[NPU_REG_VECTOR_ADD_INPUT1_MULT/4]==(uint32_t)a->input1_multiplier);
                CHECK(regs[NPU_REG_VECTOR_ADD_INPUT1_SHIFT/4]==(uint32_t)a->input1_shift);
                CHECK(regs[NPU_REG_VECTOR_ADD_INPUT2_MULT/4]==(uint32_t)a->input2_multiplier);
                CHECK(regs[NPU_REG_VECTOR_ADD_INPUT2_SHIFT/4]==(uint32_t)a->input2_shift);
                CHECK(regs[NPU_REG_VECTOR_ADD_LEFT_SHIFT/4]==(uint32_t)a->left_shift);
            }
        }
    }

    dsa_nn_set_accelerators(DSA_NN_ACCEL_ALL);
    nmsis_nn_dims in={1,1,1,7},f={7,1,1,5},out={1,1,1,5};
    nmsis_nn_fc_params fc={.activation={-128,127}};
    nmsis_nn_quant_params fq={.multiplier=mult,.shift=shift,.is_per_channel=1};
    reset_device();regs[NPU_REG_STATUS/4]=2;
    CHECK(riscv_fully_connected_wrapper_s8_acc(NULL,&fc,&fq,&in,input,&f,filter,&bd,bias,&out,output)==RISCV_NMSIS_NN_NO_IMPL_ERROR);
    CHECK(starts==0 && writes==0);
    reset_device();
    CHECK(riscv_fully_connected_wrapper_s8_acc(NULL,NULL,&fq,&in,input,&f,filter,&bd,bias,&out,output)==RISCV_NMSIS_NN_ARG_ERROR);
    CHECK(riscv_fully_connected_wrapper_s8_acc(NULL,&fc,NULL,&in,input,&f,filter,&bd,bias,&out,output)==RISCV_NMSIS_NN_ARG_ERROR);
    CHECK(starts==0 && reads==0 && writes==0);
    dsa_nn_set_accelerators(0);
    CHECK(riscv_fully_connected_wrapper_s8_acc(NULL,&fc,&fq,&in,input,&f,filter,&bd,bias,&out,expected)==RISCV_NMSIS_NN_SUCCESS);
    dsa_nn_set_accelerators(DSA_NN_ACCEL_ALL);
    reset_device();regs[NPU_REG_ID/4]=0;
    CHECK(riscv_fully_connected_wrapper_s8_acc(NULL,&fc,&fq,&in,input,&f,filter,&bd,bias,&out,output)==RISCV_NMSIS_NN_SUCCESS);
    CHECK(starts==0 && writes==0);check_values(output,expected,5);
    int8_t high_input[7]; memcpy(high_input,input,sizeof(high_input));
    reset_device();
    CHECK(riscv_fully_connected_wrapper_s8_acc(NULL,&fc,&fq,&in,high_input,&f,filter,&bd,bias,&out,output)==RISCV_NMSIS_NN_SUCCESS);
    CHECK(starts==0 && writes==0 && reads==0);check_values(output,expected,5);
    for (int failure = 0; failure < 3; ++failure) for (int kind = 0; kind < 6; ++kind) {
        const nmsis_nn_dims ci={2,3,3,3}, cf={3,1,1,3}, co={2,3,3,3};
        const nmsis_nn_conv_params cp={.stride={1,1},.dilation={1,1},.activation={-128,127}};
        const nmsis_nn_dw_conv_params dp={.ch_mult=1,.stride={1,1},.dilation={1,1},.activation={-128,127}};
        const nmsis_nn_pool_params pp={.stride={1,1},.activation={-128,127}};
        riscv_nmsis_nn_status status;
        reset_device(); memset(output,0x55,256);
        if (failure == 0) completion_status = 5u | (3u << DSA_STATUS_ERR_SHIFT);
        else if (failure == 1) completion_status = 2;
        else completion_result = 3;
        switch (kind) {
        case 0: status=riscv_fully_connected_wrapper_s8_acc(NULL,&fc,&fq,&in,input,&f,filter,&bd,bias,&out,output); break;
        case 1: status=riscv_convolve_wrapper_s8_acc(&context,&cp,&q,&ci,input,&cf,filter,&bd,bias,&co,output); break;
        case 2: status=riscv_depthwise_conv_wrapper_s8_acc(&context,&dp,&q,&ci,input,&cf,filter,&bd,bias,&co,output); break;
        case 3: status=riscv_avgpool_s8(&context,&pp,&ci,input,&cf,&co,output); break;
        case 4: status=riscv_max_pool_s8(&context,&pp,&ci,input,&cf,&co,output); break;
        default: status=riscv_elementwise_add_s8(input,filter,128,1623821475,-2,-4,1073741824,0,20,
            output,-128,1098017566,-17,-128,127,137); break;
        }
        CHECK(status==RISCV_NMSIS_NN_NO_IMPL_ERROR);
        CHECK(starts==1);
        for (int i=0;i<256;++i) CHECK(output[i]==0x55);
    }
    CHECK(munmap(memory,65536)==0);
    printf("NMSIS_RUNTIME_PASS masks=%u checks=%u\n",DSA_NN_ACCEL_ALL+1,checks);
    return 0;
}
