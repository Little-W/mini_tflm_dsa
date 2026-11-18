// SPDX-License-Identifier: Apache-2.0
#include "Vvector_engine_cosim_top.h"
#include "verilated.h"
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <vector>
#include "riscv_nnfunctions.h"
#include "dsa_vector.h"
#include "dsa_memory.h"
#include <limits>

static void require(bool cond,const std::string& text) { if(!cond) throw std::runtime_error(text); }
class Simulation {
public:
    std::unique_ptr<VerilatedContext> context;
    std::unique_ptr<Vvector_engine_cosim_top> dut;
    uint64_t cycles=0, commands=0;
    Simulation(int argc,char** argv):context(new VerilatedContext),dut(nullptr) {
        context->commandArgs(argc,argv); dut.reset(new Vvector_engine_cosim_top(context.get()));
        dut->clk=0;dut->rst_n=0;dut->host_mode=1;
        for(int i=0;i<8;i++)tick(); dut->rst_n=1;
        for(int i=0;i<8;i++)tick();
    }
    void settle() { dut->clk=0;dut->eval(); }
    void tick() {
        settle();context->timeInc(5);dut->clk=1;dut->eval();context->timeInc(5);
        settle();cycles++;
        require(cycles<100000000,"simulation cycle limit exceeded");
        require(!context->gotFinish(),"RTL called finish unexpectedly");
    }
    template<class P> void wait(P predicate,const char* reason) {
        unsigned remaining=100000;
        while(!predicate()){require(--remaining!=0,reason);tick();}
    }
    uint32_t axilWriteResponse(uint32_t addr,uint32_t value,uint32_t strobe=15,
                               int channel_skew=0,unsigned response_stall=0) {
        require(addr>=DSA_MMIO_BASE && addr<DSA_MMIO_BASE+65536u,"MMIO write range");
        dut->s_axil_awaddr=addr-DSA_MMIO_BASE;dut->s_axil_wdata=value;dut->s_axil_wstrb=strobe;
        dut->s_axil_awvalid=channel_skew>=0;dut->s_axil_wvalid=channel_skew<=0;dut->s_axil_bready=0;
        bool aw=false,w=false;
        unsigned remaining=100000,wait_cycles=unsigned(channel_skew<0?-channel_skew:channel_skew);
        while(!aw||!w) {
            settle();bool a=dut->s_axil_awvalid&&dut->s_axil_awready;
            bool d=dut->s_axil_wvalid&&dut->s_axil_wready;
            tick();if(a){aw=true;dut->s_axil_awvalid=0;}if(d){w=true;dut->s_axil_wvalid=0;}
            if((channel_skew>0 && aw && !w)||(channel_skew<0 && w && !aw)) {
                if(wait_cycles)wait_cycles--;
                else if(channel_skew>0)dut->s_axil_wvalid=1;
                else dut->s_axil_awvalid=1;
            }
            require(--remaining!=0,"AXI-Lite AW/W timeout");
        }
        settle();wait([&]{return dut->s_axil_bvalid;},"AXI-Lite B timeout");
        uint32_t response=dut->s_axil_bresp;
        for(unsigned i=0;i<response_stall;i++) {
            require(dut->s_axil_bvalid && dut->s_axil_bresp==response,"AXI-Lite B payload changed under backpressure");
            tick();
        }
        dut->s_axil_bready=1;tick();dut->s_axil_bready=0;settle();
        if(response==0 && addr==DSA_MMIO_BASE+NPU_REG_CTRL && (strobe&1u) && (value&1u))commands++;
        return response;
    }
    void axilWrite(uint32_t addr,uint32_t value) {
        require(axilWriteResponse(addr,value)==0,"AXI-Lite write response error");
    }
    uint32_t axilRead(uint32_t addr,unsigned response_stall=0) {
        require(addr>=DSA_MMIO_BASE && addr<DSA_MMIO_BASE+65536u,"MMIO read range");
        dut->s_axil_araddr=addr-DSA_MMIO_BASE;dut->s_axil_arvalid=1;dut->s_axil_rready=0;
        settle();wait([&]{return dut->s_axil_arready;},"AXI-Lite AR timeout");
        tick();dut->s_axil_arvalid=0;settle();
        wait([&]{return dut->s_axil_rvalid;},"AXI-Lite R timeout");
        require(dut->s_axil_rresp==0,"AXI-Lite read response error");
        uint32_t value=dut->s_axil_rdata;
        for(unsigned i=0;i<response_stall;i++) {
            require(dut->s_axil_rvalid && dut->s_axil_rdata==value && dut->s_axil_rresp==0,"AXI-Lite R payload changed under backpressure");
            tick();
        }
        dut->s_axil_rready=1;tick();dut->s_axil_rready=0;settle();return value;
    }
    void writeWords(uint32_t addr,const uint32_t* data,unsigned words) {
        require(dut->host_mode && words && words<=64 && !(addr&3u),"host write shape");
        dut->h_awaddr=addr;dut->h_awlen=words-1;dut->h_awvalid=1;dut->h_bready=0;
        settle();wait([&]{return dut->h_awready;},"host AW timeout");tick();dut->h_awvalid=0;
        for(unsigned i=0;i<words;i++) {
            dut->h_wdata=data[i];dut->h_wstrb=15;dut->h_wlast=(i+1==words);dut->h_wvalid=1;
            settle();wait([&]{return dut->h_wready;},"host W timeout");tick();
        }
        dut->h_wvalid=0;dut->h_wlast=0;settle();
        wait([&]{return dut->h_bvalid;},"host B timeout");require(dut->h_bresp==0,"host write error");
        dut->h_bready=1;tick();dut->h_bready=0;settle();
    }
    void readWords(uint32_t addr,uint32_t* data,unsigned words) {
        require(dut->host_mode && words && words<=64 && !(addr&3u),"host read shape");
        dut->h_araddr=addr;dut->h_arlen=words-1;dut->h_arvalid=1;dut->h_rready=0;
        settle();wait([&]{return dut->h_arready;},"host AR timeout");tick();dut->h_arvalid=0;settle();
        for(unsigned i=0;i<words;i++) {
            wait([&]{return dut->h_rvalid;},"host R timeout");
            require(dut->h_rresp==0,"host read error");require(bool(dut->h_rlast)==(i+1==words),"host RLAST mismatch");
            data[i]=dut->h_rdata;dut->h_rready=1;tick();
        }
        dut->h_rready=0;settle();
    }
    void copyToRam(const void* ptr,size_t bytes) {
        uintptr_t lo=(uintptr_t)ptr&~uintptr_t(3),hi=((uintptr_t)ptr+bytes+3)&~uintptr_t(3);
        for(uintptr_t addr=lo;addr<hi;) {
            unsigned words=unsigned(std::min({uintptr_t(64),(hi-addr)/4,(4096-(addr&4095))/4}));
            uint32_t data[64];memcpy(data,(const void*)addr,words*4);writeWords(uint32_t(addr),data,words);addr+=words*4;
        }
    }
    void copyFromRam(void* ptr,size_t bytes) {
        uintptr_t lo=(uintptr_t)ptr&~uintptr_t(3),hi=((uintptr_t)ptr+bytes+3)&~uintptr_t(3);
        for(uintptr_t addr=lo;addr<hi;) {
            unsigned words=unsigned(std::min({uintptr_t(64),(hi-addr)/4,(4096-(addr&4095))/4}));
            uint32_t data[64];readWords(uint32_t(addr),data,words);memcpy((void*)addr,data,words*4);addr+=words*4;
        }
    }
    void useNpu() { dut->host_mode=0;tick(); }
    void useHost() {
        wait([&]{return !dut->npu_busy;},"NPU remained busy after driver completed");
        for(int i=0;i<16;i++)tick();dut->host_mode=1;tick();
    }
};
static Simulation* sim;
extern "C" void dsa_mmio_write(uint32_t addr,uint32_t value){sim->axilWrite(addr,value);}
extern "C" uint32_t dsa_mmio_read(uint32_t addr){return sim->axilRead(addr);}
extern "C" riscv_nmsis_nn_status reference_depthwise_s8(
    const nmsis_nn_context*,const nmsis_nn_dw_conv_params*,const nmsis_nn_per_channel_quant_params*,
    const nmsis_nn_dims*,const int8_t*,const nmsis_nn_dims*,const int8_t*,
    const nmsis_nn_dims*,const int32_t*,const nmsis_nn_dims*,int8_t*);
