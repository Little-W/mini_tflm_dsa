// SPDX-License-Identifier: Apache-2.0
// 固定输入序列分别运行两种配置有效表达式，记录全部公开握手与有效载荷。
#include "Vvector_offer_system_top.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

using Config=std::array<uint32_t,40>;
struct Transfer {uint32_t address,remaining,size;};
static void check(bool value,const std::string &message) {
    if (!value) throw std::runtime_error(message);
}
class Simulator {
public:
    Vvector_offer_system_top top;
    std::vector<uint8_t> memory=std::vector<uint8_t>(1<<20,0);
    std::deque<Transfer> reads,writes;
    unsigned responses=0,tasks=0,checks=0;
    bool read_hold=false,response_hold=false,inject=false,injected=false;
    uint64_t cycles=0,hash=1469598103934665603ULL;
    FILE *trace=nullptr;
    std::mt19937 random{20261120};
    void add(uint64_t value) {
        hash=(hash^value)*1099511628211ULL;
        if (trace) check(std::fwrite(&value,sizeof(value),1,trace)==1,"写入公开输出记录");
    }
    void tick() {
        top.clk=0;
        top.m_axi_arready=reads.size()<4 && random()%5!=0;
        top.m_axi_awready=writes.size()<4 && random()%5!=0;
        top.m_axi_wready=!writes.empty() && random()%4!=0;
        if (!read_hold && !reads.empty() && random()%7<4) {
            const auto &read=reads.front();uint64_t word=0;
            for (unsigned i=0;i<read.size;i++) word|=uint64_t(memory.at(read.address+i))<<(((read.address+i)&7)*8);
            top.m_axi_rdata=word;top.m_axi_rlast=read.remaining==1;top.m_axi_rresp=0;
            if (inject&&!injected) {top.m_axi_rresp=2;injected=true;}
            read_hold=true;
        }
        top.m_axi_rvalid=read_hold;
        if (!response_hold && responses && random()%4!=0) {response_hold=true;top.m_axi_bresp=0;}
        top.m_axi_bvalid=response_hold;
        top.eval();
        add(top.ready);add(top.done_valid);add(top.error);
        add(top.m_axi_arvalid);add(top.m_axi_rready);add(top.m_axi_awvalid);
        add(top.m_axi_wvalid);add(top.m_axi_bready);
        if (top.m_axi_arvalid) {add(top.m_axi_araddr);add(top.m_axi_arlen);add(top.m_axi_arsize);add(top.m_axi_arburst);}
        if (top.m_axi_awvalid) {add(top.m_axi_awaddr);add(top.m_axi_awlen);add(top.m_axi_awsize);add(top.m_axi_awburst);}
        if (top.m_axi_wvalid) {add(top.m_axi_wdata);add(top.m_axi_wstrb);add(top.m_axi_wlast);}
        if (top.m_axi_rvalid&&top.m_axi_rready) {
            auto &read=reads.front();read.address+=read.size;
            if (--read.remaining==0) reads.pop_front();read_hold=false;
        }
        if (top.m_axi_bvalid&&top.m_axi_bready) {responses--;response_hold=false;}
        if (top.m_axi_arvalid&&top.m_axi_arready) {
            check(top.m_axi_arburst==1 && top.m_axi_arsize<=3,"AXI 读取参数");
            reads.push_back({top.m_axi_araddr,uint32_t(top.m_axi_arlen)+1,uint32_t(1)<<top.m_axi_arsize});
        }
        if (top.m_axi_awvalid&&top.m_axi_awready) {
            check(top.m_axi_awburst==1 && top.m_axi_awsize==3,"AXI 写入参数");
            writes.push_back({top.m_axi_awaddr,uint32_t(top.m_axi_awlen)+1,8});
        }
        if (top.m_axi_wvalid&&top.m_axi_wready) {
            check(!writes.empty(),"写入地址已经接受");auto &write=writes.front();
            check(bool(top.m_axi_wlast)==(write.remaining==1),"写入结束标志");
            for (unsigned lane=0;lane<8;lane++) if (top.m_axi_wstrb&(1<<lane))
                memory.at(write.address+lane)=uint8_t(top.m_axi_wdata>>(lane*8));
            write.address+=8;if (--write.remaining==0) {writes.pop_front();responses++;}
        }
        top.clk=1;top.eval();Verilated::timeInc(1);cycles++;top.clk=0;top.eval();
    }
    explicit Simulator(bool offer,const std::string &trace_path) {
        if (!trace_path.empty()) {trace=std::fopen(trace_path.c_str(),"wb");check(trace!=nullptr,"打开公开输出记录");}
        top.offer_enable=offer;top.rst_n=0;top.start=0;top.done_ready=0;top.is_vector=0;
        for (int i=0;i<40;i++) top.config_words[i]=0;
        for (int i=0;i<4;i++) tick();top.rst_n=1;tick();
    }
    ~Simulator() {if(trace) std::fclose(trace);}
    void put32(uint32_t address,int32_t value) {
        for (unsigned b=0;b<4;b++) memory.at(address+b)=uint8_t(uint32_t(value)>>(8*b));
    }
    void execute(const std::string &name,const Config &cfg,bool vector,unsigned expected_error=0) {
        const auto deadline=cycles+300000;
        while (!top.ready && cycles<deadline) tick();check(top.ready,"任务开始前就绪");
        for (int i=0;i<40;i++) top.config_words[i]=cfg[i];
        top.is_vector=vector;top.start=1;tick();top.start=0;const auto started=cycles;
        while (!top.done_valid && cycles<deadline) tick();
        check(top.done_valid,"任务完成: "+name);
        check(top.error==expected_error,"任务错误码: "+name+" actual="+std::to_string(top.error));
        for (unsigned i=0;i<3;i++) {tick();check(top.done_valid,"完成保持");}
        std::printf("TASK %s cycles=%llu error=%u\n",name.c_str(),
                    (unsigned long long)(cycles-started),unsigned(top.error));
        top.done_ready=1;tick();top.done_ready=0;tick();tasks++;
    }
    Config base(unsigned op=4) {
        Config cfg{};cfg[0]=op;cfg[2]=0x1000;cfg[3]=0x20000;cfg[4]=0x60000;
        cfg[5]=0x30000;cfg[6]=0x31000;cfg[7]=0x32000;
        cfg[9]=uint32_t(-128);cfg[10]=127;cfg[18]=cfg[19]=cfg[20]=cfg[21]=1;
        cfg[36]=cfg[37]=1;cfg[38]=cfg[39]=0x10001;return cfg;
    }
    void vector_sum(unsigned length,bool wide,bool fault=false) {
        auto cfg=base();cfg[0]|=wide?256:0;cfg[1]=length;
        int32_t expected=0;
        for (unsigned i=0;i<length;i++) {
            int value=int(i%7)-3;expected+=value;
            if (wide) {value*=17;expected+=value-(int(i%7)-3);memory[cfg[2]+2*i]=uint8_t(value);memory[cfg[2]+2*i+1]=uint8_t(value>>8);}
            else memory[cfg[2]+i]=uint8_t(value);
        }
        inject=fault;injected=false;
        execute("vector_sum_"+std::to_string(length)+(wide?"_s16":"_s8")+(fault?"_error":""),cfg,true,fault?3:0);
        inject=false;
        if (!fault) for (unsigned b=0;b<4;b++) {check(memory[cfg[4]+b]==uint8_t(uint32_t(expected)>>(8*b)),"向量和数值");checks++;}
        else check(injected,"读取错误已注入");
    }
    void matrix(unsigned rows,unsigned reduction,unsigned cols,bool per_channel,bool frame) {
        auto cfg=base(0);cfg[11]=rows;cfg[12]=reduction;cfg[13]=cols;cfg[35]=per_channel;
        if (frame) cfg[37]=3;
        const unsigned row_tiles=(rows+15)/16,col_tiles=(cols+15)/16;
        cfg[38]=((col_tiles+cfg[37]-1)/cfg[37]<<16)|((row_tiles+cfg[36]-1)/cfg[36]);
        cfg[39]=(((col_tiles-1)%cfg[37]+1)<<16)|((row_tiles-1)%cfg[36]+1);
        std::fill(memory.begin()+cfg[2],memory.begin()+cfg[2]+rows*reduction,1);
        std::fill(memory.begin()+cfg[3],memory.begin()+cfg[3]+cols*reduction,1);
        for (unsigned i=0;i<cols;i++) {put32(cfg[5]+4*i,0);put32(cfg[6]+4*i,0x40000000);put32(cfg[7]+4*i,0);}
        if (!per_channel) {cfg[6]=0x40000000;cfg[7]=0;}
        execute("matrix_"+std::to_string(rows)+"_"+std::to_string(reduction)+"_"+std::to_string(cols)+
                (per_channel?"_channel":"_tensor")+(frame?"_frame":""),cfg,false);
        for (unsigned i=0;i<rows*cols;i++) {check(memory[cfg[4]+i]==reduction/2,"矩阵数值");checks++;}
    }
    void pool(unsigned channels,bool depthwise) {
        auto cfg=base(depthwise?0:2);cfg[11]=5;cfg[12]=5;cfg[13]=channels;
        cfg[14]=cfg[15]=3;cfg[16]=cfg[17]=3;
        std::fill(memory.begin()+cfg[2],memory.begin()+cfg[2]+25*channels,4);
        if (depthwise) {
            std::fill(memory.begin()+cfg[3],memory.begin()+cfg[3]+9*channels,1);
            for (unsigned i=0;i<channels;i++) {put32(cfg[5]+4*i,0);put32(cfg[6]+4*i,0x40000000);put32(cfg[7]+4*i,0);}
        }
        execute((depthwise?"depthwise_":"pool_")+std::to_string(channels),cfg,true);
        for (unsigned i=0;i<9*channels;i++) {check(memory[cfg[4]+i]==(depthwise?18:4),"窗口算子数值");checks++;}
    }
};
int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);bool offer=false;std::string trace_path;
    for (int i=1;i<argc;i++) {
        if (std::string(argv[i])=="--offer") offer=true;
        if (std::string(argv[i]).rfind("+trace=",0)==0) trace_path=std::string(argv[i]).substr(7);
    }
    try {
        Simulator sim(offer,trace_path);
        sim.vector_sum(33,false);sim.matrix(16,16,16,false,false);sim.pool(7,false);
        sim.matrix(24,32,17,true,false);sim.vector_sum(37,true);sim.pool(19,true);
        sim.matrix(17,32,33,true,true);sim.vector_sum(17,false,true);
        sim.vector_sum(21,false);sim.matrix(8,16,9,true,false);sim.pool(16,false);
        auto bad=sim.base(15);bad[1]=3;sim.execute("vector_invalid",bad,true,1);
        sim.vector_sum(1,false);sim.matrix(16,16,16,false,false);sim.pool(3,true);
        check(sim.top.ordinary_clients_seen==15,"四类普通读取客户端均已参与测试");
        std::printf("VECTOR_CONFIGURATION_SYSTEM_PASS tasks=%u checks=%u cycles=%llu hash=%016llx configure=%u wait=%u ordinary=%u vector=%u clients=%u\n",
            sim.tasks,sim.checks,(unsigned long long)sim.cycles,(unsigned long long)sim.hash,
            unsigned(sim.top.configuration_cycles),unsigned(sim.top.configuration_wait_cycles),
            unsigned(sim.top.ordinary_request_cycles),unsigned(sim.top.vector_request_cycles),unsigned(sim.top.ordinary_clients_seen));
    } catch (const std::exception &exception) {
        std::fprintf(stderr,"%s\n",exception.what());return 1;
    }
    return 0;
}
