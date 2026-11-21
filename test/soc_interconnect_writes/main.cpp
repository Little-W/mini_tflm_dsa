#include "Vsoc_axi_interconnect.h"
#include "verilated.h"
#include "initialize.hpp"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <vector>

struct Request {
    uint32_t address;
    unsigned length, size, burst, target, aw_delay, w_delay;
};
struct Command {
    unsigned owner, index, beat;
    uint32_t address;
};
struct Response { unsigned owner, index, delay, code; };

static uint32_t random_state=0x72b95a13;
static uint32_t random_value() {
    random_state^=random_state<<13;random_state^=random_state>>17;
    random_state^=random_state<<5;return random_state;
}
static void require(bool value,const char *message) {
    if(!value)throw std::runtime_error(message);
}
static uint64_t data_value(unsigned owner,unsigned index,unsigned beat) {
    const uint64_t low=0x751af39dU^(index*0x9e3779b9U)^(beat*0x1f123bb5U)^(owner<<24);
    return low|((low^0xa5b36719U)<<32);
}
static unsigned strobe_value(unsigned owner,unsigned index,unsigned beat) {
    constexpr unsigned bus_bytes=TEST_DATA_WIDTH/8;
    const unsigned width=owner ? bus_bytes : 4;
    return (1U+index*37U+beat*13U)&((1U<<width)-1);
}
static uint32_t advance(uint32_t address,const Request &r) {
    const uint32_t step=1U<<r.size;
    return r.burst ? (address&~(step-1))+step : address;
}

