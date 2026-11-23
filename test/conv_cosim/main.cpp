// SPDX-License-Identifier: Apache-2.0
#include "Vconv_cosim_top.h"
#include "verilated.h"
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <vector>
#include "riscv_nnfunctions.h"

extern "C" int cosim_reference(const int8_t*,const int8_t*,const int32_t*,const int32_t*,const int32_t*,
    const nmsis_nn_dims*,const nmsis_nn_dims*,const nmsis_nn_dims*,const nmsis_nn_conv_params*,int8_t*);

static void require(bool cond,const std::string& text) { if(!cond) throw std::runtime_error(text); }
class Simulation {
public:
    std::unique_ptr<VerilatedContext> context;
    std::unique_ptr<Vconv_cosim_top> dut;
    uint64_t cycles=0, commands=0;
    Simulation(int argc,char** argv):context(new VerilatedContext),dut(nullptr) {
        context->commandArgs(argc,argv); dut.reset(new Vconv_cosim_top(context.get()));
        dut->clk=0;dut->rst_n=0;dut->host_mode=1;
        for(int i=0;i<8;i++)tick(); dut->rst_n=1;
        for(int i=0;i<8;i++)tick();
    }
    void settle() { dut->clk=0;dut->eval(); }
    void tick() {
        settle();context->timeInc(5);dut->clk=1;dut->eval();context->timeInc(5);
        settle();cycles++;
        require(cycles<10000000,"simulation cycle limit exceeded");
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
static unsigned protocol_inject_on_start=0,protocol_injection_checks=0;
static void busyProtocolProbe(unsigned mode);
extern "C" void dsa_mmio_write(uint32_t addr,uint32_t value){
    sim->axilWrite(addr,value);
    if(addr==DSA_MMIO_BASE+NPU_REG_CTRL && (value&1u) && protocol_inject_on_start) {
        unsigned mode=protocol_inject_on_start;protocol_inject_on_start=0;
        busyProtocolProbe(mode);
    }
}
extern "C" uint32_t dsa_mmio_read(uint32_t addr){return sim->axilRead(addr);}

static void protect(void* p,size_t bytes,int protection) {
    uintptr_t lo=(uintptr_t)p&~uintptr_t(4095),hi=((uintptr_t)p+bytes+4095)&~uintptr_t(4095);
    require(mprotect((void*)lo,hi-lo,protection)==0,"mprotect failed");
}
struct Case {
    const char* name;int b,h,w,ci,kh,kw,co,groups,sh,sw,dh,dw,ph,pw,offset;bool fast=false;
    bool is_mode=false,aligned=false,bypass=false;
};
static uint32_t random_state=0x7a013;
static uint32_t rng(){random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
static unsigned total_outputs=0,total_cases=0;
static void runCase(const Case& c,uint8_t* arena,bool high=false) {
    int oh=(c.h+2*c.ph-(c.kh-1)*c.dh-1)/c.sh+1,ow=(c.w+2*c.pw-(c.kw-1)*c.dw-1)/c.sw+1;
    nmsis_nn_dims in={c.b,c.h,c.w,c.ci},f={1,c.kh,c.kw,c.ci/c.groups},out={c.b,oh,ow,c.co},bd={1,1,1,c.co};
    size_t input_bytes=size_t(c.b)*c.h*c.w*c.ci,weight_bytes=size_t(c.co)*c.kh*c.kw*f.c,output_bytes=size_t(c.b)*oh*ow*c.co;
    int8_t* input=(int8_t*)arena+(c.aligned?0x2000:0x1ffd);int8_t* weight=(int8_t*)arena+0x20fff;int8_t* output=(int8_t*)arena+0x40003;
    int32_t* bias=(int32_t*)(arena+0x30000);int32_t* mult=(int32_t*)(arena+0x31000);int32_t* shift=(int32_t*)(arena+0x32000);
    require(input_bytes<0x10000 && weight_bytes<0x9000 && output_bytes<0x10000,"test allocation too small");
    void* high_storage=MAP_FAILED;
    size_t high_bytes=input_bytes+weight_bytes+output_bytes;
    if(high){
        high_storage=mmap(nullptr,high_bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        require(high_storage!=MAP_FAILED && uintptr_t(high_storage)>UINT32_MAX,"high-address allocation failed");
        input=static_cast<int8_t*>(high_storage);weight=input+input_bytes;output=weight+weight_bytes;
    }
    for(size_t i=0;i<input_bytes;i++)input[i]=int8_t(int(rng()%31)-15);
    if(input_bytes>3){input[0]=-128;input[1]=127;input[2]=-1;}
    for(size_t i=0;i<weight_bytes;i++)weight[i]=int8_t(int(rng()%15)-7);
    for(int i=0;i<c.co;i++){bias[i]=int32_t(rng()%301)-150;mult[i]=0x40000000+int32_t(rng()%0x3fffffff);shift[i]=-8-(i%3);}
    nmsis_nn_conv_params p={};p.stride={c.sw,c.sh};p.dilation={c.dw,c.dh};p.padding={c.pw,c.ph};
    p.input_offset=c.offset;p.output_offset=-7;p.activation.min=-113;p.activation.max=109;
    nmsis_nn_per_channel_quant_params q={mult,shift};
    std::vector<int8_t> expected(output_bytes);
    require(cosim_reference(input,weight,bias,mult,shift,&in,&f,&out,&p,expected.data())==0,"reference numeric contract failed");
    uint64_t start_commands=sim->commands;
    if(high) {
        std::vector<int16_t> scratch(size_t(c.kh)*c.kw*c.ci*4+16);
        nmsis_nn_context ctx={scratch.data(),int32_t(scratch.size()*2)};
        auto status=riscv_convolve_s8_acc(&ctx,&p,&q,&in,input,&f,weight,&bd,bias,nullptr,&out,output);
        require(status==RISCV_NMSIS_NN_SUCCESS,"software fallback failed");
        require(sim->commands==start_commands,"fallback unexpectedly launched NPU");
        require(std::equal(expected.begin(),expected.end(),output),"software fallback output mismatch");
        std::cout<<"COSIM_FALLBACK_PASS name="<<c.name<<" outputs="<<output_bytes<<" commands=0\n";
        munmap(high_storage,high_bytes);
    } else {
        memset(output-16,0xa5,output_bytes+32);
        sim->copyToRam(input,input_bytes);sim->copyToRam(weight,weight_bytes);
        sim->copyToRam(bias,c.co*4);sim->copyToRam(mult,c.co*4);sim->copyToRam(shift,c.co*4);sim->copyToRam(output-16,output_bytes+32);
        protect(input,input_bytes,PROT_NONE);protect(weight,weight_bytes,PROT_NONE);protect(output-16,output_bytes+32,PROT_NONE);
        sim->useNpu();uint64_t before=sim->cycles,read_before=sim->dut->npu_read_bytes,write_before=sim->dut->npu_write_bytes;
        riscv_nmsis_nn_status status;
        if(c.is_mode) {
            /* Exercise explicit IS selection through the low-level API. */
            dsa_conv_s8_config_t job={};
            job.input_h=c.h;job.input_w=c.w;job.input_c=c.ci;job.group_c=f.c;
            job.kernel_h=c.kh;job.kernel_w=c.kw;job.output_h=oh;job.output_w=ow;
            job.stride_h=c.sh;job.stride_w=c.sw;job.dilation_h=c.dh;job.dilation_w=c.dw;
            job.pad_top=c.ph;job.pad_left=c.pw;job.input_offset=c.offset;
            job.output_channels=c.co/c.groups;job.dst_row_stride=c.co;
            job.output_offset=p.output_offset;job.activation_min=p.activation.min;job.activation_max=p.activation.max;
            job.dataflow_mode=1;job.bypass_cache=c.bypass;
            status=RISCV_NMSIS_NN_SUCCESS;
            for(int batch=0;batch<c.b && status==RISCV_NMSIS_NN_SUCCESS;batch++) {
                job.input_base=uint32_t(uintptr_t(input)+size_t(batch)*c.h*c.w*c.ci);
                for(int group=0;group<c.groups;group++) {
                    unsigned oc=unsigned(group)*job.output_channels;
                    job.group_offset=unsigned(group)*unsigned(f.c);
                    job.filter_base=uint32_t(uintptr_t(weight)+size_t(oc)*c.kh*c.kw*f.c);
                    job.output_base=uint32_t(uintptr_t(output)+size_t(batch)*oh*ow*c.co+oc);
                    job.bias_base=uint32_t(uintptr_t(bias)+oc*4u);
                    job.multiplier_base=uint32_t(uintptr_t(mult)+oc*4u);
                    job.shift_base=uint32_t(uintptr_t(shift)+oc*4u);
                    uint32_t result=dsa_conv_s8_execute(&job);
                    if(result!=DSA_SUCCESS) {
                        std::cerr<<"IS Conv driver result="<<result<<" case="<<c.name<<"\n";
                        status=RISCV_NMSIS_NN_NO_IMPL_ERROR;break;
                    }
                }
            }
        } else {
            status=c.fast?riscv_convolve_1x1_s8_fast_acc(nullptr,&p,&q,&in,input,&f,weight,&bd,bias,&out,output):
                riscv_convolve_wrapper_s8_acc(nullptr,&p,&q,&in,input,&f,weight,&bd,bias,&out,output);
        }
        uint64_t duration=sim->cycles-before,reads=sim->dut->npu_read_bytes-read_before,writes=sim->dut->npu_write_bytes-write_before;
        if(status!=RISCV_NMSIS_NN_SUCCESS) {
            std::cerr<<"C driver failed status="<<int(status)<<" hw_status="<<std::hex<<dsa_reg_read(NPU_REG_STATUS)<<std::dec<<" case="<<c.name<<" cycles="<<duration<<"\n";
            throw std::runtime_error("C driver reported failure");
        }
        uint32_t hits=dsa_reg_read(NPU_REG_CONV_HITS),misses=dsa_reg_read(NPU_REG_CONV_MISSES),input_read=dsa_reg_read(NPU_REG_CONV_READ_BYTES);
        uint32_t actual_dataflow=dsa_reg_read(NPU_REG_DATAFLOW);
        require(actual_dataflow<=1 && (!c.is_mode || actual_dataflow==1),"executed dataflow mode mismatch");
        sim->useHost();protect(input,input_bytes,PROT_READ|PROT_WRITE);protect(weight,weight_bytes,PROT_READ|PROT_WRITE);protect(output-16,output_bytes+32,PROT_READ|PROT_WRITE);
        sim->copyFromRam(output-16,output_bytes+32);
        for(size_t i=0;i<output_bytes;i++)if(output[i]!=expected[i]){
            std::cerr<<"Mismatch case="<<c.name<<" index="<<i<<" actual="<<int(output[i])<<" expected="<<int(expected[i])<<"\n";
            throw std::runtime_error("RTL output mismatch");
        }
        for(int i=1;i<=16;i++)require(uint8_t(output[-i])==0xa5,"output prefix guard overwritten");
        for(size_t i=output_bytes;i<output_bytes+16;i++)require(uint8_t(output[i])==0xa5,"output suffix guard overwritten");
        require(sim->commands-start_commands==uint64_t(c.b*c.groups),"batch/group command count mismatch");
        std::cout<<"COSIM_CONV_PASS name="<<c.name<<" outputs="<<output_bytes<<" commands="<<sim->commands-start_commands
                 <<" cycles="<<duration<<" axi_read_bytes="<<reads<<" axi_write_bytes="<<writes
                 <<" last_job_hits="<<hits<<" last_job_misses="<<misses<<" last_job_input_bytes="<<input_read
                 <<" dataflow="<<(actual_dataflow?"IS":"WS")<<" bypass="<<c.bypass<<"\n";
    }
    total_outputs+=unsigned(output_bytes);total_cases++;
}

static unsigned protocol_checks=0;
static void protocolCheck(bool condition,const char* message) {
    require(condition,message);protocol_checks++;
}
static uint32_t reg(uint32_t off) { return DSA_MMIO_BASE+off; }
static void busyProtocolProbe(unsigned mode) {
    uint32_t status=sim->axilRead(reg(NPU_REG_STATUS));
    protocolCheck((status&2u)!=0,"START did not set BUSY before response");
    protocolCheck((status&0x1cu)==0,"START did not clear previous done/error");
    if(mode==2) { protocol_injection_checks++;return; }
    uint32_t hw=sim->axilRead(reg(NPU_REG_CONV_INPUT_HW));
    uint32_t n=sim->axilRead(reg(NPU_REG_N));
    uint32_t ctrl=sim->axilRead(reg(NPU_REG_CTRL));
    uint64_t commands=sim->commands;
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_INPUT_HW),0x11112222,15,3,4)==2,"busy Conv config write did not return SLVERR");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_INPUT_HW))==hw,"busy write changed Conv geometry");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_N),n+1,15,-3,4)==2,"busy legacy config write did not return SLVERR");
    protocolCheck(sim->axilRead(reg(NPU_REG_N))==n,"busy write changed reduction length");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CTRL),0xd7,15,0,4)==2,"duplicate START did not return SLVERR");
    protocolCheck(sim->axilRead(reg(NPU_REG_CTRL))==ctrl,"duplicate START changed mode fields");
    protocolCheck(sim->commands==commands,"duplicate START was accepted");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_STATUS),4,1)==0,"STATUS W1C rejected during busy");
    protocolCheck((sim->axilRead(reg(NPU_REG_STATUS))&2u)!=0,"STATUS W1C cleared BUSY");
    protocol_injection_checks++;
}
static void runAxilProtocol(uint8_t* arena) {
    unsigned before=protocol_checks;
    protocolCheck(sim->axilRead(reg(NPU_REG_ID),4)==0x4e505531u,"device ID readback");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONFIG_ABI))==2u,"GEMM ABI readback");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_CAPS))==0x00010007u,"Conv capability/version readback");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_CAPS),0,15)==0,"capability ignored-write response");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_CAPS))==0x00010007u,"capability register was writable");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONFIG_ABI),0,15)==0,"ABI ignored-write response");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONFIG_ABI))==2u,"ABI register was writable");
    protocolCheck((sim->axilRead(reg(NPU_REG_CTRL))&1u)==0,"START pulse read back as stored bit");
    std::cout<<"AXIL_PROTOCOL_CASE_PASS name=identity_capability_readonly checks="<<protocol_checks-before<<"\n";
    before=protocol_checks;
    const uint32_t pairs[]={NPU_REG_CONV_INPUT_HW,NPU_REG_CONV_CHANNELS,NPU_REG_CONV_KERNEL_HW,
        NPU_REG_CONV_OUTPUT_HW,NPU_REG_CONV_STRIDE_HW,NPU_REG_CONV_DILATION_HW,NPU_REG_CONV_PADDING_HW};
    for(uint32_t address:pairs) {
        sim->axilWrite(reg(address),0x11223344);
        protocolCheck(sim->axilRead(reg(address),3)==0x11223344,"packed initial readback");
        protocolCheck(sim->axilWriteResponse(reg(address),0xaabbccdd,5,3,3)==0,"packed partial write response (AW first)");
        protocolCheck(sim->axilRead(reg(address))==0x11bb33dd,"packed byte 0/2 strobe merge");
        protocolCheck(sim->axilWriteResponse(reg(address),0x55667788,10,-3,3)==0,"packed partial write response (W first)");
        protocolCheck(sim->axilRead(reg(address))==0x55bb77dd,"packed byte 1/3 strobe merge");
        protocolCheck(sim->axilWriteResponse(reg(address),0xffffffff,0,0,3)==0,"zero-strobe write response");
        protocolCheck(sim->axilRead(reg(address))==0x55bb77dd,"zero-strobe modified packed field");
    }
    std::cout<<"AXIL_PROTOCOL_CASE_PASS name=packed_wstrb_channel_skew fields=7 checks="<<protocol_checks-before<<"\n";
    before=protocol_checks;
    sim->axilWrite(reg(NPU_REG_CONV_INPUT_BASE),0x12345678);
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_INPUT_BASE),0xaabbccdd,8)==0,"input base partial write");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_INPUT_BASE))==0xaa345678,"input base byte strobe");
    sim->axilWrite(reg(NPU_REG_CONV_GROUP_OFFSET),0x1234);
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_GROUP_OFFSET),0xaabbccdd,2)==0,"group offset partial write");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_GROUP_OFFSET))==0xcc34,"group offset lower half merge");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_GROUP_OFFSET),0xffffffff,12)==0,"group upper-half write");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_GROUP_OFFSET))==0xcc34,"group high bytes were not ignored");
    sim->axilWrite(reg(NPU_REG_CONV_INPUT_OFFSET),0);
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_INPUT_OFFSET),0x0000ff00,2)==0,"signed offset high byte write");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_INPUT_OFFSET))==0xffffff00,"signed offset did not sign extend");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_INPUT_OFFSET),0x00000081,1)==0,"signed offset low byte write");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_INPUT_OFFSET))==0xffffff81,"signed offset -127 readback");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CONV_INPUT_OFFSET),0,12)==0,"signed offset unused bytes write");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_INPUT_OFFSET))==0xffffff81,"unused upper bytes changed signed offset");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_CTRL),0x000000d6,2)==0,"CTRL upper-byte write response");
    protocolCheck(sim->axilRead(reg(NPU_REG_CTRL))==0,"CTRL ignored WSTRB[0] gate");
    sim->axilWriteResponse(reg(NPU_REG_CTRL),0xd6,1);
    protocolCheck(sim->axilRead(reg(NPU_REG_CTRL))==0xd6,"CTRL mode bit readback");
    std::cout<<"AXIL_PROTOCOL_CASE_PASS name=scalar_signed_control_wstrb checks="<<protocol_checks-before<<"\n";
    before=protocol_checks;
    protocol_inject_on_start=1;
    runCase({"axil_busy_lock",1,5,5,3,3,3,5,1,1,1,1,1,1,1,17},arena);
    protocolCheck(protocol_injection_checks==1,"busy protocol probe was not exercised");
    std::cout<<"AXIL_PROTOCOL_CASE_PASS name=busy_config_duplicate_start checks="<<protocol_checks-before<<" slverr=3\n";
    before=protocol_checks;
    uint32_t stride=sim->axilRead(reg(NPU_REG_CONV_STRIDE_HW));
    sim->axilWrite(reg(NPU_REG_CONV_STRIDE_HW),stride&0xffff0000u);
    sim->useNpu();uint64_t reads=sim->dut->npu_read_bytes,writes=sim->dut->npu_write_bytes;
    sim->axilWrite(reg(NPU_REG_CTRL),0x57);
    uint32_t state=0;unsigned left=10000;
    do { state=sim->axilRead(reg(NPU_REG_STATUS));require(--left,"invalid configuration failed to complete"); } while(!(state&4u));
    protocolCheck((state&0x1eu)==0x0cu,"configuration error status must be done+err1, not busy");
    protocolCheck(sim->dut->irq,"configuration error did not assert enabled IRQ");
    protocolCheck(sim->axilRead(reg(NPU_REG_WB_DATA))==1,"configuration error writeback code");
    protocolCheck(sim->dut->npu_read_bytes==reads && sim->dut->npu_write_bytes==writes,"invalid configuration issued a memory transaction");
    for(unsigned i=0;i<4;i++)protocolCheck((sim->axilRead(reg(NPU_REG_STATUS),3)&0x1cu)==0x0cu,"done/error not sticky across reads");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_STATUS),4,8)==0,"STATUS upper-byte write response");
    protocolCheck((sim->axilRead(reg(NPU_REG_STATUS))&0x1cu)==0x0cu && sim->dut->irq,"wrong-byte W1C changed done/error/IRQ");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_STATUS),0,1)==0,"STATUS zero write response");
    protocolCheck((sim->axilRead(reg(NPU_REG_STATUS))&0x1cu)==0x0cu,"writing zero cleared done/error");
    protocolCheck(sim->axilWriteResponse(reg(NPU_REG_STATUS),4,1)==0,"STATUS valid W1C response");
    protocolCheck((sim->axilRead(reg(NPU_REG_STATUS))&0x1cu)==0x08u && !sim->dut->irq,"W1C did not clear done/IRQ while preserving error history");
    protocolCheck(sim->axilRead(reg(NPU_REG_WB_DATA))==1,"W1C unexpectedly erased writeback history");
    sim->useHost();sim->axilWrite(reg(NPU_REG_CONV_STRIDE_HW),stride);
    std::cout<<"AXIL_PROTOCOL_CASE_PASS name=configuration_error_sticky_w1c checks="<<protocol_checks-before<<"\n";
    before=protocol_checks;
    protocol_inject_on_start=2;
    runCase({"axil_error_recovery",1,5,5,3,3,3,5,1,1,1,1,1,1,1,17},arena);
    protocolCheck(protocol_injection_checks==2,"error-clear-on-start probe was not exercised");
    protocolCheck((sim->axilRead(reg(NPU_REG_STATUS))&0x1cu)==0,"successful recovery retained stale error/done");
    std::cout<<"AXIL_PROTOCOL_CASE_PASS name=recovery_clears_error checks="<<protocol_checks-before<<"\n";
    std::cout<<"AXIL_PROTOCOL_PASS groups=6 checks="<<protocol_checks<<" packed_fields=7 busy_slverr=3 valid_tasks=2 invalid_tasks=1 checked_outputs=250\n";
}
static void runUnavailableConv(bool is_only) {
    const uint32_t expected_caps=is_only?0x00010003u:0u;
    protocolCheck(sim->axilRead(reg(NPU_REG_ID))==0x4e505531u,"disabled profile changed device ID");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONFIG_ABI))==2u,"disabled profile changed GEMM ABI");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_CAPS))==expected_caps,"disabled profile advertised unavailable Conv capability");
    protocolCheck(dsa_conv_capabilities()==expected_caps,"production capability query mismatch");
    dsa_conv_s8_config_t c={};
    c.input_base=0x11ffd;c.filter_base=0x30fff;c.output_base=0x50003;c.bias_base=0x40000;
    c.multiplier_base=0x41000;c.shift_base=0x42000;
    c.input_h=c.input_w=c.input_c=c.group_c=c.kernel_h=c.kernel_w=c.output_h=c.output_w=1;
    c.stride_h=c.stride_w=c.dilation_h=c.dilation_w=c.output_channels=c.dst_row_stride=1;
    c.activation_min=-128;c.activation_max=127;c.ia_reuse_num=c.w_reuse_num=1;
    c.dataflow_mode=is_only?1u:0u;
    protocolCheck(dsa_conv_s8_validate(&c)==DSA_SUCCESS,"disabled-profile test command is not otherwise valid");
    protocolCheck(dsa_conv_s8_execute(&c)==DSA_ERR_UNSUPPORTED,"production driver did not reject absent Conv capability");
    protocolCheck(sim->commands==0,"unsupported driver call issued START");
    protocolCheck(sim->dut->npu_read_bursts==0 && sim->dut->npu_read_bytes==0 && sim->dut->npu_write_bytes==0,
                  "unsupported driver call issued memory traffic");
    // Bypass the capability-aware driver deliberately: the core must reject an
    // otherwise legal 1x1 command even when software forces HW_CONV directly.
    const uint32_t fields[][2]={
        {NPU_REG_LHS_BASE,c.input_base},{NPU_REG_RHS_BASE,c.filter_base},{NPU_REG_DST_BASE,c.output_base},
        {NPU_REG_BIAS_BASE,c.bias_base},{NPU_REG_K,1},{NPU_REG_N,1},{NPU_REG_M,1},
        {NPU_REG_LHS_STRIDE_B,DSA_TILE_SIZE*2},{NPU_REG_RHS_STRIDE_B,1},{NPU_REG_DST_STRIDE_B,1},
        {NPU_REG_LHS_ZP,0},{NPU_REG_RHS_ZP,0},{NPU_REG_DST_ZP,0},
        {NPU_REG_Q_MULT,c.multiplier_base},{NPU_REG_Q_SHIFT,c.shift_base},
        {NPU_REG_ACT_MIN,uint32_t(-128)},{NPU_REG_ACT_MAX,127},
        {NPU_REG_IA_REUSE,1},{NPU_REG_W_REUSE,1},{NPU_REG_DATAFLOW,c.dataflow_mode},
        {NPU_REG_IA_BANKS,2},{NPU_REG_PS_CONTROL,1},
        {NPU_REG_ROW_GROUPS,1},{NPU_REG_ROW_TAIL_TILES,1},{NPU_REG_COL_GROUPS,1},{NPU_REG_COL_TAIL_TILES,1},
        {NPU_REG_CONV_INPUT_BASE,c.input_base},{NPU_REG_CONV_INPUT_HW,0x00010001},
        {NPU_REG_CONV_CHANNELS,0x00010001},{NPU_REG_CONV_GROUP_OFFSET,0},
        {NPU_REG_CONV_KERNEL_HW,0x00010001},{NPU_REG_CONV_OUTPUT_HW,0x00010001},
        {NPU_REG_CONV_STRIDE_HW,0x00010001},{NPU_REG_CONV_DILATION_HW,0x00010001},
        {NPU_REG_CONV_PADDING_HW,0},{NPU_REG_CONV_INPUT_OFFSET,0}
    };
    for(const auto& field:fields)sim->axilWrite(reg(field[0]),field[1]);
    sim->useNpu();sim->axilWrite(reg(NPU_REG_CTRL),is_only?0x5fu:0x57u);
    uint32_t state=0;unsigned left=10000;
    do {state=sim->axilRead(reg(NPU_REG_STATUS));require(--left,"disabled Conv forced START did not complete");}while(!(state&4u));
    protocolCheck((state&0x1eu)==0x0cu,"disabled Conv did not return done+configuration error and release busy");
    protocolCheck(sim->axilRead(reg(NPU_REG_WB_DATA))==1,"disabled Conv writeback was not configuration error");
    protocolCheck(sim->dut->irq,"disabled Conv error did not assert enabled IRQ");
    protocolCheck(sim->commands==1,"disabled Conv test did not issue exactly one forced START");
    protocolCheck(sim->dut->npu_read_bursts==0 && sim->dut->npu_read_bytes==0 && sim->dut->npu_write_bytes==0,
                  "forced disabled Conv issued memory traffic");
    protocolCheck(sim->axilRead(reg(NPU_REG_CONV_HITS))==0 && sim->axilRead(reg(NPU_REG_CONV_MISSES))==0 &&
                  sim->axilRead(reg(NPU_REG_CONV_READ_BYTES))==0,"disabled Conv exposed nonzero cache counters");
    sim->axilWrite(reg(NPU_REG_STATUS),4);
    protocolCheck((sim->axilRead(reg(NPU_REG_STATUS))&0x1cu)==8 && !sim->dut->irq,"disabled Conv W1C completion handling");
    sim->useHost();
    std::cout<<(is_only?"CONV_DISABLED_IS_PASS":"CONV_DISABLED_PER_CHANNEL_PASS")<<" checks="<<protocol_checks
             <<" capability="<<expected_caps<<" driver_start=0 forced_start=1 error=1 external_transactions=0\n";
}
int main(int argc,char** argv) {
    try {
        Simulation instance(argc,argv);sim=&instance;
        void* mem=mmap((void*)0x10000,0x60000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
        require(mem!=MAP_FAILED && mem==(void*)0x10000,"32-bit CPU test arena mapping failed");
        auto* arena=(uint8_t*)mem;memset(arena,0xa5,0x60000);
        bool protocol_only=false,disabled_per_channel=false,disabled_is=false;
        for(int i=1;i<argc;i++) {
            if(std::string(argv[i])=="+AXIL_PROTOCOL_ONLY")protocol_only=true;
            if(std::string(argv[i])=="+CONV_DISABLED_PER_CHANNEL")disabled_per_channel=true;
            if(std::string(argv[i])=="+CONV_DISABLED_IS")disabled_is=true;
        }
        if(disabled_per_channel || disabled_is) {
            runUnavailableConv(disabled_is);munmap(mem,0x60000);sim->dut->final();return 0;
        }
        require(dsa_conv_capabilities()==0x00010007u,"actual RTL capability register mismatch");
        if(protocol_only) {
            runAxilProtocol(arena);munmap(mem,0x60000);sim->dut->final();return 0;
        }
        runCase({"conv3x3",1,5,5,3,3,3,5,1,1,1,1,1,1,1,17},arena);
        runCase({"pointwise",1,3,7,5,1,1,7,1,1,1,1,1,0,0,-127,true},arena);
        runCase({"batch_groups",2,4,5,6,3,2,9,3,1,1,1,1,1,0,128},arena);
        runCase({"rect_stride_dilation",1,9,10,5,2,3,7,1,2,1,2,2,1,2,-31},arena);
        runCase({"same_address_changed_input",1,5,5,3,3,3,5,1,1,1,1,1,1,1,17},arena);
        runCase({"address_range_fallback",1,4,5,3,3,3,5,1,1,1,1,1,1,1,17},arena,true);
        runCase({"is_conv3x3",1,5,5,3,3,3,5,1,1,1,1,1,1,1,17,false,true},arena);
        runCase({"is_pointwise",1,3,7,5,1,1,7,1,1,1,1,1,0,0,-127,false,true},arena);
        runCase({"is_batch_groups",2,4,5,6,3,2,9,3,1,1,1,1,1,0,128,false,true},arena);
        runCase({"is_rect_stride_dilation",1,9,10,5,2,3,7,1,2,1,2,2,1,2,-31,false,true},arena);
        runCase({"aligned_ws_reuse",1,12,12,16,3,3,17,1,1,1,1,1,1,1,-17,false,false,true},arena);
        runCase({"aligned_is_same_shape",1,12,12,16,3,3,17,1,1,1,1,1,1,1,-17,false,true,true},arena);
        runCase({"aligned_ws_after_is",1,12,12,16,3,3,17,1,1,1,1,1,1,1,-17,false,false,true},arena);
        runCase({"is_bypass_double_tail",1,5,7,5,3,3,19,1,1,1,1,1,1,1,128,false,true,false,true},arena);
        std::cout<<"CONV_C_RTL_COSIM_PASS cases="<<total_cases<<" outputs="<<total_outputs<<" hardware_commands="<<sim->commands<<"\n";
        munmap(mem,0x60000);sim->dut->final();return 0;
    } catch(const std::exception& e) { std::cerr<<"CONV_C_RTL_COSIM_FAIL "<<e.what()<<"\n";return 1; }
}
