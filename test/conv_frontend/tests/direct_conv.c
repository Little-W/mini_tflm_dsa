/* SPDX-License-Identifier: Apache-2.0
 * Independent NHWC / OHWI direct-convolution reference, no im2col and no cache.
 * Verification-only; this is not used in the accelerator runtime.
 */
#include <stdint.h>
#include <stddef.h>
#include <limits.h>
#include <string.h>

int direct_conv(const int32_t *p, const int16_t *input, const int8_t *weight,
                const int32_t *bias, int32_t cout, int32_t *output) {
    const int h=p[0], w=p[1], cin=p[2], kh=p[3], kw=p[4], oh=p[5], ow=p[6];
    const int sh=p[7], sw=p[8], dh=p[9], dw=p[10], pt=p[11], pl=p[12];
    const int gc=p[13], go=p[14], offset=p[15];
    if (h<=0 || w<=0 || cin<=0 || kh<=0 || kw<=0 || oh<=0 || ow<=0 || cout<=0 ||
        gc<=0 || go<0 || gc+go>cin || sh<=0 || sw<=0 || dh<=0 || dw<=0) return -1;
    for (int y=0;y<oh;y++) for(int x=0;x<ow;x++) for(int oc=0;oc<cout;oc++) {
        int64_t sum=bias ? bias[oc] : 0;
        for (int ky=0;ky<kh;ky++) for(int kx=0;kx<kw;kx++) {
            const int iy=y*sh-pt+ky*dh, ix=x*sw-pl+kx*dw;
            if (iy<0 || iy>=h || ix<0 || ix>=w) continue; /* corrected padding = 0 */
            for(int c=0;c<gc;c++) {
                size_t ii=((size_t)iy*w+ix)*cin+go+c;
                size_t wi=(((size_t)oc*kh+ky)*kw+kx)*gc+c;
                sum += ((int32_t)input[ii]+offset)*(int32_t)weight[wi];
            }
        }
        uint32_t bits=(uint32_t)(uint64_t)sum;
        memcpy(output+((size_t)y*ow+x)*cout+oc,&bits,sizeof bits);
    }
    return 0;
}

/* Explicit two-rounding numerical contract, independent implementation. */
int quant_contract(int32_t value, int32_t multiplier, int shift, int offset,
                   int amin, int amax, int32_t *result) {
    if (!result || shift < -31 || shift > 30 || amin>amax) return -1;
    int64_t val=(int64_t)value*((int64_t)1<<(shift>0 ? shift : 0));
    if (val<INT32_MIN || val>INT32_MAX) return -2;
    int64_t prod=val*multiplier+((int64_t)1<<30);
    /* Floor division, independent of implementation-defined signed right shift. */
    int64_t den=(int64_t)1<<31;
    int64_t high=prod>=0 ? prod/den : -((-prod+den-1)/den);
    if (shift<0) {
        den=(int64_t)1<<(-shift);
        int64_t magnitude=high<0 ? -high : high;
        high=(magnitude+den/2)/den*(high<0 ? -1 : 1);
    }
    high+=offset;
    if (high<amin) high=amin;
    if (high>amax) high=amax;
    *result=(int32_t)high;
    return 0;
}
