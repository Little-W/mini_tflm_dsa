// SPDX-License-Identifier: Apache-2.0
#ifndef VECTOR_ENGINE_SOFTMAX_TESTS_H
#define VECTOR_ENGINE_SOFTMAX_TESTS_H
#include <fstream>

static unsigned softmax_cases=0;
static uint64_t softmax_outputs=0;

static Config softmax_config(uint32_t depth,unsigned alignment=0) {
  auto c=config(10);c[1]=depth;
  c[2]=0x1ffc+(alignment&3);c[3]=0x20ffc;c[4]=0x60ffc+((alignment>>2)&3);
  for (unsigned i=5;i<c.size();i++) c[i]=0xa5a5a5a5;
  return c;
}

static Result softmax_case(Sim& s,const std::string& name,const std::vector<int8_t>& input,
    const std::vector<int32_t>& table,const std::vector<int8_t>& golden,unsigned alignment=0) {
  require(!input.empty() && input.size()==golden.size() && table.size()==256,"Softmax tensor size");
  auto c=softmax_config(input.size(),alignment);
  s.put(c[2],input);s.put(c[3],table);
  std::fill(s.mem.begin()+c[4]-16,s.mem.begin()+c[4]+golden.size()+16,0xa5);
  auto expected=s.mem;std::memcpy(expected.data()+c[4],golden.data(),golden.size());
  s.ranges={{c[2],uint32_t(input.size())},{c[3],1024}};
  s.output_base=c[4];s.output_size=golden.size();
  const auto r=s.execute(c);
  if(s.mem!=expected)for(size_t i=0;i<s.mem.size();i++)if(s.mem[i]!=expected[i])
    throw std::runtime_error(name+" mismatch at "+std::to_string(i)+" got "+
        std::to_string(int8_t(s.mem[i]))+" expected "+std::to_string(int8_t(expected[i])));
  require(r.writes==golden.size() && r.reads>=input.size(),"Softmax transfer size");
  report(name.c_str(),r);++cases;outputs+=golden.size();++softmax_cases;softmax_outputs+=golden.size();return r;
}

static void softmax_functional(Sim& s,unsigned maximum_depth=16) {
  std::vector<int32_t> table(256,0);table[0]=INT32_MAX;
  for(unsigned depth=1;depth<=maximum_depth;depth++) {
    for(unsigned alignment=0;alignment<16;alignment++) {
      std::vector<int8_t> input(depth,-128),golden(depth,-128);
      const unsigned maxima=1+alignment%depth;
      for(unsigned i=0;i<maxima;i++) input[i]=127;
      const unsigned q=256/maxima,r=256%maxima;
      const int rounded=int(q+(r>maxima-r || (r==maxima-r && (q&1))));
      for(unsigned i=0;i<maxima;i++) golden[i]=int8_t(std::min(255,rounded)-128);
      softmax_case(s,"softmax_depth_"+std::to_string(depth)+"_alignment_"+
          std::to_string(alignment),input,table,golden,alignment);
    }
  }
}

static void softmax_invalid(Sim& s,unsigned maximum_depth=16) {
  const auto base=softmax_config(3,15);std::vector<Config> tests;
  auto change=[&](unsigned index,uint32_t value){auto c=base;c[index]=value;tests.push_back(c);};
  change(1,0);change(1,maximum_depth+1);change(0,10|256);
  change(3,base[3]+1);change(3,0xfffffc00);change(2,0xfffffffe);change(4,0xfffffffe);
  change(4,base[2]);change(4,base[3]+1023);
  for(unsigned i=0;i<tests.size();i++) {
    auto expected=s.mem;const auto r=s.execute(tests[i],1);
    require(r.reads==0 && r.writes==0 && s.mem==expected,"invalid Softmax touched memory");
    report(("softmax_invalid_"+std::to_string(i)).c_str(),r);++cases;++softmax_cases;
  }
  std::vector<int8_t> input{7,-128,6},golden{127,-128,-128};
  std::vector<int32_t> table(256,0);table[0]=INT32_MAX;
  auto c=base;s.put(c[2],input);s.put(c[3],table);
  s.ranges={{c[2],3},{c[3],1024}};s.output_base=c[4];s.output_size=3;
  for(unsigned kind=0;kind<2;kind++) {
    const auto before=s.mem;s.read_fault=true;s.fault_addr=kind?c[3]:c[2];
    const auto r=s.execute(c,2);
    require(s.fault_used && r.writes==0 && s.mem==before,"Softmax read failure changed output");
    s.read_fault=false;report(kind?"softmax_lut_read_error":"softmax_input_read_error",r);++cases;++softmax_cases;
    softmax_case(s,"softmax_read_recovery",input,table,golden,15);
  }
  s.write_fault=true;auto r=s.execute(c,2);require(s.fault_used,"Softmax write failure injection");
  s.write_fault=false;report("softmax_write_error",r);++cases;++softmax_cases;
  softmax_case(s,"softmax_write_recovery",input,table,golden,15);
  table[0]=INT32_MIN;s.put(c[3],table);auto before=s.mem;r=s.execute(c,2);
  require(r.writes==0 && s.mem==before,"negative Softmax table changed output");
  report("softmax_negative_table",r);++cases;++softmax_cases;
  table[0]=INT32_MAX;softmax_case(s,"softmax_table_recovery",input,table,golden,15);
}

static void softmax_replay(Sim& s,const std::string& path) {
  std::ifstream file(path,std::ios::binary);require(bool(file),"cannot open Softmax replay");
  auto read=[&](void* dst,size_t n){file.read(static_cast<char*>(dst),std::streamsize(n));require(bool(file),"truncated Softmax replay");};
  auto word=[&](){std::array<uint8_t,4>b{};read(b.data(),4);return uint32_t(b[0])|uint32_t(b[1])<<8|uint32_t(b[2])<<16|uint32_t(b[3])<<24;};
  std::array<char,8>magic{};read(magic.data(),8);require(std::memcmp(magic.data(),"VCESMX1\0",8)==0,"invalid Softmax replay format");
  const auto count=word();require(count>0 && count<1000,"invalid Softmax replay count");
  for(uint32_t i=0;i<count;i++) {
    const auto chars=word();require(chars>0 && chars<256,"invalid Softmax replay name");
    std::string name(chars,' ');read(name.data(),chars);
    const auto n=word();require(n>0 && n<=256,"invalid Softmax replay size");
    std::vector<int32_t>table(256);for(auto& x:table)x=int32_t(word());
    std::vector<int8_t>input(n),golden(n);read(input.data(),n);read(golden.data(),n);
    softmax_case(s,"softmax_replay_"+name,input,table,golden,(i*7)%16);
  }
  require(file.peek()==std::char_traits<char>::eof(),"trailing Softmax replay data");
}
#endif
