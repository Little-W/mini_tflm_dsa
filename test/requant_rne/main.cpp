// SPDX-License-Identifier: Apache-2.0
#include "Vtb_requant_rne.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>

static int64_t divide_even(int64_t n, unsigned shift) {
    if (!shift) return n;
    const int64_t d = int64_t(1) << shift;
    int64_t q=n/d, r=n%d;
    if (r<0) r=-r;
    if (r>d-r || (r==d-r && q%2)) q+=n<0?-1:1;
    return q;
}
static int64_t clip(int64_t v,int64_t lo,int64_t hi) { return std::max(lo,std::min(hi,v)); }
int main(int argc,char** argv) {
    VerilatedContext ctx; ctx.commandArgs(argc,argv); Vtb_requant_rne dut(&ctx);
    auto tick=[&](){dut.clk=0;dut.eval();ctx.timeInc(1);dut.clk=1;dut.eval();ctx.timeInc(1);};
    dut.rst_n=0;dut.init_cfg=0;dut.in_valid=0;tick();tick();dut.rst_n=1;
    uint32_t rng=0x3257ae19;unsigned checked=0;
    auto random=[&](){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;};
    try {
        for(unsigned test=0;test<20000;++test) {
            const std::array<int32_t,10> coeff={0,1,32768,98304,163840,0x40000000,0x60000000,0x7ffe8000,0x7fff0000,INT32_MAX};
            int32_t m=test<1000?coeff[test%coeff.size()]:int32_t(random()&INT32_MAX);
            int32_t shift=-31+int32_t(test%62);
            int32_t offset=int32_t(test%256)-128;
            if (test%37==0) offset=INT32_MAX;
            else if (test%37==1) offset=INT32_MIN;
            if (test%7==0) m=int32_t(random());
            dut.multiplier=m;dut.shift=shift;dut.offset=offset;dut.init_cfg=1;tick();dut.init_cfg=0;
            for(int i=0;i<4;i++)tick();
            std::array<int8_t,4> expected_s8;std::array<int16_t,4> expected_s16;
            for(unsigned lane=0;lane<4;++lane) {
                int32_t v=test<512?int32_t(test)-256:int32_t(random());
                if(lane==1 && v!=INT32_MIN)v=-v;
                if(lane==2)v=INT32_MIN;
                if(lane==3)v=INT32_MAX;
                dut.input_s32[lane]=v;dut.input_s64[lane]=uint64_t(int64_t(v));
                expected_s8[lane]=int8_t(clip(divide_even(int64_t(v)*m,31-shift)+offset,-128,127));
                int64_t reduced=std::min<int64_t>(32767,divide_even(m,16));
                expected_s16[lane]=int16_t(clip(divide_even(int64_t(v)*reduced,15-std::min(shift,15)),-32768,32767));
            }
            dut.in_valid=1;tick();dut.in_valid=0;
            unsigned found=0;
            for(unsigned cycle=0;cycle<16;++cycle) {
                if(dut.valid_s16) {
                    for(unsigned i=0;i<4;++i)if(int16_t(dut.output_s16[i])!=expected_s16[i])throw std::runtime_error("s16 mismatch");
                    found|=1;
                }
                if(dut.valid_tensor||dut.valid_full) {
                    if(!dut.valid_tensor||!dut.valid_full)throw std::runtime_error("valid mismatch");
                    for(unsigned i=0;i<4;++i)if(int8_t(dut.output_tensor[i])!=expected_s8[i]||int8_t(dut.output_full[i])!=expected_s8[i]) {
                        std::cerr<<"test="<<test<<" lane="<<i<<" m="<<m<<" shift="<<shift<<" expected="<<int(expected_s8[i])<<" full="<<int(int8_t(dut.output_full[i]))<<" tensor="<<int(int8_t(dut.output_tensor[i]))<<'\n';
                        throw std::runtime_error("s8 mismatch");
                    }
                    found|=2;
                }
                if(dut.valid_shared_s16) {
                    for(unsigned i=0;i<4;++i)if(int16_t(dut.output_shared_s16[i])!=expected_s16[i]) {
                        std::cerr<<"shared s16 test="<<test<<" lane="<<i<<" multiplier="<<m<<" shift="<<shift<<" got="<<int16_t(dut.output_shared_s16[i])<<" expected="<<expected_s16[i]<<'\n';
                        throw std::runtime_error("shared s16 mismatch");
                    }
                    found|=4;
                }
                tick();
            }
            if(found!=7)throw std::runtime_error("missing output");
            checked+=16;
        }
        std::cout<<"REQUANT_RNE_PASS outputs="<<checked<<" variants=4\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
    dut.final();return 0;
}