extern "C" riscv_nmsis_nn_status reference_avgpool_s8(
    const nmsis_nn_context*,const nmsis_nn_pool_params*,const nmsis_nn_dims*,const int8_t*,
    const nmsis_nn_dims*,const nmsis_nn_dims*,int8_t*);
extern "C" riscv_nmsis_nn_status reference_max_pool_s8(
    const nmsis_nn_context*,const nmsis_nn_pool_params*,const nmsis_nn_dims*,const int8_t*,
    const nmsis_nn_dims*,const nmsis_nn_dims*,int8_t*);

static void protect(void* p,size_t bytes,int access) {
    uintptr_t lo=(uintptr_t)p&~uintptr_t(4095),hi=((uintptr_t)p+bytes+4095)&~uintptr_t(4095);
    require(mprotect((void*)lo,hi-lo,access)==0,"memory protection failed");
}
static uint32_t rng_state=0xf058b31;
static uint32_t rng(){rng_state^=rng_state<<13;rng_state^=rng_state>>17;rng_state^=rng_state<<5;return rng_state;}
static unsigned total_cases=0,total_outputs=0;
static bool hardware_available=true;

static void checkBytes(const char* name,const int8_t* output,const std::vector<int8_t>& expected) {
    for(size_t i=0;i<expected.size();i++) {
        if(output[i]!=expected[i]) {
            std::cerr<<"case="<<name<<" index="<<i<<" actual="<<int(output[i])<<" expected="<<int(expected[i])<<"\n";
            throw std::runtime_error("NMSIS output comparison failed");
        }
    }
    for(int i=1;i<=16;i++)require(uint8_t(output[-i])==0xa5,"output prefix changed");
    for(size_t i=expected.size();i<expected.size()+16;i++)require(uint8_t(output[i])==0xa5,"output suffix changed");
}
static void reportCase(const char* type,const char* name,size_t outputs,uint64_t commands,
                       uint64_t cycles,uint64_t reads,uint64_t writes) {
    std::cout<<"VECTOR_ENGINE_COSIM_CASE type="<<type<<" name="<<name<<" outputs="<<outputs
             <<" commands="<<commands<<" cycles="<<cycles<<" axi_read_bytes="<<reads<<" axi_write_bytes="<<writes<<"\n";
    total_cases++;total_outputs+=unsigned(outputs);
}

extern "C" int cosim_reference(const int8_t*,const int8_t*,const int32_t*,const int32_t*,const int32_t*,
    const nmsis_nn_dims*,const nmsis_nn_dims*,const nmsis_nn_dims*,const nmsis_nn_conv_params*,int8_t*);
