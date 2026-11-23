#include "Vps_raw_store_tb.h"
#include "verilated.h"
#include <array>
#include <vector>
#include <random>
#include <iostream>
#include <stdexcept>
using Row=std::array<uint32_t,16>;
Vps_raw_store_tb d;
std::array<std::array<uint32_t,4>,1024> mem{};
std::vector<Row> replay;
uint64_t cycles=0,values=0,commands=0,cancellations=0;
unsigned banks=4;
void require(bool c,const char* text){if(!c)throw std::runtime_error(text);}
void tick(){
 d.clk=0;d.eval();
 if(d.rst_n&&d.replay_valid){Row row;for(int i=0;i<16;i++)row[i]=d.replay_data[i];replay.push_back(row);}
 std::array<std::array<uint32_t,4>,4> incoming{};
 for(int p=0;p<4;p++)if((d.ram_read_en>>p)&1){
  unsigned a=(d.read_addresses>>(10*p))&1023;
  require(a<banks*128,"read outside allocated banks");incoming[p]=mem[a];
  for(int w=0;w<4;w++)if((d.ram_write_en>>w)&1)
   require(a!=((d.write_addresses>>(10*w))&1023),"read/write collision");
 }
 for(int p=0;p<4;p++)if((d.ram_write_en>>p)&1){
  unsigned a=(d.write_addresses>>(10*p))&1023;
  require(a<banks*128,"write outside allocated banks");
  for(int w=0;w<4;w++)mem[a][w]=d.ram_write_packet[p*4+w];
 }
 d.clk=1;d.eval();
 for(int p=0;p<4;p++)for(int w=0;w<4;w++)d.ram_read_packet[p*4+w]=incoming[p][w];
 d.eval();++cycles;
 if(d.rst_n)require(!d.capacity_fault,"RAW32 capacity fault");
}
template<class F>void wait(F f){for(int n=0;n<1000&&!f();n++)tick();require(f(),"timeout");}
void command(unsigned id,const std::vector<Row>& old,const std::vector<Row>& next,bool final){
 replay.clear();d.frame_id=id;d.frame_rows=old.empty()?next.size():old.size();d.frame_init=old.empty();d.frame_final=final;d.frame_request=1;
 if ((commands & 1)==0) {
  for (unsigned n=0;n<1+(commands%7);n++) tick();
  d.frame_request=0;tick();tick();tick();
  require(!d.frame_ready && !d.frame_pressure,"cancelled request remained ready or pressured");
  require(replay.empty(),"cancelled request emitted replay data");
  require(!d.ram_write_en,"cancelled request wrote committed storage");
  ++cancellations;d.frame_request=1;
 }
 wait([]{return d.frame_ready;});d.frame_accept=1;tick();d.frame_accept=0;d.frame_request=0;
 if(!old.empty()){d.replay_trigger=1;tick();d.replay_trigger=0;wait([&]{return replay.size()==old.size();});
  require(replay==old,"RAW32 replay value mismatch");values+=old.size()*16;}
 if(!final)for(const Row& row:next){for(int i=0;i<16;i++)d.write_data[i]=row[i];d.write_valid=1;tick();}
 d.write_valid=0;d.write_frame_end=1;tick();d.write_frame_end=0;
 wait([]{return d.frame_complete;});tick();++commands;
}
int main(int argc,char**argv){try{
 Verilated::commandArgs(argc,argv);std::mt19937 rng(0x734321);
 for(banks=4;banks<=8;banks++){
  d.rst_n=0;tick();tick();d.rst_n=1;d.cfg_pool_bank_count=banks;d.cfg_valid=1;tick();d.cfg_valid=0;tick();tick();
  std::array<std::vector<Row>,4> saved;
  if(argc>1 && std::string(argv[1])=="large"){
   unsigned rows=banks*128/4;
   std::vector<Row> first(rows),next(rows);
   for(Row&r:first)for(uint32_t&v:r)v=rng();
   for(Row&r:next)for(uint32_t&v:r)v=rng();
   command(0,{},first,false);command(0,first,next,false);command(0,next,{},true);
   continue;
  }
  for(int n=0;n<160;n++){
   unsigned id=rng()%4;bool final=!saved[id].empty()&&n%4==0;
   unsigned rows=saved[id].empty()?1+rng()%16:saved[id].size();std::vector<Row> next(rows);
   for(Row&r:next)for(uint32_t&v:r)v=rng();
   command(id,saved[id],next,final);saved[id]=final?std::vector<Row>{}:next;
  }
  for(unsigned id=0;id<4;id++)if(!saved[id].empty())command(id,saved[id],{},true);
 }
 std::cout<<"RAW_STORE_PASS commands="<<commands<<" int32_values="<<values<<" cancellations="<<cancellations<<" cycles="<<cycles<<"\n";
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;} }
