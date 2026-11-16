/* SPDX-License-Identifier: Apache-2.0 */
#include "Vvector_softmax_test.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#include "tensorflow/lite/kernels/internal/quantization_util.h"
#include "tensorflow/lite/kernels/internal/reference/softmax.h"
#include "tensorflow/lite/micro/kernels/softmax_vce.h"

#ifndef TEST_MAX_DEPTH
#define TEST_MAX_DEPTH 16
#endif

using Table=std::array<int32_t,256>;
static std::mt19937 random_values(20261115);
static uint64_t case_count,element_count,cycle_count,request_count;

static tflite::SoftmaxParams parameters(double scale) {
  tflite::SoftmaxParams p={};
  tflite::PreprocessSoftmaxScaling(1.0,scale,5,&p.input_multiplier,&p.input_left_shift);
  p.diff_min=-tflite::CalculateInputRadius(5,p.input_left_shift);
  return p;
}

static std::vector<int8_t> reference(const std::vector<int8_t>& input,
                                    const tflite::SoftmaxParams& p) {
  std::vector<int8_t> result(input.size());
  const tflite::RuntimeShape shape({1,static_cast<int>(input.size())});
  tflite::reference_ops::Softmax(p,shape,input.data(),shape,result.data());
  return result;
}

static std::vector<int8_t> table_reference(const std::vector<int8_t>& input,
                                          const Table& table) {
  const int maximum=*std::max_element(input.begin(),input.end());
  int32_t sum=0;
  for (int x:input) sum+=gemmlowp::Rescale<12>(
      gemmlowp::FixedPoint<int32_t,0>::FromRaw(table[maximum-x])).raw();
  int above_unit=0;
  const int32_t reciprocal=tflite::GetReciprocal(sum,12,&above_unit);
  std::vector<int8_t> result;
  for (int x:input) {
    const int64_t rounded=gemmlowp::RoundingDivideByPOTInt64(
        static_cast<int64_t>(reciprocal)*table[maximum-x],54+above_unit);
    result.push_back(static_cast<int8_t>(std::clamp<int64_t>(rounded-128,-128,127)));
  }
  return result;
}

class Simulation {
 public:
  Vvector_softmax_test dut;
  std::array<int8_t,256> input{},output{};
  std::array<int32_t,256> exponent{};
  const Table* table=nullptr;
  std::mt19937 bus_random{0x534d5831};
  int pending=-1,delay=0,requests=0,writes=0,fail_request=-1;
  bool pending_error=false;

  void tick() {
    dut.clk=0;
    dut.input_data=static_cast<uint8_t>(input[dut.input_index]);
    dut.exp_rdata=static_cast<uint32_t>(exponent[dut.exp_index]);
    dut.lut_req_ready=(bus_random()%4)!=0;
    dut.lut_rsp_valid=pending>=0 && delay==0;
    dut.lut_rsp_data=pending>=0 ? static_cast<uint32_t>((*table)[pending]) : 0;
    dut.lut_rsp_error=pending_error;
    dut.eval();
    // Index outputs are combinational functions of registered state.
    dut.input_data=static_cast<uint8_t>(input[dut.input_index]);
    dut.exp_rdata=static_cast<uint32_t>(exponent[dut.exp_index]);
    dut.eval();
    const bool accepted=dut.lut_req_valid && dut.lut_req_ready;
    const int address=dut.lut_index;
    if (dut.exp_we) exponent[dut.exp_index]=static_cast<int32_t>(dut.exp_wdata);
    if (dut.out_we) {
      if (dut.out_index!=writes) throw std::runtime_error("output order");
      output[dut.out_index]=static_cast<int8_t>(dut.out_data);++writes;
    }
    const bool responded=dut.lut_rsp_valid;
    dut.clk=1;dut.eval();++cycle_count;
    if (responded) pending=-1;
    else if (pending>=0) --delay;
    if (accepted) {
      if (pending>=0) throw std::runtime_error("multiple outstanding table reads");
      pending=address;delay=bus_random()%6;
      pending_error=requests==fail_request;
      ++requests;++request_count;
    }
  }

  Simulation() {
    dut.rst_n=0;dut.start=0;dut.depth=0;tick();tick();
    dut.rst_n=1;tick();
  }

  void run(const std::vector<int8_t>& values,const Table& lut,
           const std::vector<int8_t>& expected,const std::string& name,
           int expected_error=0,int fail_at=-1) {
    if (!dut.ready) throw std::runtime_error("core not ready");
    table=&lut;input.fill(0);exponent.fill(0x34343434);output.fill(77);
    std::copy(values.begin(),values.end(),input.begin());
    pending=-1;requests=0;writes=0;fail_request=fail_at;pending_error=false;
    dut.depth=values.size();dut.start=1;tick();dut.start=0;
    for (unsigned cycles=0;!dut.done;cycles++) {
      if (cycles>100000) throw std::runtime_error(name+": timeout");
      tick();
    }
    if (dut.error!=expected_error)
      throw std::runtime_error(name+": device error "+std::to_string(dut.error));
    if (!expected_error) {
      if (writes!=static_cast<int>(values.size()) || requests!=writes)
        throw std::runtime_error(name+": transfer count");
      for (unsigned i=0;i<values.size();++i) {
        if (output[i]!=expected[i])
          throw std::runtime_error(name+": element "+std::to_string(i)+
              " expected "+std::to_string(expected[i])+" actual "+std::to_string(output[i]));
      }
      element_count+=values.size();
    } else if (writes) throw std::runtime_error(name+": output changed on failed operation");
    ++case_count;tick();
    if (!dut.ready) throw std::runtime_error(name+": completion recovery");
  }
};

