/* SPDX-License-Identifier: Apache-2.0 */
#include "riscv_nnfunctions.h"
#include <stdint.h>
#include <string.h>

int dw_pool_reference(const uint32_t *c, const int8_t *input, const int8_t *weight,
                      const int32_t *bias, int32_t *mult, int32_t *shift, int8_t *output)
{
    nmsis_nn_context ctx = {0};
    nmsis_nn_dims in = {1,(int32_t)c[11],(int32_t)c[12],(int32_t)c[13]};
    nmsis_nn_dims kernel = {1,(int32_t)c[14],(int32_t)c[15],(int32_t)c[13]};
    nmsis_nn_dims out = {1,(int32_t)c[16],(int32_t)c[17],(int32_t)c[13]};
    nmsis_nn_dims bd = {1,1,1,(int32_t)c[13]};
    if ((c[0]&15u) == 0) {
        nmsis_nn_dw_conv_params p;
        memset(&p,0,sizeof(p));p.input_offset=(int32_t)c[24];p.output_offset=(int32_t)c[8];p.ch_mult=1;
        p.stride.h=(int32_t)c[18];p.stride.w=(int32_t)c[19];
        p.dilation.h=(int32_t)c[20];p.dilation.w=(int32_t)c[21];
        p.padding.h=(int32_t)c[22];p.padding.w=(int32_t)c[23];
        p.activation.min=(int32_t)c[9];p.activation.max=(int32_t)c[10];
        nmsis_nn_per_channel_quant_params q={mult,shift};
        return riscv_depthwise_conv_s8(&ctx,&p,&q,&in,input,&kernel,weight,&bd,bias,&out,output);
    }
    nmsis_nn_pool_params p;
    memset(&p,0,sizeof(p));p.stride.h=(int32_t)c[18];p.stride.w=(int32_t)c[19];
    p.padding.h=(int32_t)c[22];p.padding.w=(int32_t)c[23];
    p.activation.min=(int32_t)c[9];p.activation.max=(int32_t)c[10];
    if ((c[0]&15u)==1) return riscv_avgpool_s8(&ctx,&p,&in,input,&kernel,&out,output);
    if ((c[0]&15u)==2) return riscv_max_pool_s8(&ctx,&p,&in,input,&kernel,&out,output);
    for (int oy=0;oy<out.h;oy++) for (int ox=0;ox<out.w;ox++) for (int ch=0;ch<in.c;ch++) {
        int best=127;
        for (int ky=0;ky<kernel.h;ky++) for (int kx=0;kx<kernel.w;kx++) {
            int y=oy*p.stride.h-p.padding.h+ky,x=ox*p.stride.w-p.padding.w+kx;
            if (y>=0 && y<in.h && x>=0 && x<in.w) {
                int value=input[(y*in.w+x)*in.c+ch];if (value<best) best=value;
            }
        }
        if (best<p.activation.min) best=p.activation.min;
        if (best>p.activation.max) best=p.activation.max;
        output[(oy*out.w+ox)*in.c+ch]=(int8_t)best;
    }
    return 0;
}
