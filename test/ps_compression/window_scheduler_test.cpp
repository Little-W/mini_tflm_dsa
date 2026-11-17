#include "Vps_window_scheduler.h"
#include "verilated.h"
#include "window_scheduler_ref.hpp"
#include <array>
#include <iostream>
#include <random>

namespace {
void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
struct Simulation {
    VerilatedContext context;
    Vps_window_scheduler dut{&context};
    void tick() {
        dut.clk=0;dut.eval();context.timeInc(1);
        dut.clk=1;dut.eval();context.timeInc(1);
    }
    Simulation() {
        dut.rst_n=0;dut.start=0;dut.done_ready=0;dut.slice_tiles=0;
        dut.command_ready=0;dut.command_pressure=0;dut.command_complete=0;
        tick();tick();dut.rst_n=1;tick();
    }
};
void compare(const Vps_window_scheduler& dut,const ps_schedule::Command& c) {
    check(dut.frame_id==c.frame_id && dut.p0==c.p0 && dut.q0==c.q0 && dut.column0==c.column0 &&
          dut.rows==c.rows && dut.cols==c.cols && dut.count_k==c.reduction &&
          bool(dut.frame_init)==c.init && bool(dut.frame_final)==c.final,
          "RTL frame command differs from the independent scheduler");
}
}
int main(int argc,char** argv) {
    try {
        Verilated::commandArgs(argc,argv);
        Simulation s;std::mt19937 rng(20261116);
        std::uint64_t total_commands=0,total_pressure=0,early_finishes=0;
        for (unsigned test=0;test<321;++test) {
            ps_schedule::Config cfg;
            if (!test) cfg={16,80,48,1,5};
            else cfg={1U+unsigned(rng()%193),1U+unsigned(rng()%269),1U+unsigned(rng()%129),
                      1U<<(test%3),1U+test%16};
            unsigned depth=std::min(cfg.stream_rows,16*cfg.reuse_rows)*(1+unsigned(rng()%4));
            if (!test) depth=20;
            std::array<std::array<unsigned,4>,16> occupied{};
            std::array<unsigned,4> used{};
            ps_schedule::WindowScheduler reference;
            reference.start(cfg);
            check(s.dut.ready,"RTL scheduler was not ready for another job");
            s.dut.stream_rows=cfg.stream_rows;s.dut.stationary_rows=cfg.stationary_rows;
            s.dut.reduction=cfg.reduction;s.dut.reuse_rows=cfg.reuse_rows;s.dut.window_frames=cfg.window_frames;
            s.dut.config_error=0;s.dut.start=1;s.tick();s.dut.start=0;
            unsigned early=0;
            while(!reference.done()) {
                unsigned wait=0;
                while(!s.dut.command_valid) {check(++wait<8,"RTL scheduler stopped making progress");s.tick();}
                const auto c=*reference.candidate();compare(s.dut,c);
                bool admit=true;
                for(unsigned b=0;b<4;++b)
                    if(!c.final && depth-used[b]+occupied[c.frame_id][b]<c.rows) admit=false;
                if(!admit) {
                    reference.pressure();s.dut.command_pressure=1;s.tick();s.dut.command_pressure=0;
                    ++total_pressure;continue;
                }
                const bool drain=reference.phase()==ps_schedule::Phase::Draining;
                reference.accept();s.dut.command_ready=1;s.tick();s.dut.command_ready=0;
                for(unsigned delay=unsigned(rng()%5);delay;--delay) {
                    check(s.dut.command_active && !s.dut.command_valid,"Accepted RTL command did not remain active");
                    compare(s.dut,c);s.tick();
                }
                for(unsigned b=0;b<4;++b) {
                    used[b]-=occupied[c.frame_id][b];
                    unsigned count=c.final?0:unsigned(rng()%(c.rows+1));
                    if(!test && !c.final) count=c.frame_id==4?16:((b==2*(c.frame_id%2)||b==2*(c.frame_id%2)+1)?1:0);
                    occupied[c.frame_id][b]=count;used[b]+=count;
                    check(used[b]<=depth,"RAW admission allowed a bank capacity overflow");
                }
                if(drain && c.final) {++early;++early_finishes;}
                reference.complete();
                if(s.dut.lookahead_valid) {
                    const auto predicted=reference.candidate();
                    check(predicted.has_value(), "Stationary prefetch predicts work after completion");
                    check(s.dut.lookahead_q0==predicted->q0 &&
                          s.dut.lookahead_column==predicted->column0 &&
                          s.dut.lookahead_cols==predicted->cols &&
                          s.dut.lookahead_count_k==predicted->reduction,
                          "Stationary prefetch descriptor differs from the next scheduled command");
                }s.dut.command_complete=1;s.tick();s.dut.command_complete=0;
                ++total_commands;
            }
            unsigned wait=0;
            while(!s.dut.done_valid) {check(++wait<8,"RTL did not finish the completed job");s.tick();}
            check(s.dut.err_code==0 && !s.dut.command_active,"RTL job failed or retained an active command");
            check(s.dut.stat_commands==reference.statistics().commands &&
                  s.dut.stat_pressure_events==reference.statistics().pressures &&
                  s.dut.stat_early_finish_frames==early,"RTL scheduler statistics differ");
            for(auto count:used)check(count==0,"A completed job retained partial-sum allocation");
            s.dut.done_ready=1;s.tick();s.dut.done_ready=0;
        }
        for(unsigned kind=0;kind<4;++kind) {
            s.dut.stream_rows=kind==0?0:16;s.dut.stationary_rows=16;s.dut.reduction=17;
            s.dut.reuse_rows=1;s.dut.window_frames=kind==1?17:1;
            s.dut.config_error=kind>=2?kind-1:0;s.dut.start=1;s.tick();s.dut.start=0;
            check(s.dut.done_valid && s.dut.err_code==(kind>=2?kind-1:1),"Invalid scheduler configuration was accepted");
            s.dut.done_ready=1;s.tick();s.dut.done_ready=0;
        }
        std::cout<<"{\"passed\":true,\"cases\":321,\"commands\":"<<total_commands
                 <<",\"pressure_events\":"<<total_pressure<<",\"early_finish_frames\":"<<early_finishes
                 <<",\"invalid_configurations\":4}\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
