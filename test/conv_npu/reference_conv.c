// SPDX-License-Identifier: Apache-2.0
// Direct NHWC/OHWI convolution, with the repository's NMSIS requantization.
// This reference never calls the accelerator or constructs im2col.
#include <stdint.h>
#include <limits.h>
#include "riscv_nnsupportfunctions.h"

int reference_conv(const int8_t *input, const int8_t *weight,
                   const int32_t *bias, const int32_t *mult, const int32_t *shift,
                   const int32_t *p, int8_t *output, int32_t *accumulators)
{
    const int h=p[0],w=p[1],c=p[2],gc=p[3],go=p[4],kh=p[5],kw=p[6];
    const int oh=p[7],ow=p[8],co=p[9],sh=p[10],sw=p[11],dh=p[12],dw=p[13];
    const int ph=p[14],pw=p[15],offset=p[16],out_offset=p[17],amin=p[18],amax=p[19];
    for(int y=0;y<oh;y++)for(int x=0;x<ow;x++)for(int oc=0;oc<co;oc++) {
        int64_t sum=bias[oc];
        for(int ky=0;ky<kh;ky++)for(int kx=0;kx<kw;kx++) {
            const int iy=y*sh+ky*dh-ph, ix=x*sw+kx*dw-pw;
            if(iy<0 || iy>=h || ix<0 || ix>=w)continue;
            for(int ic=0;ic<gc;ic++) {
                const int a=input[(iy*w+ix)*c+go+ic]+offset;
                const int b=weight[((oc*kh+ky)*kw+kx)*gc+ic];
                sum+=(int64_t)a*b;
            }
        }
        if(sum<INT32_MIN || sum>INT32_MAX)return 1;
        const int i=(y*ow+x)*co+oc;
        accumulators[i]=(int32_t)sum;
        int32_t value=riscv_nn_requantize((int32_t)sum,mult[oc],shift[oc]);
        value+=out_offset;
        if(value<amin)value=amin;
        if(value>amax)value=amax;
        output[i]=(int8_t)value;
    }
    return 0;
}