static void runConvSwitch(const char* name,uint8_t* arena,bool is_mode) {
    constexpr int h=3,w=5,ci=3,co=5;
    constexpr size_t ni=h*w*ci,nw=ci*co,no=h*w*co;
    int8_t* input=(int8_t*)arena+0x1ffd;int8_t* weight=(int8_t*)arena+0x20fff;int8_t* output=(int8_t*)arena+0x40003;
    int32_t* bias=(int32_t*)(arena+0x30000);int32_t* mult=(int32_t*)(arena+0x31000);int32_t* shift=(int32_t*)(arena+0x32000);
    for(size_t i=0;i<ni;i++)input[i]=int8_t(int(rng()%255)-128);
    for(size_t i=0;i<nw;i++)weight[i]=int8_t(int(rng()%17)-8);
    for(int i=0;i<co;i++){bias[i]=i-2;mult[i]=0x60000000;shift[i]=-7-i;}
    nmsis_nn_dims in={1,h,w,ci},filter={1,1,1,ci},out={1,h,w,co};
    nmsis_nn_conv_params params={};params.stride={1,1};params.dilation={1,1};
    params.input_offset=17;params.output_offset=-3;params.activation.min=-119;params.activation.max=113;
    std::vector<int8_t> expected(no);
    require(cosim_reference(input,weight,bias,mult,shift,&in,&filter,&out,&params,expected.data())==0,"Conv software reference failed");
    memset(output-16,0xa5,no+32);
    sim->copyToRam(input,ni);sim->copyToRam(weight,nw);sim->copyToRam(output-16,no+32);
    sim->copyToRam(bias,co*4);sim->copyToRam(mult,co*4);sim->copyToRam(shift,co*4);
    protect(input,ni,PROT_NONE);protect(weight,nw,PROT_NONE);protect(output-16,no+32,PROT_NONE);
    protect(bias,co*4,PROT_NONE);protect(mult,co*4,PROT_NONE);protect(shift,co*4,PROT_NONE);
    dsa_conv_s8_config_t job={};job.input_base=uint32_t(uintptr_t(input));job.filter_base=uint32_t(uintptr_t(weight));
    job.output_base=uint32_t(uintptr_t(output));job.bias_base=uint32_t(uintptr_t(bias));
    job.multiplier_base=uint32_t(uintptr_t(mult));job.shift_base=uint32_t(uintptr_t(shift));
    job.input_h=h;job.input_w=w;job.input_c=ci;job.group_c=ci;job.kernel_h=1;job.kernel_w=1;
    job.output_h=h;job.output_w=w;job.stride_h=job.stride_w=job.dilation_h=job.dilation_w=1;
    job.output_channels=co;job.dst_row_stride=co;job.input_offset=params.input_offset;job.output_offset=params.output_offset;
    job.activation_min=params.activation.min;job.activation_max=params.activation.max;job.dataflow_mode=is_mode;
    uint64_t before_commands=sim->commands,before_cycles=sim->cycles,reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    sim->useNpu();require(dsa_conv_s8_execute(&job)==DSA_SUCCESS,"Conv mode switch failed");
    uint64_t duration=sim->cycles-before_cycles;sim->useHost();
    protect(input,ni,PROT_READ|PROT_WRITE);protect(weight,nw,PROT_READ|PROT_WRITE);protect(output-16,no+32,PROT_READ|PROT_WRITE);
    protect(bias,co*4,PROT_READ|PROT_WRITE);protect(mult,co*4,PROT_READ|PROT_WRITE);protect(shift,co*4,PROT_READ|PROT_WRITE);
    sim->copyFromRam(output-16,no+32);checkBytes(name,output,expected);
    require(sim->commands-before_commands==1,"Conv mode switch command count mismatch");
    reportCase(is_mode?"conv_is":"conv_ws",name,no,1,duration,sim->dut->npu_read_bytes-reads,sim->dut->npu_write_bytes-writes);
}

