#include "Vraw_frame_store_tb.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>
#include <utility>

using Row=std::array<uint32_t,16>;
static void require(bool condition,const char* message) {
    if(!condition)throw std::runtime_error(message);
}

struct Test {
    Vraw_frame_store_tb dut;
    std::mt19937 random{2048};
    std::array<std::vector<Row>,4> frames;
    uint64_t cycles=0,commands=0,checked=0,pressure_checks=0,resets=0;
    void tick() {
        dut.clk=0;dut.eval();dut.clk=1;dut.eval();++cycles;
        require(!dut.capacity_fault,"Direct INT32 store reported a capacity fault");
    }
    void reset() {
        dut.rst_n=0;dut.frame_request=0;dut.frame_accept=0;dut.write_valid=0;
        dut.write_frame_end=0;dut.replay_trigger=0;
        tick();tick();dut.rst_n=1;tick();tick();
        for(auto& frame:frames)frame.clear();
        ++resets;
    }
    std::vector<Row> values(unsigned count) {
        std::vector<Row> rows(count);
        for(auto& row:rows)for(auto& lane:row)lane=random();
        return rows;
    }
    void command(unsigned id,bool initial,bool final,unsigned count) {
        auto next=values(count);
        dut.frame_id=id;dut.frame_rows=count;dut.frame_init=initial;dut.frame_final=final;
        dut.frame_request=1;dut.eval();
        unsigned wait=0;
        while(!dut.frame_ready) {tick();require(++wait<100,"Frame admission did not complete");}
        dut.frame_accept=1;tick();dut.frame_accept=0;dut.frame_request=0;
        if(!initial) {
            require(frames[id].size()==count,"Reference frame length differs");
            for(unsigned edge=0;edge<10;++edge)tick();
            dut.replay_trigger=1;tick();dut.replay_trigger=0;
            unsigned row=0,timeout=0;bool streaming=false;
            while(row<count) {
                tick();require(++timeout<count+32,"Frame replay did not complete");
                if(dut.replay_valid) {
                    for(unsigned lane=0;lane<16;++lane) {
                        require(dut.replay_data[lane]==frames[id][row][lane],"Recovered INT32 value differs");
                        ++checked;
                    }
                    ++row;streaming=true;
                } else require(!streaming,"Direct INT32 replay stream stalled");
            }
        }
        if(!final) {
            for(const auto& row:next) {
                if((random()&3U)==0)tick();
                for(unsigned lane=0;lane<16;++lane)dut.write_data[lane]=row[lane];
                dut.write_valid=1;tick();dut.write_valid=0;
            }
        }
        dut.write_frame_end=1;tick();dut.write_frame_end=0;
        wait=0;
        while(!dut.frame_complete) {tick();require(++wait<100,"Frame completion did not arrive");}
        if(final)frames[id].clear();else frames[id]=std::move(next);
        ++commands;
    }
    void pressure() {
        dut.frame_request=1;dut.frame_id=4;dut.frame_rows=1;dut.frame_init=1;dut.frame_final=0;
        for(unsigned edge=0;edge<5;++edge) {
            dut.eval();require(dut.frame_pressure && !dut.frame_ready,"Out-of-capacity frame was admitted");
            tick();++pressure_checks;
        }
        dut.frame_request=0;tick();
    }
    void run() {
        for(unsigned linear=0;linear<8192;++linear) {
            dut.inspect_linear=linear;dut.eval();
            for(unsigned index=0;index<3;++index) {
                require(dut.inspect_quotient[index]==linear/(index+5),"Initial row address differs");
                require(dut.inspect_remainder[index]==linear%(index+5),"Initial bank address differs");
            }
        }
        constexpr std::array<unsigned,7> sizes{1,2,7,16,31,47,64};
        for(unsigned epoch=0;epoch<sizes.size();++epoch) {
            reset();
            for(unsigned id=0;id<4;++id)command(id,true,false,sizes[(epoch+id)%sizes.size()]);
            pressure();
            for(unsigned round=0;round<12;++round) {
                std::array<unsigned,4> ids{0,1,2,3};std::shuffle(ids.begin(),ids.end(),random);
                for(auto id:ids)command(id,false,false,frames[id].size());
            }
            for(unsigned id=4;id--;)command(id,false,true,frames[id].size());
        }
        reset();command(0,true,false,64);reset();command(0,true,false,47);command(0,false,true,47);
        std::cout<<"{\"passed\":true,\"commands\":"<<commands
            <<",\"address_cases\":24576,\"checked_read_int32\":"<<checked<<",\"pressure_checks\":"<<pressure_checks
            <<",\"reset_cases\":"<<resets<<",\"cycles\":"<<cycles<<"}\n";
    }
};

int main(int argc,char** argv) {
    Verilated::commandArgs(argc,argv);
    try {Test test;test.run();return 0;}
    catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