static void run_quantized(Simulation& sim,const std::vector<int8_t>& input,
                          const tflite::SoftmaxParams& p,const std::string& name) {
  Table table{};tflite::PopulateSoftmaxVceTable(p,table.data());
  const auto expected=reference(input,p);
  if (table_reference(input,table)!=expected) throw std::runtime_error(name+": prepared table equivalence");
  sim.run(input,table,expected,name);
}

static unsigned replay(Simulation& sim,const std::string& path,const std::string& binary_path) {
  if (path.empty()) return 0;
  std::ifstream stream(path);unsigned cases=0;
  std::ofstream binary;
  if (!binary_path.empty()) binary.open(binary_path,std::ios::binary);
  auto word=[&](uint32_t value) {
    const uint8_t bytes[]={uint8_t(value),uint8_t(value>>8),uint8_t(value>>16),uint8_t(value>>24)};
    binary.write(reinterpret_cast<const char*>(bytes),4);
  };
  if (binary.is_open()) {binary.write("VCESMX1\0",8);word(0);}
  std::string label;
  while (stream>>label) {
    tflite::SoftmaxParams p={};unsigned n;
    stream>>p.input_multiplier>>p.input_left_shift>>p.diff_min>>n;
    std::vector<int8_t> input(n),golden(n);
    for (auto& x:input) {int v;stream>>v;x=v;}
    for (auto& x:golden) {int v;stream>>v;x=v;}
    if (!stream || n>TEST_MAX_DEPTH) throw std::runtime_error("replay format or capacity");
    if (reference(input,p)!=golden) throw std::runtime_error(label+": stored reference differs");
    Table table{};tflite::PopulateSoftmaxVceTable(p,table.data());
    sim.run(input,table,golden,label);++cases;
    if (binary.is_open()) {
      word(label.size());binary.write(label.data(),label.size());word(n);
      for (int32_t value:table) word(static_cast<uint32_t>(value));
      binary.write(reinterpret_cast<const char*>(input.data()),n);
      binary.write(reinterpret_cast<const char*>(golden.data()),n);
    }
  }
  if (binary.is_open()) {binary.seekp(8);word(cases);if (!binary) throw std::runtime_error("replay export failed");}
  return cases;
}

int main(int argc,char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Simulation sim;
    const double scales[]={1.0/1048576,1.0/1024,1.0/256,1.0/16,0.25,1,8,32,100};
    for (unsigned depth=1;depth<=TEST_MAX_DEPTH;depth++) {
      for (double scale:scales) {
        const auto p=parameters(scale);
        for (int value:{-128,-1,0,1,127})
          run_quantized(sim,std::vector<int8_t>(depth,value),p,"equal");
        for (unsigned trial=0;trial<40;trial++) {
          std::vector<int8_t> input(depth);
          for (auto& x:input) x=static_cast<int8_t>(random_values());
          run_quantized(sim,input,p,"random");
        }
      }
    }
    // Exercise every signed input difference and both sides of each cutoff.
    for (double scale:scales) {
      auto p=parameters(scale);
      for (int diff=0;diff<=255;diff++) {
        run_quantized(sim,{127,static_cast<int8_t>(127-diff)},p,"difference");
        auto clipped=p;clipped.diff_min=std::max(p.diff_min,-diff+1);
        if (clipped.diff_min<=0) run_quantized(sim,{127,static_cast<int8_t>(127-diff)},clipped,"cutoff");
      }
    }
    // Exact half-integer accumulation values alternate even and odd quotients.
    Table tie_table{};tie_table[0]=INT32_MAX;
    for (unsigned i=1;i<256;i++) tie_table[i]=static_cast<int32_t>((i*2047u<<12)+2048u);
    for (unsigned depth=2;depth<=TEST_MAX_DEPTH;depth++) {
      for (unsigned trial=0;trial<40;trial++) {
        std::vector<int8_t> input(depth);input[0]=127;
        for (unsigned i=1;i<depth;i++) input[i]=static_cast<int8_t>(random_values());
        sim.run(input,tie_table,table_reference(input,tie_table),"accumulation_ties");
      }
    }
    const auto p=parameters(0.125);Table table{};
    tflite::PopulateSoftmaxVceTable(p,table.data());
    sim.run({},table,{},"zero_depth",1);
    sim.run(std::vector<int8_t>(TEST_MAX_DEPTH+1,0),table,{},"excess_depth",1);
    sim.run({1,2,3},table,{},"read_error",2,1);
    Table negative=table;negative[0]=INT32_MIN;
    sim.run({1,1},negative,{},"negative_exponential",2);
    Table zero{};sim.run({1,2},zero,{},"zero_sum",1);
    run_quantized(sim,{1,2,3},p,"recovery");
    const unsigned model_cases=replay(sim,argc>1?argv[1]:"",argc>2?argv[2]:"");
    std::cout<<"{\"passed\":true,\"maximum_depth\":"<<TEST_MAX_DEPTH
             <<",\"cases\":"<<case_count<<",\"elements\":"<<element_count
             <<",\"cycles\":"<<cycle_count<<",\"lut_requests\":"<<request_count
             <<",\"model_cases\":"<<model_cases<<"}\n";
    return 0;
  } catch (const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