struct DwCase {
    const char* name;int batches,h,w,c,kh,kw,sh,sw,dh,dw,ph,pw,offset;
    int multiplier=1;bool no_bias=false,positive_shift=false,high_address=false;
};
static void runDepthwise(const DwCase& c,uint8_t* arena) {
    int oh=(c.h+2*c.ph-(c.kh-1)*c.dh-1)/c.sh+1;
    int ow=(c.w+2*c.pw-(c.kw-1)*c.dw-1)/c.sw+1;
    int co=c.c*c.multiplier;
    nmsis_nn_dims in={c.batches,c.h,c.w,c.c},filter={1,c.kh,c.kw,co},out={c.batches,oh,ow,co},bd={1,1,1,co};
    size_t ni=size_t(c.batches)*c.h*c.w*c.c,nw=size_t(c.kh)*c.kw*co,no=size_t(c.batches)*oh*ow*co;
    int8_t* input=(int8_t*)arena+0x1ffd;int8_t* weight=(int8_t*)arena+0x20fff;int8_t* output=(int8_t*)arena+0x40003;
    int32_t* bias=(int32_t*)(arena+0x30000);int32_t* mult=(int32_t*)(arena+0x31000);int32_t* shift=(int32_t*)(arena+0x32000);
    require(ni<0x10000 && nw<0x9000 && no<0x10000,"DW test allocation exceeded");
    void* high_input=MAP_FAILED;
    if(c.high_address) {
        high_input=mmap(reinterpret_cast<void*>(UINT64_C(0x100000000)),ni,
                        PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        require(high_input!=MAP_FAILED && uintptr_t(high_input)>UINT32_MAX,
                "DW high-address allocation failed");
        input=static_cast<int8_t*>(high_input);
    }
    for(size_t i=0;i<ni;i++)input[i]=int8_t(int(rng()%255)-128);
    for(size_t i=0;i<nw;i++)weight[i]=int8_t(int(rng()%255)-128);
    for(int i=0;i<co;i++){bias[i]=int32_t(rng()%3001)-1500;mult[i]=0x40000000+int32_t(rng()%0x3fffffff);shift[i]=-10-(i%4);}
    if(c.positive_shift) {
        for(size_t i=0;i<ni;i++)input[i]=int8_t(int(i%3)-1);
        for(size_t i=0;i<nw;i++)weight[i]=int8_t(int(i%3)-1);
        for(int i=0;i<co;i++){bias[i]=i-2;shift[i]=(i%4)-1;}
    }
    nmsis_nn_dw_conv_params params={};params.ch_mult=c.multiplier;
    params.stride={c.sw,c.sh};params.dilation={c.dw,c.dh};params.padding={c.pw,c.ph};
    params.input_offset=c.offset;params.output_offset=-3;params.activation.min=-119;params.activation.max=113;
    nmsis_nn_per_channel_quant_params quant={mult,shift};
    std::vector<int8_t> expected(no);nmsis_nn_context ctx={};
    require(reference_depthwise_s8(&ctx,&params,&quant,&in,input,&filter,weight,&bd,c.no_bias?nullptr:bias,&out,expected.data())==RISCV_NMSIS_NN_SUCCESS,"software DW reference failed");
    bool hw=hardware_available && c.multiplier==1 && c.kh*c.kw<=49 && !c.high_address;
    memset(output-16,0xa5,no+32);
    if(hw) {
        sim->copyToRam(input,ni);sim->copyToRam(weight,nw);sim->copyToRam(output-16,no+32);
        sim->copyToRam(bias,co*4);sim->copyToRam(mult,co*4);sim->copyToRam(shift,co*4);
        protect(input,ni,PROT_NONE);protect(weight,nw,PROT_NONE);protect(output-16,no+32,PROT_NONE);
        protect(bias,co*4,PROT_NONE);protect(mult,co*4,PROT_NONE);protect(shift,co*4,PROT_NONE);
    }
    uint64_t before_commands=sim->commands,before_cycles=sim->cycles,reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    sim->useNpu();
    auto status=riscv_depthwise_conv_wrapper_s8_acc(&ctx,&params,&quant,&in,input,&filter,weight,&bd,c.no_bias?nullptr:bias,&out,output);
    if(status!=RISCV_NMSIS_NN_SUCCESS) {
        std::ostringstream error;
        error<<"DW production wrapper failed: case="<<c.name<<" status="<<int(status)
             <<" input="<<static_cast<const void*>(input)<<" commands="<<(sim->commands-before_commands);
        throw std::runtime_error(error.str());
    }
    uint64_t duration=sim->cycles-before_cycles;
    sim->useHost();
    if(hw) {
        protect(input,ni,PROT_READ|PROT_WRITE);protect(weight,nw,PROT_READ|PROT_WRITE);protect(output-16,no+32,PROT_READ|PROT_WRITE);
        protect(bias,co*4,PROT_READ|PROT_WRITE);protect(mult,co*4,PROT_READ|PROT_WRITE);protect(shift,co*4,PROT_READ|PROT_WRITE);
        sim->copyFromRam(output-16,no+32);
    }
    checkBytes(c.name,output,expected);
    uint64_t commands=sim->commands-before_commands;
    require(commands==uint64_t(hw?c.batches:0),"DW hardware dispatch count mismatch");
    require(hw || (reads==sim->dut->npu_read_bytes && writes==sim->dut->npu_write_bytes),"software DW issued DMA traffic");
    reportCase(hw?"depthwise":"software",c.name,no,commands,duration,sim->dut->npu_read_bytes-reads,sim->dut->npu_write_bytes-writes);
    if(high_input!=MAP_FAILED)munmap(high_input,ni);
}

struct PoolCase {
    const char* name;int operation,batches,h,w,c,kh,kw,sh,sw,ph,pw;
    bool half_rounding=false;
};
static void runPool(const PoolCase& c,uint8_t* arena) {
    int oh=(c.h+2*c.ph-c.kh)/c.sh+1,ow=(c.w+2*c.pw-c.kw)/c.sw+1;
    nmsis_nn_dims in={c.batches,c.h,c.w,c.c},f={1,c.kh,c.kw,c.c},out={c.batches,oh,ow,c.c};
    nmsis_nn_pool_params p={};p.stride={c.sw,c.sh};p.padding={c.pw,c.ph};p.activation.min=-117;p.activation.max=109;
    size_t ni=size_t(c.batches)*c.h*c.w*c.c,no=size_t(c.batches)*oh*ow*c.c;
    int8_t* input=(int8_t*)arena+0x1ffd;int8_t* output=(int8_t*)arena+0x40003;
    require(ni<0x10000 && no<0x10000,"pool test allocation exceeded");
    for(size_t i=0;i<ni;i++)input[i]=int8_t(int(rng()%256)-128);
    if(c.half_rounding)for(size_t i=0;i<ni;i++)input[i]=int8_t((i/c.c)==0?(i%2?-1:1):0);
    std::vector<int8_t> expected(no);nmsis_nn_context ctx={};
    if(c.operation==DSA_VECTOR_OP_AVGPOOL_S8)
        require(reference_avgpool_s8(&ctx,&p,&in,input,&f,&out,expected.data())==RISCV_NMSIS_NN_SUCCESS,"software average pool reference failed");
    else if(c.operation==DSA_VECTOR_OP_MAXPOOL_S8)
        require(reference_max_pool_s8(&ctx,&p,&in,input,&f,&out,expected.data())==RISCV_NMSIS_NN_SUCCESS,"software maximum pool reference failed");
    else {
        for(int b=0;b<c.batches;b++)for(int y=0;y<oh;y++)for(int x=0;x<ow;x++)for(int ch=0;ch<c.c;ch++) {
            int value=127,count=0;
            for(int ky=0;ky<c.kh;ky++)for(int kx=0;kx<c.kw;kx++) {
                int iy=y*c.sh+ky-c.ph,ix=x*c.sw+kx-c.pw;
                if(iy>=0 && iy<c.h && ix>=0 && ix<c.w){value=std::min(value,int(input[((b*c.h+iy)*c.w+ix)*c.c+ch]));count++;}
            }
            require(count!=0,"empty pool test window");
            expected[((b*oh+y)*ow+x)*c.c+ch]=int8_t(std::max(p.activation.min,std::min(p.activation.max,value)));
        }
    }
    bool hw=hardware_available;
    if(!hw && c.operation==DSA_VECTOR_OP_MINPOOL_S8)return;
    memset(output-16,0xa5,no+32);
    if(hw){sim->copyToRam(input,ni);sim->copyToRam(output-16,no+32);protect(input,ni,PROT_NONE);protect(output-16,no+32,PROT_NONE);}
    uint64_t before_commands=sim->commands,before_cycles=sim->cycles,reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    sim->useNpu();
    if(c.operation==DSA_VECTOR_OP_AVGPOOL_S8)
        require(riscv_avgpool_s8(&ctx,&p,&in,input,&f,&out,output)==RISCV_NMSIS_NN_SUCCESS,"production average pool failed");
    else if(c.operation==DSA_VECTOR_OP_MAXPOOL_S8)
        require(riscv_max_pool_s8(&ctx,&p,&in,input,&f,&out,output)==RISCV_NMSIS_NN_SUCCESS,"production maximum pool failed");
    else {
        dsa_vector_config_t config;dsa_vector_config_init(&config);config.operation=c.operation;
        config.input_h=c.h;config.input_w=c.w;config.input_c=c.c;config.output_h=oh;config.output_w=ow;
        config.kernel_h=c.kh;config.kernel_w=c.kw;config.stride_h=c.sh;config.stride_w=c.sw;
        config.pad_top=c.ph;config.pad_left=c.pw;config.activation_min=p.activation.min;config.activation_max=p.activation.max;
        for(int b=0;b<c.batches;b++) {
            config.input_base=uint32_t(uintptr_t(input)+size_t(b)*c.h*c.w*c.c);
            config.output_base=uint32_t(uintptr_t(output)+size_t(b)*oh*ow*c.c);
            require(dsa_vector_execute(&config)==DSA_SUCCESS,"production minimum pool failed");
        }
    }
    uint64_t duration=sim->cycles-before_cycles;sim->useHost();
    if(hw){protect(input,ni,PROT_READ|PROT_WRITE);protect(output-16,no+32,PROT_READ|PROT_WRITE);sim->copyFromRam(output-16,no+32);}
    checkBytes(c.name,output,expected);
    require(sim->commands-before_commands==uint64_t(hw?c.batches:0),"pool hardware dispatch count mismatch");
    reportCase(hw?"pool":"software",c.name,no,sim->commands-before_commands,duration,sim->dut->npu_read_bytes-reads,sim->dut->npu_write_bytes-writes);
}

static void runVector(uint8_t* arena,unsigned operation,unsigned length,bool s16) {
    unsigned element=s16?2:1;uint8_t* lhs=arena+(s16?0x1ffe:0x1fff);uint8_t* rhs=arena+(s16?0x20ffe:0x20fff);
    int32_t* output=(int32_t*)(arena+0x40004);unsigned count=operation==DSA_VECTOR_OP_HADAMARD?length:1;
    std::vector<int32_t> a(length),b(length),expected(count);
    uint32_t accum=0;int32_t extreme=operation==DSA_VECTOR_OP_MAX?INT32_MIN:INT32_MAX;
    for(unsigned i=0;i<length;i++) {
        a[i]=s16?int16_t(rng()):int8_t(rng());b[i]=s16?int16_t(rng()):int8_t(rng());
        if(i==0){a[i]=s16?-32768:-128;b[i]=a[i];}
        if(i==1){a[i]=s16?32767:127;b[i]=-1;}
        if(s16){int16_t x=int16_t(a[i]),y=int16_t(b[i]);memcpy(lhs+i*2,&x,2);memcpy(rhs+i*2,&y,2);}
        else{lhs[i]=uint8_t(a[i]);rhs[i]=uint8_t(b[i]);}
        int32_t product=int32_t(int64_t(a[i])*b[i]);
        if(operation==DSA_VECTOR_OP_HADAMARD)expected[i]=product;
        else if(operation==DSA_VECTOR_OP_DOT)accum+=uint32_t(product);
        else if(operation==DSA_VECTOR_OP_SUM)accum+=uint32_t(a[i]);
        else if(operation==DSA_VECTOR_OP_MAX)extreme=std::max(extreme,a[i]);
        else if(operation==DSA_VECTOR_OP_MIN)extreme=std::min(extreme,a[i]);
    }
    if(operation!=DSA_VECTOR_OP_HADAMARD)expected[0]=(operation==DSA_VECTOR_OP_MAX||operation==DSA_VECTOR_OP_MIN)?extreme:int32_t(accum);
    memset((uint8_t*)output-16,0xa5,count*4+32);
    sim->copyToRam(lhs,length*element);sim->copyToRam(rhs,length*element);sim->copyToRam((uint8_t*)output-16,count*4+32);
    protect(lhs,length*element,PROT_NONE);protect(rhs,length*element,PROT_NONE);protect((uint8_t*)output-16,count*4+32,PROT_NONE);
    dsa_vector_config_t config;dsa_vector_config_init(&config);config.operation=operation;config.vector_s16=s16;config.length=length;
    config.input_base=uint32_t(uintptr_t(lhs));config.rhs_base=uint32_t(uintptr_t(rhs));config.output_base=uint32_t(uintptr_t(output));
    uint64_t before_commands=sim->commands,before_cycles=sim->cycles,reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    sim->useNpu();require(dsa_vector_execute(&config)==DSA_SUCCESS,"vector production driver failed");
    uint64_t duration=sim->cycles-before_cycles;sim->useHost();
    protect(lhs,length*element,PROT_READ|PROT_WRITE);protect(rhs,length*element,PROT_READ|PROT_WRITE);protect((uint8_t*)output-16,count*4+32,PROT_READ|PROT_WRITE);
    sim->copyFromRam((uint8_t*)output-16,count*4+32);
    require(std::equal(expected.begin(),expected.end(),output),"signed vector output mismatch");
    for(unsigned i=0;i<16;i++) {
        require(*((uint8_t*)output-1-i)==0xa5,"vector prefix changed");
        require(*((uint8_t*)output+count*4+i)==0xa5,"vector suffix changed");
    }
    require(sim->commands-before_commands==1,"vector command count mismatch");
    std::string name="op"+std::to_string(operation)+"_n"+std::to_string(length)+(s16?"_s16":"_s8");
    reportCase("vector",name.c_str(),count,1,duration,sim->dut->npu_read_bytes-reads,sim->dut->npu_write_bytes-writes);
}

static int64_t divideEven(int64_t value, unsigned shift) {
    const int64_t divisor=int64_t(1)<<shift;
    int64_t q=value/divisor,r=value%divisor;
    if(r<0)r=-r;
    if(r>divisor-r || (r==divisor-r && q%2))q+=value<0?-1:1;
    return q;
}
static void runAdd(const char* name,uint8_t* arena,unsigned length,
                   const dsa_vector_add_params_t& p,int offset=-128,
                   bool identical_inputs=false,bool inplace=false) {
    int8_t* a=(int8_t*)arena+0x1ffd;
    int8_t* b=identical_inputs?a:(int8_t*)arena+0x20fff;
    int8_t* output=inplace?a:(int8_t*)arena+0x40003;
    for(unsigned i=0;i<length;i++) {
        a[i]=int8_t(rng());
        if(!identical_inputs)b[i]=int8_t(rng());
    }
    std::vector<int8_t> expected(length);
    for(unsigned i=0;i<length;i++) {
        const int64_t x=(int64_t(a[i])+p.input1_offset)*(int64_t(1)<<p.left_shift);
        const int64_t y=(int64_t(b[i])+p.input2_offset)*(int64_t(1)<<p.left_shift);
        const int64_t u=divideEven(x*p.input1_multiplier,31-p.input1_shift);
        const int64_t v=divideEven(y*p.input2_multiplier,31-p.input2_shift);
        const int64_t q=divideEven((u+v)*p.output_multiplier,31-p.output_shift)+offset;
        expected[i]=int8_t(std::max<int64_t>(-128,std::min<int64_t>(127,q)));
    }
    if(inplace) {
        memset(output-16,0xa5,16);memset(output+length,0xa5,16);
    }else memset(output-16,0xa5,length+32);
    const bool hw=hardware_available && !inplace;
    if(hw) {
        sim->copyToRam(a,length);sim->copyToRam(b,length);sim->copyToRam(output-16,length+32);
        protect(a,length,PROT_NONE);protect(b,length,PROT_NONE);protect(output-16,length+32,PROT_NONE);
    }
    const uint64_t commands=sim->commands,cycles=sim->cycles;
    const uint64_t reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    sim->useNpu();
    require(riscv_elementwise_add_s8(a,b,p.input1_offset,p.input1_multiplier,p.input1_shift,
        p.input2_offset,p.input2_multiplier,p.input2_shift,p.left_shift,output,
        offset,p.output_multiplier,p.output_shift,-128,127,length)==RISCV_NMSIS_NN_SUCCESS,
        "production quantized Add failed");
    const uint64_t duration=sim->cycles-cycles;sim->useHost();
    if(hw) {
        protect(a,length,PROT_READ|PROT_WRITE);protect(b,length,PROT_READ|PROT_WRITE);
        protect(output-16,length+32,PROT_READ|PROT_WRITE);sim->copyFromRam(output-16,length+32);
    }
    checkBytes(name,output,expected);
    require(sim->commands-commands==unsigned(hw),"Add dispatch count mismatch");
    require(hw || (sim->dut->npu_read_bytes==reads && sim->dut->npu_write_bytes==writes),
            "software Add issued DMA traffic");
    reportCase(hw?"add":"software_add",name,length,sim->commands-commands,duration,
        sim->dut->npu_read_bytes-reads,sim->dut->npu_write_bytes-writes);
}

static void invalidDriverCalls() {
    dsa_vector_config_t c;dsa_vector_config_init(&c);c.operation=DSA_VECTOR_OP_SUM;
    c.input_base=0x10000;c.output_base=0x50004;c.length=0;
    uint64_t before=sim->commands,reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    require(dsa_vector_execute(&c)!=DSA_SUCCESS,"zero vector length was accepted");
    c.length=3;c.operation=15;require(dsa_vector_execute(&c)!=DSA_SUCCESS,"unknown operation was accepted");
    c.operation=DSA_VECTOR_OP_SUM;c.vector_s16=1;c.input_base=0x10001;
    require(dsa_vector_execute(&c)!=DSA_SUCCESS,"unaligned s16 address was accepted");
    c.input_base=0xfffffff0;c.length=32;
    require(dsa_vector_execute(&c)!=DSA_SUCCESS,"address overflow was accepted");
    require(sim->commands==before && sim->dut->npu_read_bytes==reads && sim->dut->npu_write_bytes==writes,"invalid driver input issued DMA traffic");
    total_cases+=4;std::cout<<"VECTOR_ENGINE_COSIM_INVALID_PASS cases=4 commands=0\n";
}

static void unavailableHardware() {
    dsa_vector_config_t c;dsa_vector_config_init(&c);c.operation=DSA_VECTOR_OP_SUM;
    c.input_base=0x11fff;c.output_base=0x50004;c.length=3;
    uint64_t before=sim->commands,reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    require(dsa_vector_execute(&c)==DSA_ERR_UNSUPPORTED,"disabled DW driver accepted a command");
    require(sim->commands==before,"disabled DW driver issued START");
    sim->axilWrite(DSA_MMIO_BASE+NPU_REG_VECTOR_OP,c.operation);
    sim->axilWrite(DSA_MMIO_BASE+NPU_REG_VECTOR_LENGTH,c.length);
    sim->axilWrite(DSA_MMIO_BASE+NPU_REG_LHS_BASE,c.input_base);
    sim->axilWrite(DSA_MMIO_BASE+NPU_REG_DST_BASE,c.output_base);
    sim->useNpu();sim->axilWrite(DSA_MMIO_BASE+NPU_REG_CTRL,NPU_CTRL_VECTOR_ENGINE|DSA_CTRL_START|DSA_CTRL_IRQ_ENABLE);
    uint32_t status=0;unsigned remaining=10000;
    do {status=sim->axilRead(DSA_MMIO_BASE+NPU_REG_STATUS);require(--remaining,"disabled DW forced START timed out");} while(!(status&DSA_STATUS_DONE));
    require((status&0x1eu)==0x0cu,"disabled DW completion status incorrect");
    require(sim->axilRead(DSA_MMIO_BASE+NPU_REG_WB_DATA)==1,"disabled DW error code incorrect");
    require(sim->dut->irq,"disabled DW error did not assert IRQ");
    require(sim->dut->npu_read_bytes==reads && sim->dut->npu_write_bytes==writes,"disabled DW issued memory traffic");
    require(sim->axilRead(DSA_MMIO_BASE+NPU_REG_VECTOR_CYCLES)==0 &&
            sim->axilRead(DSA_MMIO_BASE+NPU_REG_VECTOR_COMPUTE)==0 &&
            sim->axilRead(DSA_MMIO_BASE+NPU_REG_VECTOR_DMA_WAIT)==0,"disabled DW counters changed");
    sim->axilWrite(DSA_MMIO_BASE+NPU_REG_STATUS,DSA_STATUS_DONE);
    require(!sim->dut->irq,"completion clear did not release IRQ");sim->useHost();
    total_cases+=2;
    std::cout<<"VECTOR_ENGINE_UNAVAILABLE_PASS driver_commands=0 forced_commands=1 dma_read_bytes=0 dma_write_bytes=0\n";
}

int main(int argc,char** argv) {
    try {
        Simulation instance(argc,argv);sim=&instance;
        for(int i=1;i<argc;i++)if(std::string(argv[i])=="+DW_DISABLED")hardware_available=false;
        void* memory=mmap((void*)0x10000,0x60000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
        require(memory==(void*)0x10000,"32-bit CPU memory allocation failed");
        auto* arena=(uint8_t*)memory;memset(arena,0xa5,0x60000);
        uint32_t caps=dsa_vector_capabilities();
        const uint32_t vector_features=DSA_VECTOR_CAP_DW_S8|DSA_VECTOR_CAP_POOL_S8|
            DSA_VECTOR_CAP_VECTOR_S8|DSA_VECTOR_CAP_VECTOR_S16|DSA_VECTOR_CAP_LARGE_POOL|
            DSA_VECTOR_CAP_ADD_S8|DSA_VECTOR_CAP_SOFTMAX_S8;
        require(hardware_available?((caps&0xff)==vector_features):(caps==0),
                "Vector capability register mismatch");
        if(hardware_available)require(((caps>>8)&0xffu)==DW_TEST_PE_COUNT,"PE count capability mismatch");
        for(int i=1;i<argc;i++)if(std::string(argv[i])=="+PS_COMPRESS") {
            const uint32_t ps_caps=sim->axilRead(DSA_MMIO_BASE+NPU_REG_PS_CAPS);
            const uint32_t required=DSA_PS_CAP_STORE|DSA_PS_CAP_FRAME_SCHEDULE|
                DSA_PS_CAP_IA_COMPACT|DSA_PS_CAP_SHARED;
            require((ps_caps&required)==required && (ps_caps>>24)==DSA_PS_CAP_VERSION,
                    "Compressed PS capabilities differ");
            require(sim->axilRead(DSA_MMIO_BASE+NPU_REG_SHARED_TOTAL_BYTES)==14336 &&
                    sim->axilRead(DSA_MMIO_BASE+NPU_REG_SHARED_BANK_BYTES)==2048,
                    "Shared IA/PS capacity differs");
            require((dsa_conv_capabilities()&(DSA_CONV_CAP_S8|DSA_CONV_CAP_IS))==
                    (DSA_CONV_CAP_S8|DSA_CONV_CAP_IS),"Conv capabilities differ");
            std::cout<<"VECTOR_ENGINE_SHARED_PS_PASS total_bytes=14336 bank_bytes=2048 conv=1 vce=1\n";
        }
        if(hardware_available)runConvSwitch("conv_ws_before_dw",arena,false);
        runDepthwise({"dw3x3_tail",1,5,7,5,3,3,1,1,1,1,1,1,17},arena);
        runPool({"avgpool_padding",DSA_VECTOR_OP_AVGPOOL_S8,1,5,7,5,3,3,1,1,1,1},arena);
        if(hardware_available)runConvSwitch("conv_is_after_pool",arena,true);
        runDepthwise({"dw_stride2",1,9,8,7,3,3,2,2,1,1,1,1,128},arena);
        runPool({"maxpool_stride2",DSA_VECTOR_OP_MAXPOOL_S8,1,7,8,7,3,2,2,2,1,0},arena);
        runDepthwise({"dw_rect_dilation",1,9,10,3,2,3,1,2,2,2,1,2,-127},arena);
        runDepthwise({"dw_positive_shift",1,3,5,7,1,1,1,1,1,1,0,0,0,1,false,true},arena);
        runDepthwise({"dw_null_bias",1,5,5,5,3,3,1,1,1,1,1,1,0,1,true},arena);
        runDepthwise({"dw5x5",1,7,8,3,5,5,1,1,1,1,2,2,-11},arena);
        runDepthwise({"dw7x7",1,8,9,9,7,7,1,1,1,1,3,3,1},arena);
        runDepthwise({"dw_two_batches",2,4,5,3,3,3,1,1,1,1,1,1,21},arena);
        runDepthwise({"same_address_changed_input",1,5,7,5,3,3,1,1,1,1,1,1,17},arena);
        runPool({"avgpool_half_rounding",DSA_VECTOR_OP_AVGPOOL_S8,1,1,2,7,1,2,1,1,0,0,true},arena);
        runPool({"avgpool_two_batches",DSA_VECTOR_OP_AVGPOOL_S8,2,3,5,3,2,3,1,1,0,1},arena);
        runPool({"minpool_padding",DSA_VECTOR_OP_MINPOOL_S8,1,5,7,5,3,3,1,1,1,1},arena);
        runDepthwise({"multiplier2_software",1,4,5,3,3,3,1,1,1,1,1,1,3,2},arena);
        runDepthwise({"address_range_software",1,5,5,3,3,3,1,1,1,1,1,1,17,1,false,false,true},arena);
        runPool({"dscnn_avgpool_25x5",DSA_VECTOR_OP_AVGPOOL_S8,1,25,5,64,25,5,1,1,0,0},arena);
        runPool({"resnet_avgpool_8x8",DSA_VECTOR_OP_AVGPOOL_S8,1,8,8,64,8,8,1,1,0,0},arena);
        runPool({"avgpool_256_taps",DSA_VECTOR_OP_AVGPOOL_S8,1,16,16,17,16,16,1,1,0,0},arena);
        runPool({"avgpool_four_channels",DSA_VECTOR_OP_AVGPOOL_S8,1,5,5,4,5,5,1,1,0,0},arena);
        runPool({"maxpool_four_channel_tail",DSA_VECTOR_OP_MAXPOOL_S8,1,4,4,20,4,4,1,1,0,0},arena);
        const dsa_vector_add_params_t residuals[]={
            {128,-4,1623821475,-2,1073741824,0,20,1098017566,-17},
            {17,-4,1699529983,-2,1073741824,0,20,1140768826,-17},
            {-38,2,1657902019,-2,1073741824,0,20,1835721671,-18},
        };
        for(unsigned i=0;i<3;i++) {
            std::string name="resnet_add_"+std::to_string(i);
            runAdd(name.c_str(),arena,16384u>>i,residuals[i]);
        }
        const dsa_vector_add_params_t ties={0,0,1073741824,0,1073741824,0,0,1073741824,0};
        const dsa_vector_add_params_t saturate={128,-127,INT32_MAX,0,INT32_MAX,0,22,INT32_MAX,30};
        for(unsigned n:{1u,3u,7u,9u,15u,17u,65u,4097u}) {
            std::string name="add_tail_"+std::to_string(n);
            runAdd(name.c_str(),arena,n,ties,0);
        }
        runAdd("add_output_saturation",arena,65,saturate,127);
        runAdd("add_shared_input",arena,65,residuals[0],-128,true);
        runAdd("add_inplace",arena,65,residuals[0],-128,false,true);
        if(hardware_available) {
            for(bool s16:{false,true})for(unsigned operation:{4u,5u,6u,7u,8u})for(unsigned n:{1u,3u,17u,65u})
                runVector(arena,operation,n,s16);
            invalidDriverCalls();
            runConvSwitch("conv_ws_after_vector",arena,false);
            runDepthwise({"dw_after_conv_recovery",1,3,3,5,3,3,1,1,1,1,1,1,17},arena);
        } else {
            unavailableHardware();
        }
        require(!sim->dut->npu_busy,"device remained busy at end of test");
        std::cout<<"VECTOR_ENGINE_C_RTL_COSIM_PASS cases="<<total_cases<<" outputs="<<total_outputs<<" hardware_commands="<<sim->commands<<"\n";
        munmap(memory,0x60000);sim->dut->final();return 0;
    } catch(const std::exception& e) {
        std::cerr<<"VECTOR_ENGINE_C_RTL_COSIM_FAIL "<<e.what()<<"\n";return 1;
    }
}
