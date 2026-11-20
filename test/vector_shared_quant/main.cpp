// SPDX-License-Identifier: Apache-2.0
#include "Vshared_quant_top.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include <stdexcept>
#include <string>

static void require(bool condition, const std::string &message) {
  if (!condition) throw std::runtime_error(message);
}

// 参考计算使用整数除法与余数，独立检查最近偶数舍入和有符号饱和。
static int8_t reference(int32_t value, int32_t multiplier, unsigned right,
                        int32_t offset, int32_t minimum, int32_t maximum) {
  __int128 product=__int128(value)*multiplier;
  const bool negative=product<0;
  __int128 magnitude=negative ? -product : product;
  const __int128 divisor=__int128(1)<<right;
  __int128 quotient=magnitude/divisor, remainder=magnitude%divisor;
  if (remainder>divisor-remainder || (remainder==divisor-remainder && (quotient&1))) ++quotient;
  __int128 result=(negative ? -quotient : quotient)+offset;
  result=std::max<__int128>(minimum,std::min<__int128>(maximum,result));
  return int8_t(std::max<__int128>(-128,std::min<__int128>(127,result)));
}

struct Expected {
  uint64_t cycle;
  bool dw, tag;
  std::array<int8_t,16> data;
};

int main(int argc,char **argv) {
  Verilated::commandArgs(argc,argv);
  Vshared_quant_top dut;
  std::deque<Expected> pending;
  std::mt19937 random{20261120};
  uint64_t cycle=0, vectors=0, dw_vectors=0, matrix_vectors=0;
  auto tick=[&] {
    dut.clk=0;dut.eval();
    dut.clk=1;dut.eval();++cycle;Verilated::timeInc(1);
    bool valid=dut.dw_out_valid || dut.matrix_out_valid;
    require(!(dut.dw_out_valid && dut.matrix_out_valid),"one result was delivered to both clients");
    if (valid) {
      require(!pending.empty(),"output without accepted input");
      const Expected expected=pending.front();pending.pop_front();
      require(expected.cycle==cycle,"quantization latency changed");
      require(bool(dut.dw_out_valid)==expected.dw,"result returned to another client");
      if (expected.dw) require(bool(dut.dw_out_tag)==expected.tag,"result tag differs");
      for (unsigned lane=0;lane<16;lane++) {
        if (int8_t(dut.output_data[lane])!=expected.data[lane]) {
          std::fprintf(stderr,"cycle=%llu lane=%u dw=%u got=%d expected=%d\n",
            (unsigned long long)cycle,lane,expected.dw,int(int8_t(dut.output_data[lane])),int(expected.data[lane]));
          throw std::runtime_error("quantization output differs");
        }
      }
      ++vectors;
      if (expected.dw) ++dw_vectors; else ++matrix_vectors;
    }
    require(pending.empty() || pending.front().cycle>cycle,"quantization output was lost");
    dut.clk=0;dut.eval();
  };
  try {
    dut.rst_n=0;dut.init_cfg=0;dut.dw_enable=0;dut.in_valid=0;dut.dw_valid=0;
    dut.in_tile_done=0;dut.dw_tag=0;dut.dw_mask=0;
    dut.output_offset=0;dut.activation_minimum=uint32_t(-128);dut.activation_maximum=127;
    dut.matrix_multiplier=0;dut.matrix_shift=0;
    for (unsigned lane=0;lane<16;lane++) {
      dut.input_data[lane]=0;dut.dw_multiplier[lane]=0;dut.dw_right[lane]=0;
    }
    tick();tick();dut.rst_n=1;tick();
    const std::array<int32_t,10> edges={INT32_MIN,INT32_MAX,0,1,-1,32768,-32768,0x40000000,-0x40000000,3};
    // 每轮执行 GEMM、DW、GEMM，连续输入和随机空拍同时覆盖全部十二级流水。
    for (unsigned task=0;task<240;task++) {
      const bool dw=task%3==1;
      dut.dw_enable=dw;
      int32_t offset=int32_t(random()%256)-128;
      int32_t minimum=-128+int32_t(random()%32),maximum=127-int32_t(random()%32);
      dut.output_offset=uint32_t(offset);dut.activation_minimum=uint32_t(minimum);dut.activation_maximum=uint32_t(maximum);
      int32_t common_multiplier=task<30 ? edges[task%edges.size()] : int32_t(random());
      unsigned common_right=1+task%62;
      dut.matrix_multiplier=uint32_t(common_multiplier);dut.matrix_shift=uint32_t(31-int32_t(common_right));
      dut.init_cfg=!dw;tick();dut.init_cfg=0;
      for (unsigned idle=0;idle<3;idle++) tick();
      for (unsigned row=0;row<32;row++) {
        for (unsigned idle=0;idle<random()%4;idle++) tick();
        Expected expected{cycle+12,dw,bool(random()&1),{}};
        dut.dw_tag=expected.tag;
        dut.dw_mask=uint16_t(random());
        if (row%8==0) dut.dw_mask=0xffff;
        if (row%8==1) dut.dw_mask=0x0001;
        for (unsigned lane=0;lane<16;lane++) {
          int32_t value=row<10 ? edges[(row+lane)%edges.size()] : int32_t(random());
          int32_t multiplier=lane<10 ? edges[(lane+task)%edges.size()] : int32_t(random());
          unsigned right=(row+lane+task)%64;
          dut.input_data[lane]=uint32_t(value);dut.dw_multiplier[lane]=uint32_t(multiplier);dut.dw_right[lane]=right;
          expected.data[lane]=dw && !(dut.dw_mask&(1u<<lane)) ? 0 :
            reference(value,dw ? multiplier : common_multiplier,dw ? right : common_right,offset,minimum,maximum);
        }
        dut.dw_valid=dw;dut.in_valid=!dw;dut.in_tile_done=row%16==15;
        dut.eval();if (dw) require(dut.dw_ready,"shared quantizer did not accept a DW input");
        pending.push_back(expected);tick();dut.dw_valid=0;dut.in_valid=0;dut.in_tile_done=0;
      }
      while (!pending.empty()) tick();
      tick();
    }
    dut.final();
    std::printf("VECTOR_SHARED_QUANT_PASS vectors=%llu outputs=%llu dw_vectors=%llu matrix_vectors=%llu tasks=240\n",
      (unsigned long long)vectors,(unsigned long long)(16*vectors),
      (unsigned long long)dw_vectors,(unsigned long long)matrix_vectors);
  } catch (const std::exception &error) {
    std::fprintf(stderr,"VECTOR_SHARED_QUANT_FAIL %s\n",error.what());return 1;
  }
  return 0;
}
