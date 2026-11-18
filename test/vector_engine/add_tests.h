// SPDX-License-Identifier: Apache-2.0
#ifndef VECTOR_ENGINE_ADD_TESTS_H
#define VECTOR_ENGINE_ADD_TESTS_H
#include "reference_add.h"
#include <fstream>

static unsigned add_cases=0;
static uint64_t add_outputs=0;

static Config add_config(const vector_add_reference_params&p,uint32_t length){
 auto c=config(9);c[1]=length;c[2]=0x1ffd;c[3]=0x20fff;c[4]=0x60fff;
 c[8]=uint32_t(p.output_offset);c[9]=uint32_t(p.activation_min);c[10]=uint32_t(p.activation_max);
 c[26]=uint32_t(p.input1_offset);c[27]=uint32_t(p.input2_offset);
 c[28]=uint32_t(p.input1_multiplier);c[29]=uint32_t(p.input1_shift);
 c[30]=uint32_t(p.input2_multiplier);c[31]=uint32_t(p.input2_shift);
 c[32]=uint32_t(p.left_shift);c[33]=uint32_t(p.output_multiplier);c[34]=uint32_t(p.output_shift);
 return c;
}

static Result add_case(Sim&s,const std::string&name,const vector_add_reference_params&p,
 const std::vector<int8_t>&a,const std::vector<int8_t>&b,unsigned alignment=0,
 const std::vector<int8_t>*recorded=nullptr){
 require(!a.empty()&&a.size()==b.size(),"invalid Add tensors");
 auto c=add_config(p,uint32_t(a.size()));
 c[2]=0x1ffc+(alignment&3);c[3]=0x20ffc+((alignment>>2)&3);c[4]=0x60ffc+((alignment>>4)&3);
 std::vector<int8_t>gold(a.size());
 require(vector_add_reference(&p,uint32_t(a.size()),a.data(),b.data(),gold.data())==0,"independent Add reference rejected parameters");
 if(recorded)require(gold==*recorded,"recorded Add tensor differs from independent reference");
 s.put(c[2],a);s.put(c[3],b);
 std::fill(s.mem.begin()+c[4]-16,s.mem.begin()+c[4]+gold.size()+16,0xa5);auto expected=s.mem;
 std::memcpy(expected.data()+c[4],gold.data(),gold.size());
 s.ranges={{c[2],uint32_t(a.size())},{c[3],uint32_t(b.size())}};s.output_base=c[4];s.output_size=gold.size();
 auto r=s.execute(c);
 if(s.mem!=expected)for(size_t i=0;i<s.mem.size();i++)if(s.mem[i]!=expected[i])
   throw std::runtime_error(name+" mismatch at "+std::to_string(i)+" got "+std::to_string(int8_t(s.mem[i]))+" expected "+std::to_string(int8_t(expected[i])));
 require(r.writes==a.size()&&r.reads>=2*a.size(),"Add DMA byte count");
 require(s.top.pe_count>0&&r.compute==17*a.size(),"Add compute-cycle count");
 report(name.c_str(),r);cases++;outputs+=a.size();add_cases++;add_outputs+=a.size();return r;
}

static std::array<vector_add_reference_params,3> resnet_add_params(){
 return {{{128,-4,1623821475,-2,1073741824,0,20,1098017566,-17,-128,-128,127},
          {17,-4,1699529983,-2,1073741824,0,20,1140768826,-17,-128,-128,127},
          {-38,2,1657902019,-2,1073741824,0,20,1835721671,-18,-128,-128,127}}};
}

static void add_random_case(Sim&s,const std::string&name,const vector_add_reference_params&p,
 uint32_t length,unsigned alignment,int pattern=0){
 std::vector<int8_t>a(length),b(length);
 for(uint32_t i=0;i<length;i++){
   a[i]=int8_t(int(s.rng()%256)-128);b[i]=int8_t(int(s.rng()%256)-128);
   if(pattern==1){a[i]=(i&1)?-128:127;b[i]=a[i];}
   if(pattern==2){a[i]=int8_t(int(i%255)-127);b[i]=int8_t(-a[i]);}
 }
 add_case(s,name,p,a,b,alignment);
}

