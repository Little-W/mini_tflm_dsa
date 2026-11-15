// SPDX-License-Identifier: Apache-2.0
#include "Vvector_pe.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <random>
#include <stdexcept>

static uint64_t comparisons=0,products=0;
static uint32_t execute(Vvector_pe &pe,unsigned op,uint16_t a,uint16_t b,int32_t acc){
    pe.op=op;pe.a=a;pe.b=b;pe.acc=uint32_t(acc);pe.eval();return pe.result;
}
static void check(Vvector_pe &pe,uint16_t a,uint16_t b,int32_t acc){
    const int32_t sa=int16_t(a),sb=int16_t(b);
    const int64_t signed_product=int64_t(sa)*sb;
    const std::array<uint32_t,7> expected{
        uint32_t(acc)+uint32_t(signed_product),uint32_t(acc)+uint32_t(sa),
        uint32_t(acc>sa?acc:sa),uint32_t(acc<sa?acc:sa),uint32_t(signed_product),
        uint32_t(uint64_t(a)*b),uint32_t(int64_t(sa)*b)};
    for(unsigned op=0;op<expected.size();op++){
        if(execute(pe,op,a,b,acc)!=expected[op])throw std::runtime_error("16-bit PE arithmetic mismatch");
        comparisons++;
    }
}
static void check_full_product(Vvector_pe &pe,int32_t a,int32_t multiplier){
    const uint16_t al=uint16_t(a),ah=uint16_t(uint32_t(a)>>16);
    const uint16_t ml=uint16_t(multiplier),mh=uint16_t(uint32_t(multiplier)>>16);
    int64_t assembled=execute(pe,5,al,ml,0);
    assembled+=int64_t(execute(pe,5,al,mh,0))*(INT64_C(1)<<16);
    assembled+=int64_t(int32_t(execute(pe,6,ah,ml,0)))*(INT64_C(1)<<16);
    assembled+=int64_t(int32_t(execute(pe,6,ah,mh,0)))*(INT64_C(1)<<32);
    if(assembled!=int64_t(a)*multiplier)throw std::runtime_error("four-part complete product mismatch");
    products++;
}
int main(int argc,char **argv){
    Verilated::commandArgs(argc,argv);
    try{
        Vvector_pe pe;std::mt19937 rng(20261115);
        for(uint32_t a=0;a<65536;a++)for(uint16_t b:{0u,1u,2u,0x7fffu,0x8000u,0x8001u,0xfffeu,0xffffu,0x5555u,0xaaaau})
            check(pe,uint16_t(a),b,int32_t(rng()));
        for(int32_t a:{INT32_MIN,INT32_MIN+1,-65536,-65535,-32768,-255,-1,0,1,255,32767,65535,65536,INT32_MAX-1,INT32_MAX})
            for(int32_t m:{0,1,2,32767,32768,65535,65536,0x40000000,0x7fff0000,INT32_MAX})check_full_product(pe,a,m);
        for(unsigned i=0;i<100000;i++){
            check(pe,uint16_t(rng()),uint16_t(rng()),int32_t(rng()));
            check_full_product(pe,int32_t(rng()),int32_t(rng()&INT32_MAX));
        }
        std::printf("VECTOR_PE_PASS comparisons=%llu full_products=%llu\n",
                    (unsigned long long)comparisons,(unsigned long long)products);
        return 0;
    }catch(const std::exception &error){
        std::fprintf(stderr,"FAIL: %s\n",error.what());return 1;
    }
}
