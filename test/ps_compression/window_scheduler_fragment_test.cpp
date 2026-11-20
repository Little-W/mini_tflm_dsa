#include "Vps_window_scheduler.h"
#include "verilated.h"
#include "window_scheduler_ref.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

namespace {
void check(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
struct Simulation {
    VerilatedContext context;
    Vps_window_scheduler dut{&context};
    void tick() {
        dut.clk=0; dut.eval(); context.timeInc(1);
        dut.clk=1; dut.eval(); context.timeInc(1);
    }
    Simulation() {
        dut.rst_n=0; dut.start=0; dut.done_ready=0;
        dut.command_ready=0; dut.command_pressure=0; dut.command_complete=0;
        tick(); tick(); dut.rst_n=1; tick();
    }
};
struct Totals {
    std::uint64_t cases=0, commands=0, triplets=0, pressures=0;
    std::uint64_t opening_pressures=0, update_pressures=0, early_finishes=0;
    std::uint64_t frame_id_reuses=0, tail_frames=0, reserve_checks=0, bank_checks=0;
    std::uint64_t raw_cases=0, word_rotation_cases=0, bounded_bank_cases=0;
    std::array<unsigned,4> peak_bank_words{};
} totals;
struct LiveFrame {
    bool live=false, used_before=false;
    unsigned p0=0, column0=0, rows=0, reserve=0, next_k=0;
};
using Key=std::tuple<unsigned,unsigned,unsigned>;

std::string context(const ps_schedule::Config& cfg, unsigned index) {
    std::ostringstream out;
    out << "case=" << index << " M=" << cfg.stream_rows << " N=" << cfg.stationary_rows
        << " K=" << cfg.reduction << " R=" << cfg.reuse_rows << " W=" << cfg.window_frames
        << " slice=" << cfg.slice_tiles << ": ";
    return out.str();
}
void compare(const Vps_window_scheduler& dut,const ps_schedule::Command& c,const std::string& label) {
    if (dut.frame_id!=c.frame_id || dut.p0!=c.p0 || dut.q0!=c.q0 || dut.column0!=c.column0 ||
        dut.rows!=c.rows || dut.cols!=c.cols || dut.count_k!=c.reduction ||
        bool(dut.frame_init)!=c.init || bool(dut.frame_final)!=c.final || dut.reserve_rows!=c.reserve_rows) {
        std::ostringstream out;
        out << label << "command mismatch: expected id/p/q/col/rows/cols/k/reserve="
            << c.frame_id << '/' << c.p0 << '/' << c.q0 << '/' << c.column0 << '/'
            << c.rows << '/' << c.cols << '/' << c.reduction << '/' << c.reserve_rows
            << ", actual=" << unsigned(dut.frame_id) << '/' << dut.p0 << '/' << dut.q0 << '/'
            << dut.column0 << '/' << dut.rows << '/' << dut.cols << '/' << dut.count_k << '/'
            << dut.reserve_rows;
        throw std::runtime_error(out.str());
    }
}

void run_case(Simulation& s,const ps_schedule::Config& cfg,unsigned index,
              unsigned pattern,std::mt19937& rng) {
    const auto label=context(cfg,index);
    const unsigned group_size=16*cfg.reuse_rows;
    const unsigned slice_size=16*(cfg.slice_tiles ? cfg.slice_tiles : cfg.reuse_rows);
    const unsigned max_reserve=std::min({slice_size,group_size,cfg.stream_rows});
    const unsigned depth=max_reserve*(1+unsigned(rng()%4)) + unsigned(rng()%3);
    const unsigned mt=(cfg.stream_rows+15)/16, nt=(cfg.stationary_rows+15)/16;
    const unsigned kt=(cfg.reduction+15)/16;
    std::vector<std::uint8_t> computed(std::size_t(mt)*nt*kt,0);
    std::array<std::array<unsigned,4>,16> occupied{};
    std::array<unsigned,4> used{};
    std::array<LiveFrame,16> frames{};
    std::set<Key> initialized;
    unsigned rotation=0;
    ps_schedule::WindowScheduler reference;
    reference.start(cfg);
    check(s.dut.ready,label+"scheduler is not ready");
    s.dut.stream_rows=cfg.stream_rows; s.dut.stationary_rows=cfg.stationary_rows;
    s.dut.reduction=cfg.reduction; s.dut.reuse_rows=cfg.reuse_rows;
    s.dut.window_frames=cfg.window_frames; s.dut.slice_tiles=cfg.slice_tiles;
    s.dut.config_error=0; s.dut.start=1; s.tick(); s.dut.start=0;
    unsigned early=0, commands=0, iterations=0;
    while(!reference.done()) {
        check(++iterations<computed.size()*5+100,label+"scheduler failed to make bounded progress");
        unsigned wait=0;
        while(!s.dut.command_valid) {
            check(!s.dut.done_valid,label+"scheduler ended before completing every tile");
            check(++wait<16,label+"scheduler stopped making progress");
            s.tick();
        }
        const auto candidate=reference.candidate();
        check(candidate.has_value(),label+"reference has no available command");
        const auto c=*candidate;
        compare(s.dut,c,label);
        const unsigned group_base=(c.p0/group_size)*group_size;
        const unsigned group_end=std::min(cfg.stream_rows,group_base+group_size);
        const unsigned group_reserve=std::min(slice_size,group_end-group_base);
        check(c.p0%16==0 && c.q0%16==0 && c.column0%16==0,label+"tile origin is not aligned");
        check(c.rows && c.rows<=group_end-c.p0,label+"a slice crosses its R group");
        check(c.reserve_rows==group_reserve && c.rows<=c.reserve_rows,label+"tail reserve differs within a group");
        check(c.cols==std::min(16U,cfg.stationary_rows-c.column0),label+"stationary tail is incorrect");
        check(c.reduction==std::min(16U,cfg.reduction-c.q0),label+"K tail is incorrect");
        ++totals.reserve_checks;

        // Hold the request without accepting it; every descriptor field must remain stable.
        for(unsigned delay=unsigned(rng()%3);delay;--delay) {
            check(s.dut.command_valid && !s.dut.command_active,label+"unaccepted command changed state");
            compare(s.dut,c,label); s.tick();
        }
        bool admit=true;
        const unsigned budget=c.reserve_rows;
        for(unsigned bank=0;bank<4;++bank) {
            check(used[bank]<=depth,label+"bank occupancy exceeded its capacity");
            if(!c.final && depth-used[bank]+occupied[c.frame_id][bank]<budget) admit=false;
            ++totals.bank_checks;
        }
        if(!admit) {
            const auto phase=reference.phase();
            const auto before=s.dut.stat_commands;
            const auto rejected_q=c.q0;
            reference.pressure();
            s.dut.command_pressure=1; s.tick(); s.dut.command_pressure=0;
            check(!s.dut.command_active && s.dut.stat_commands==before,
                  label+"rejected request started or completed computation");
            check(frames[c.frame_id].next_k==rejected_q || c.init,
                  label+"pressure changed the frame's K progress");
            ++totals.pressures;
            if(phase==ps_schedule::Phase::Opening) ++totals.opening_pressures;
            else ++totals.update_pressures;
            continue;
        }
        auto& frame=frames[c.frame_id];
        const Key key{c.p0,c.column0,c.rows};
        if(c.init) {
            check(!frame.live && c.q0==0,label+"frame ID initialized over live PS");
            check(initialized.insert(key).second,label+"output frame was recomputed from K zero");
            if(frame.used_before) ++totals.frame_id_reuses;
        } else {
            check(frame.live && frame.p0==c.p0 && frame.column0==c.column0 && frame.rows==c.rows,
                  label+"frame ID points to a different output slice");
            check(frame.next_k==c.q0 && frame.reserve==c.reserve_rows,
                  label+"reused frame ID has incorrect K progress or reservation");
        }
        const bool draining=reference.phase()==ps_schedule::Phase::Draining;
        reference.accept(); s.dut.command_ready=1; s.tick(); s.dut.command_ready=0;
        for(unsigned delay=1+unsigned(rng()%5);delay;--delay) {
            check(s.dut.command_active && !s.dut.command_valid,label+"accepted command was not retained");
            compare(s.dut,c,label); s.tick();
        }
        std::array<unsigned,4> next_words{};
        const unsigned frame_length=c.rows;
        if(!c.final) {
            if(pattern==0) next_words.fill(frame_length);
            else if(pattern==1) {
                for(unsigned row=0;row<frame_length;++row) {
                    const unsigned words=row==0 ? 2+unsigned(rng()%3) : unsigned(rng()%5);
                    for(unsigned word=0;word<words;++word) ++next_words[(rotation+word)%4];
                    rotation=(rotation+words)%4;
                }
            } else {
                // Each row can occupy at most one word in each bank. These bounded
                // patterns also stress bank imbalance independently of a codec.
                for(unsigned bank=0;bank<4;++bank) next_words[bank]=unsigned(rng()%(frame_length+1));
            }
        }
        for(unsigned bank=0;bank<4;++bank) {
            check(used[bank]>=occupied[c.frame_id][bank],label+"old allocation was freed twice");
            used[bank]-=occupied[c.frame_id][bank];
            occupied[c.frame_id][bank]=next_words[bank];
            used[bank]+=next_words[bank];
            check(used[bank]<=depth,label+"RAW reservation admitted a bank overflow");
            totals.peak_bank_words[bank]=std::max(totals.peak_bank_words[bank],used[bank]);
            ++totals.bank_checks;
        }
        for(unsigned row_tile=c.p0/16;row_tile<(c.p0+c.rows+15)/16;++row_tile) {
            const auto address=(std::size_t(row_tile)*nt+c.column0/16)*kt+c.q0/16;
            check(address<computed.size() && computed[address]==0,label+"an M/N/K tile was computed twice");
            computed[address]=1;
            ++totals.triplets;
        }
        frame={ !c.final, true, c.p0, c.column0, c.rows, c.reserve_rows, c.q0+c.reduction };
        if(c.init && c.rows<c.reserve_rows) ++totals.tail_frames;
        if(draining && c.final) {++early; ++totals.early_finishes;}
        reference.complete();
                if(s.dut.lookahead_valid) {
                    const auto predicted=reference.candidate();
                    check(predicted.has_value(), "Stationary prefetch predicts work after completion");
                    check(s.dut.lookahead_q0==predicted->q0 &&
                          s.dut.lookahead_column==predicted->column0 &&
                          s.dut.lookahead_cols==predicted->cols &&
                          s.dut.lookahead_count_k==predicted->reduction,
                          "Stationary prefetch descriptor differs from the next scheduled command");
                } s.dut.command_complete=1; s.tick(); s.dut.command_complete=0;
        ++commands; ++totals.commands;
    }
    unsigned wait=0;
    while(!s.dut.done_valid) {check(++wait<16,label+"completed job did not report done");s.tick();}
    check(s.dut.err_code==0 && !s.dut.command_active,label+"completed job reports an error");
    check(s.dut.stat_commands==commands && commands==reference.statistics().commands &&
          s.dut.stat_pressure_events==reference.statistics().pressures &&
          s.dut.stat_early_finish_frames==early,label+"statistics mismatch");
    check(std::all_of(computed.begin(),computed.end(),[](auto value){return value==1;}),
          label+"not every M/N/K tile was computed exactly once");
    for(auto count:used) check(count==0,label+"completed job retains PS payload");
    for(const auto& frame:frames) check(!frame.live,label+"completed job retains a live frame ID");
    s.tick(); check(s.dut.done_valid,label+"completion was not held for done_ready");
    s.dut.done_ready=1; s.tick(); s.dut.done_ready=0;
    ++totals.cases;
    if(pattern==0) ++totals.raw_cases;
    else if(pattern==1) ++totals.word_rotation_cases;
    else ++totals.bounded_bank_cases;
}
} // namespace

int main(int argc,char** argv) {
    try {
        Verilated::commandArgs(argc,argv);
        Simulation simulation;
        std::mt19937 rng(20261117);
        const bool irregular_only=argc>1 && std::string(argv[1])=="--irregular-only";
        const unsigned max_reuse=argc>1 && std::string(argv[1])=="--max-reuse-4" ? 4 : 0;
        unsigned cases1=0,cases2=0,directed=0;
        if(!irregular_only) {
            for(unsigned slice:{1U,2U})
                for(unsigned test=0;test<321;++test) {
                    ps_schedule::Config cfg;
                    cfg.stream_rows=1+unsigned(rng()%193);
                    cfg.stationary_rows=1+unsigned(rng()%269);
                    cfg.reduction=1+unsigned(rng()%129);
                    cfg.reuse_rows=std::max(slice,1U<<(test%3));
                    cfg.window_frames=1+test%16;
                    cfg.slice_tiles=slice;
                    run_case(simulation,cfg,unsigned(totals.cases),test%3,rng);
                    if(slice==1) ++cases1; else ++cases2;
                }
        }
        const std::vector<ps_schedule::Config> directed_cases={
            {97,49,35,3,4,2}, {55,65,65,4,4,1}, {55,65,65,4,4,2},
            {401,35,49,25,16,2}, {417,49,65,25,8,2}, {49,17,17,3,16,2},
            {97,49,35,3,4,1}, {33,33,1,4,16,1}, {33,33,16,4,16,2},
            {65,17,17,4,16,1}, {65,17,33,4,16,2}, {1,269,129,4,16,1}
        };
        for(const auto& cfg:directed_cases) {
            if(max_reuse && cfg.reuse_rows>max_reuse) continue;
            run_case(simulation,cfg,unsigned(totals.cases),directed%3,rng);
            ++directed;
        }
        if(!irregular_only) {
            check(totals.opening_pressures && totals.update_pressures && totals.early_finishes,
                  "The corpus must exercise opening pressure, update pressure and protected completion");
            check(totals.frame_id_reuses && totals.tail_frames,"The corpus must reuse frame IDs and process short tails");
        }
        std::cout << "{\"passed\":true,\"cases\":" << totals.cases
                  << ",\"slice_1_cases\":" << cases1 << ",\"slice_2_cases\":" << cases2
                  << ",\"directed_cases\":" << directed << ",\"commands\":" << totals.commands
                  << ",\"mnk_tile_checks\":" << totals.triplets << ",\"pressure_events\":" << totals.pressures
                  << ",\"opening_pressures\":" << totals.opening_pressures
                  << ",\"update_pressures\":" << totals.update_pressures
                  << ",\"early_finish_frames\":" << totals.early_finishes
                  << ",\"frame_id_reuses\":" << totals.frame_id_reuses
                  << ",\"tail_frames\":" << totals.tail_frames
                  << ",\"reserve_checks\":" << totals.reserve_checks
                  << ",\"bank_checks\":" << totals.bank_checks
                  << ",\"raw_cases\":" << totals.raw_cases
                  << ",\"word_rotation_cases\":" << totals.word_rotation_cases
                  << ",\"bounded_bank_cases\":" << totals.bounded_bank_cases
                  << ",\"peak_bank_words\":[" << totals.peak_bank_words[0] << ',' << totals.peak_bank_words[1]
                  << ',' << totals.peak_bank_words[2] << ',' << totals.peak_bank_words[3] << "]}\n";
    } catch(const std::exception& error) {std::cerr << error.what() << '\n';return 1;}
}