static void add_functional(Sim&s){
 auto models=resnet_add_params();unsigned alignment=0;
 for(unsigned n:{1u,3u,7u,8u,15u,16u,17u,31u,32u,33u,65u})
   add_random_case(s,"add_tail_"+std::to_string(n),models[n%3],n,alignment++);
 for(unsigned i=0;i<64;i++)add_random_case(s,"add_alignment_"+std::to_string(i),models[i%3],17,i);
 vector_add_reference_params p{0,0,0x40000000,0,0x40000000,0,0,0x40000000,0,0,-128,127};
 std::vector<int8_t>a(65536),b(65536);
 for(unsigned i=0;i<65536;i++){a[i]=int8_t(int(i>>8)-128);b[i]=int8_t(int(i&255)-128);}
 add_case(s,"add_exhaustive_ties",p,a,b,63);
 p={-127,128,INT32_MAX,-1,0x40000001,-2,2,0x60000001,-1,7,-43,79};
 add_case(s,"add_exhaustive_offsets",p,a,b,27);
 unsigned index=0;
 for(int left:{0,20,22})for(int shift:{-31,0,30})for(int offset:{-128,0,127}){
   p={-127,128,INT32_MAX,0,INT32_MAX,0,left,INT32_MAX,shift,offset,-128,127};
   add_random_case(s,"add_bounds_"+std::to_string(index),p,33,(index*7)%64,1);index++;
 }
 p={0,0,INT32_MAX,0,INT32_MAX,0,22,INT32_MAX,0,0,-128,127};
 add_random_case(s,"add_cancellation",p,65,39,2);
 p={0,0,INT32_MAX,-31,INT32_MAX,-31,0,INT32_MAX,30,0,-128,127};
 add_random_case(s,"add_smallest_inputs",p,33,49);
 p={128,-127,0,0,0,0,22,INT32_MAX,30,127,-128,127};
 add_random_case(s,"add_zero_inputs",p,17,13);
 p={128,128,INT32_MAX,0,INT32_MAX,0,22,INT32_MAX,30,127,-128,127};
 add_random_case(s,"add_positive_saturation",p,33,61,1);
 p={-127,-127,INT32_MAX,0,INT32_MAX,0,22,INT32_MAX,30,-128,-128,127};
 add_random_case(s,"add_negative_saturation",p,33,26,1);
 p={0,0,0x40000000,0,0x40000000,0,20,0,-31,-19,-7,3};
 add_random_case(s,"add_zero_output_multiplier",p,17,47);
 for(unsigned i=0;i<32;i++){
   p={int(s.rng()%256)-127,int(s.rng()%256)-127,int32_t(s.rng()&INT32_MAX),-int(s.rng()%32),
      int32_t(s.rng()&INT32_MAX),-int(s.rng()%32),int(s.rng()%23),
      int32_t(s.rng()&INT32_MAX),int(s.rng()%62)-31,int(s.rng()%256)-128,-128,127};
   add_random_case(s,"add_random_"+std::to_string(i),p,1+s.rng()%129,s.rng()%64);
 }
}

static void add_invalid(Sim&s){
 const auto p=resnet_add_params()[0];auto base=add_config(p,17);std::vector<Config>tests;
 auto change=[&](unsigned word,int32_t value){auto c=base;c[word]=uint32_t(value);tests.push_back(c);};
 change(1,0);change(0,9|256);change(26,-128);change(26,129);change(27,-128);change(27,129);
 change(28,-1);change(30,-1);change(33,-1);change(29,-32);change(29,1);change(31,-32);change(31,1);
 change(32,-1);change(32,23);change(34,-32);change(34,31);change(8,-129);change(8,128);
 change(9,-129);change(10,128);change(9,128);change(4,int32_t(base[2]));change(4,int32_t(base[3]));
 change(2,-8);change(3,-8);change(4,-8);
 for(unsigned i=0;i<tests.size();i++){
   auto expected=s.mem;auto r=s.execute(tests[i],1);
   require(r.reads==0&&r.writes==0&&s.mem==expected,"invalid Add touched memory");
   report(("add_invalid_"+std::to_string(i)).c_str(),r);cases++;
 }
 add_random_case(s,"add_invalid_recovery",p,17,43);
 auto c=base;std::vector<int8_t>a(17,11),b(17,-9),gold(17);
 s.put(c[2],a);s.put(c[3],b);s.ranges={{c[2],17},{c[3],17}};s.output_base=c[4];s.output_size=17;
 s.read_fault=true;s.fault_addr=c[3]+3;auto before=s.mem;auto r=s.execute(c,2);
 require(s.fault_used&&r.writes==0&&s.mem==before,"Add read-error handling");s.read_fault=false;report("add_read_error",r);cases++;
 require(vector_add_reference(&p,17,a.data(),b.data(),gold.data())==0,"Add recovery reference");
 r=s.execute(c);require(std::memcmp(gold.data(),s.mem.data()+c[4],gold.size())==0,"Add read-error recovery");report("add_read_error_recovery",r);cases++;
 s.write_fault=true;r=s.execute(c,2);require(s.fault_used,"Add write-error injection");s.write_fault=false;report("add_write_error",r);cases++;
 r=s.execute(c);require(std::memcmp(gold.data(),s.mem.data()+c[4],gold.size())==0,"Add write-error recovery");report("add_write_error_recovery",r);cases++;
}

static void add_replay(Sim&s,const std::string&path){
 std::ifstream file(path,std::ios::binary);require(bool(file),"cannot read Add replay file");
 auto read=[&](void*dst,size_t n){file.read(static_cast<char*>(dst),std::streamsize(n));require(bool(file),"truncated Add replay file");};
 auto word=[&](){std::array<uint8_t,4>b{};read(b.data(),4);return uint32_t(b[0])|uint32_t(b[1])<<8|uint32_t(b[2])<<16|uint32_t(b[3])<<24;};
 std::array<char,8>magic{};read(magic.data(),8);require(std::memcmp(magic.data(),"VCEADD1\0",8)==0,"invalid Add replay format");
 auto count=word();require(count>0&&count<1000,"invalid Add replay count");
 for(uint32_t i=0;i<count;i++){
   const auto chars=word();require(chars>0&&chars<256,"invalid Add replay name");std::string name(chars,' ');read(name.data(),chars);
   const auto n=word();require(n>0&&n<=65536,"invalid Add replay size");std::array<int32_t,12>v{};for(auto&x:v)x=int32_t(word());
   vector_add_reference_params p{v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]};
   std::vector<int8_t>a(n),b(n),gold(n);read(a.data(),n);read(b.data(),n);read(gold.data(),n);
   add_case(s,name,p,a,b,(i*13+31)%64,&gold);
 }
 require(file.peek()==std::char_traits<char>::eof(),"trailing Add replay data");
}
#endif