int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    Vsoc_axi_interconnect dut;
    constexpr unsigned bytes=TEST_DATA_WIDTH/8;
    unsigned long cycles=0,completed=0,beats=0,stalls=0,concurrent=0,errors=0;
    try {
        for(unsigned epoch=0;epoch<4;++epoch) {
            initialize(dut);dut.rst_n=0;
            for(unsigned n=0;n<3;++n){dut.clk=0;dut.eval();dut.clk=1;dut.eval();++cycles;}
            dut.rst_n=1;
            std::array<std::vector<Request>,2> requests;
            for(unsigned index=0;index<512;++index) {
                const unsigned target=index%4;
                const uint32_t base=std::array<uint32_t,4>{0,0x10000000,0x02000000,0x20000000}[target];
                requests[0].push_back({base+(random_value()&0xffcU),
                    target ? 0U : random_value()%8, target ? 2U : random_value()%3,
                    unsigned(random_value()%4!=0),target,random_value()%6,random_value()%9});
                requests[1].push_back({0x10000U+(random_value()&0x7ff8U),random_value()%16,
                    bytes==8 ? 3U : 2U,unsigned(random_value()%4!=0),0,
                    random_value()%3,random_value()%6});
            }
            std::array<unsigned,2> sent_aw{},sent_w{},done{},word{};
            std::array<std::deque<Command>,4> commands;
            std::array<std::deque<Response>,4> responses;
            unsigned local_cycles=0;
            while(done[0]<512 || done[1]<512) {
                require(++local_cycles<300000,"写入事务超时");++cycles;
                dut.clk=0;dut.npu_bus_lock=(random_value()%31)==0;
                dut.s0_axi_bready=(random_value()%7)!=0;
                dut.s1_axi_bready=(random_value()%5)!=0;
                for(unsigned owner=0;owner<2;++owner) {
                    const bool aw_eligible=sent_aw[owner]<512 &&
                        sent_aw[owner]-done[owner]<(owner ? TEST_OUTSTANDING : 1);
                    bool awvalid=false,wvalid=false;
                    if(aw_eligible) {
                        auto &r=requests[owner][sent_aw[owner]];
                        if(r.aw_delay)--r.aw_delay;else awvalid=true;
                        if(owner){dut.s1_axi_awaddr=r.address;dut.s1_axi_awlen=r.length;
                            dut.s1_axi_awsize=r.size;dut.s1_axi_awburst=r.burst;}
                        else{dut.s0_axi_awaddr=r.address;dut.s0_axi_awlen=r.length;
                            dut.s0_axi_awsize=r.size;dut.s0_axi_awburst=r.burst;}
                    }
                    if(sent_w[owner]<512 && (owner || sent_w[owner]==done[owner])) {
                        auto &r=requests[owner][sent_w[owner]];
                        if(r.w_delay)--r.w_delay;else wvalid=true;
                        const auto data=data_value(owner,sent_w[owner],word[owner]);
                        const auto strobe=strobe_value(owner,sent_w[owner],word[owner]);
                        if(owner){dut.s1_axi_wdata=data;dut.s1_axi_wstrb=strobe;
                            dut.s1_axi_wlast=word[owner]==r.length;}
                        else{dut.s0_axi_wdata=uint32_t(data);dut.s0_axi_wstrb=strobe;
                            dut.s0_axi_wlast=word[owner]==r.length;}
                    }
                    if(owner){dut.s1_axi_awvalid=awvalid;dut.s1_axi_wvalid=wvalid;}
                    else{dut.s0_axi_awvalid=awvalid;dut.s0_axi_wvalid=wvalid;}
                }
                std::array<bool,4> aw_ready,w_ready,b_valid;
                for(unsigned target=0;target<4;++target) {
                    aw_ready[target]=commands[target].size()+responses[target].size()<
                        (target ? 1U : TEST_OUTSTANDING) && random_value()%4!=0;
                    w_ready[target]=!commands[target].empty() && random_value()%5!=0;
                    if(!responses[target].empty() && responses[target].front().delay)
                        --responses[target].front().delay;
                    b_valid[target]=!responses[target].empty() && !responses[target].front().delay;
                }
                dut.m_ram_awready=aw_ready[0];dut.m_npu_awready=aw_ready[1];
                dut.m_uart_awready=aw_ready[2];dut.m_ctrl_awready=aw_ready[3];
                dut.m_ram_wready=w_ready[0];dut.m_npu_wready=w_ready[1];
                dut.m_uart_wready=w_ready[2];dut.m_ctrl_wready=w_ready[3];
                dut.m_ram_bvalid=b_valid[0];dut.m_npu_bvalid=b_valid[1];
                dut.m_uart_bvalid=b_valid[2];dut.m_ctrl_bvalid=b_valid[3];
                dut.m_ram_bresp=b_valid[0]?responses[0].front().code:0;
                dut.m_npu_bresp=b_valid[1]?responses[1].front().code:0;
                dut.m_uart_bresp=b_valid[2]?responses[2].front().code:0;
                dut.m_ctrl_bresp=b_valid[3]?responses[3].front().code:0;
                dut.eval();
                // 空闲从设备允许地址和首拍同时到达，覆盖两种 CPU 写入配置。
                if(commands[0].empty() && dut.m_ram_awvalid && aw_ready[0])dut.m_ram_wready=random_value()%3!=0;
                if(commands[1].empty() && dut.m_npu_awvalid && aw_ready[1])dut.m_npu_wready=random_value()%3!=0;
                if(commands[2].empty() && dut.m_uart_awvalid && aw_ready[2])dut.m_uart_wready=random_value()%3!=0;
                if(commands[3].empty() && dut.m_ctrl_awvalid && aw_ready[3])dut.m_ctrl_wready=random_value()%3!=0;
                dut.eval();
                const std::array<bool,2> aw_fire={bool(dut.s0_axi_awvalid&&dut.s0_axi_awready),bool(dut.s1_axi_awvalid&&dut.s1_axi_awready)};
                const std::array<bool,2> w_fire={bool(dut.s0_axi_wvalid&&dut.s0_axi_wready),bool(dut.s1_axi_wvalid&&dut.s1_axi_wready)};
                const std::array<bool,4> slave_aw={bool(dut.m_ram_awvalid&&dut.m_ram_awready),bool(dut.m_npu_awvalid&&dut.m_npu_awready),bool(dut.m_uart_awvalid&&dut.m_uart_awready),bool(dut.m_ctrl_awvalid&&dut.m_ctrl_awready)};
                const std::array<uint32_t,4> addresses={dut.m_ram_awaddr,0x10000000U+dut.m_npu_awaddr,dut.m_uart_awaddr,dut.m_ctrl_awaddr};
                for(unsigned target=0;target<4;++target)if(slave_aw[target]) {
                    const unsigned owner=target==0 && aw_fire[1] ? 1 : 0;
                    require(aw_fire[owner],"从设备地址没有对应的主设备握手");
                    const auto &r=requests[owner][sent_aw[owner]];
                    require(r.target==target && r.address==addresses[target],"写入目标或地址错误");
                    if(target==0)require(dut.m_ram_awlen==r.length && dut.m_ram_awsize==r.size && dut.m_ram_awburst==r.burst,"RAM 突发属性错误");
                    commands[target].push_back({owner,sent_aw[owner],0,r.address});
                }
                const std::array<bool,4> slave_w={bool(dut.m_ram_wvalid&&dut.m_ram_wready),bool(dut.m_npu_wvalid&&dut.m_npu_wready),bool(dut.m_uart_wvalid&&dut.m_uart_wready),bool(dut.m_ctrl_wvalid&&dut.m_ctrl_wready)};
                const std::array<uint64_t,4> data={uint64_t(dut.m_ram_wdata),dut.m_npu_wdata,dut.m_uart_wdata,dut.m_ctrl_wdata};
                const std::array<unsigned,4> strobe={dut.m_ram_wstrb,dut.m_npu_wstrb,dut.m_uart_wstrb,dut.m_ctrl_wstrb};
                for(unsigned target=0;target<4;++target)if(slave_w[target]) {
                    require(!commands[target].empty(),"从设备没有已接收的写地址");
                    auto &c=commands[target].front();const auto &r=requests[c.owner][c.index];
                    require(w_fire[c.owner],"从设备数据没有对应的主设备握手");
                    const unsigned lane=target==0 && c.owner==0 ? (c.address&(bytes-1))&~3U : 0;
                    const uint64_t raw=data_value(c.owner,c.index,c.beat);
                    const uint64_t expected=c.owner ? (TEST_DATA_WIDTH==64?raw:uint32_t(raw)) : uint64_t(uint32_t(raw))<<(8*lane);
                    require(data[target]==expected,"写入数据或窄传输通道错误");
                    require(strobe[target]==(strobe_value(c.owner,c.index,c.beat)<<lane),"写入字节使能错误");
                    if(target==0)require(bool(dut.m_ram_wlast)==(c.beat==r.length),"RAM 末拍标志错误");
                    ++beats;
                    if(c.beat==r.length){responses[target].push_back({c.owner,c.index,random_value()%8,(c.index%7==0)?2U:0U});commands[target].pop_front();}
                    else{++c.beat;c.address=advance(c.address,r);}
                }
                const std::array<bool,4> slave_b_ready={bool(dut.m_ram_bready),bool(dut.m_npu_bready),bool(dut.m_uart_bready),bool(dut.m_ctrl_bready)};
                for(unsigned target=0;target<4;++target)if(b_valid[target]) {
                    const auto &b=responses[target].front();
                    const bool valid=b.owner ? dut.s1_axi_bvalid : dut.s0_axi_bvalid;
                    const unsigned code=b.owner ? dut.s1_axi_bresp : dut.s0_axi_bresp;
                    require(valid && code==b.code && done[b.owner]==b.index,"写响应内容或顺序错误");
                    if(slave_b_ready[target]){++done[b.owner];++completed;if(code)++errors;responses[target].pop_front();}
                    else ++stalls;
                }
                for(unsigned owner=0;owner<2;++owner) {
                    if(aw_fire[owner])++sent_aw[owner];
                    if(w_fire[owner]) {
                        auto &r=requests[owner][sent_w[owner]];
                        if(word[owner]==r.length){word[owner]=0;++sent_w[owner];}
                        else{++word[owner];r.w_delay=random_value()%3;}
                    }
                }
                if(sent_aw[0]>done[0] && sent_aw[1]>done[1])++concurrent;
                dut.clk=1;dut.eval();
            }
            for(unsigned target=0;target<4;++target)require(commands[target].empty()&&responses[target].empty(),"完成后仍有写入事务");
        }
        std::cout<<"INTERCONNECT_WRITES_PASS {\"passed\":true,\"data_width\":"<<TEST_DATA_WIDTH
            <<",\"write_overlap\":"<<TEST_WRITE_OVERLAP<<",\"outstanding\":"<<TEST_OUTSTANDING
            <<",\"transactions\":"<<completed<<",\"beats\":"<<beats<<",\"response_stalls\":"<<stalls
            <<",\"concurrent_cycles\":"<<concurrent<<",\"error_responses\":"<<errors
            <<",\"cycles\":"<<cycles<<",\"resets\":4}\n";
    }catch(const std::exception &e){std::cerr<<"cycle="<<cycles<<" "<<e.what()<<"\n";return 1;}
}
