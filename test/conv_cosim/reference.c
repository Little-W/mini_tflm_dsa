/* SPDX-License-Identifier: Apache-2.0 */
#include <stdint.h>
#include <limits.h>
#include "riscv_nnsupportfunctions.h"
/* Direct NHWC/OHWI convolution and signed quotient/remainder RNE. */
static int64_t reference_rne(int64_t numerator, int shift)
{
    int64_t denominator = INT64_C(1) << shift;
    int64_t q = numerator / denominator;
    int64_t r = numerator % denominator;
    int64_t magnitude = r < 0 ? -r : r;
    if (magnitude > denominator - magnitude ||
        (magnitude == denominator - magnitude && q % 2 != 0))
        q += numerator < 0 ? -1 : 1;
    return q;
}
int cosim_reference(const int8_t *input, const int8_t *filter,
                    const int32_t *bias, const int32_t *mult, const int32_t *shift,
                    const nmsis_nn_dims *in, const nmsis_nn_dims *f,
                    const nmsis_nn_dims *out, const nmsis_nn_conv_params *p,
                    int8_t *result)
{
    int groups=in->c/f->c, group_out=out->c/groups;
    int red=f->h*f->w*f->c;
    for(int b=0;b<in->n;b++)for(int y=0;y<out->h;y++)for(int x=0;x<out->w;x++)for(int oc=0;oc<out->c;oc++) {
        int64_t sum=bias?bias[oc]:0;
        int go=(oc/group_out)*f->c;
        for(int ky=0;ky<f->h;ky++)for(int kx=0;kx<f->w;kx++) {
            int64_t iy=(int64_t)y*p->stride.h+(int64_t)ky*p->dilation.h-p->padding.h;
            int64_t ix=(int64_t)x*p->stride.w+(int64_t)kx*p->dilation.w-p->padding.w;
            if(iy<0||iy>=in->h||ix<0||ix>=in->w)continue;
            for(int c=0;c<f->c;c++) {
                size_t ii=(((size_t)b*in->h+(size_t)iy)*in->w+(size_t)ix)*in->c+go+c;
                size_t wi=(size_t)oc*red+(ky*f->w+kx)*f->c+c;
                sum+=(int64_t)(input[ii]+p->input_offset)*filter[wi];
            }
        }
        if(sum<INT32_MIN||sum>INT32_MAX)return 1;
        int64_t value=reference_rne(sum*mult[oc],31-shift[oc])+p->output_offset;
        if(value<p->activation.min)value=p->activation.min;
        if(value>p->activation.max)value=p->activation.max;
        result[((b*out->h+y)*out->w+x)*out->c+oc]=(int8_t)value;
    }
    return 0;
}
