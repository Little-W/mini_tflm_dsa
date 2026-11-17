#include "Vdip_weight_tb.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>

constexpr unsigned N=TEST_SIZE, WIDTH=TEST_WEIGHT_WIDTH;
static void require(bool ok,const std::string &message) {
    if(!ok) throw std::runtime_error(message);
}
static std::int32_t signed_bits(std::uint32_t value,unsigned bits) {
    const std::uint32_t mask=(1U<<bits)-1U;
    value&=mask;
    return value&(1U<<(bits-1U)) ? std::int32_t(value)-std::int32_t(1U<<bits) : std::int32_t(value);
}
struct Tile {unsigned id,lanes,reduction;bool is_mode;};
static std::int32_t coefficient(const Tile &tile,unsigned lane,unsigned k) {
    if(lane>=tile.lanes || k>=tile.reduction) return 0;
    std::uint32_t value=(tile.id+1U)*0x2845f9U+lane*0x273bc1U+k*0x5197U;
    value^=value>>13;
    return signed_bits(value,tile.is_mode?WIDTH:8U);
}
struct Send {Tile tile;unsigned physical_row=N-1U;};
using Vector=std::array<std::uint32_t,N>;

class Check {
public:
    Vdip_weight_tb dut;
    std::mt19937 random{0x8134573U};
    std::deque<Send> sends;
    std::deque<Vector> sums;
    std::optional<Tile> active;
    std::array<std::optional<Tile>,N> row_tiles;
    std::array<bool,N> row_select{};
    bool input_select=false;
    unsigned stream_remaining=0,input_index=0;
    std::uint64_t cycles=0,weight_vectors=0,weight_checks=0,result_rows=0,result_checks=0;
    std::uint64_t shadow_checks=0,commits=0,ws_tiles=0,is_tiles=0,tail_tiles=0;
    std::uint64_t mixed_valid_cycles=0,select_checks=0;

    Check() {
        dut.rst_n=0;
        dut.cache_flush=dut.discard_head=dut.load_start=dut.row_valid=dut.load_done=dut.send_start=0;
        dut.weight_commit=dut.input_valid=0;
        tick();tick();dut.rst_n=1;tick();
    }
    void tick() {
        dut.input_valid=stream_remaining && random()%5U!=0U;
        if(dut.input_valid) {
            require(active.has_value(),"A stream needs committed weights");
            Vector golden{};
            std::array<std::int32_t,N> x{};
            for(unsigned k=0;k<N;++k) {
                const auto value=std::uint32_t(input_index*0x713bU+k*0x25a9U+active->id*0x9283U);
                x[k]=signed_bits(value,active->is_mode?8U:16U);
                dut.input_row[k]=std::uint16_t(x[k]);
            }
            for(unsigned c=0;c<N;++c) {
                const std::uint32_t seed=0x7fff0000U+input_index*0x713U+c*0x473U;
                dut.initial_sum[c]=seed;
                std::int64_t sum=seed;
                for(unsigned k=0;k<N;++k) sum+=std::int64_t(x[k])*coefficient(*active,c,k);
                golden[c]=std::uint32_t(sum);
            }
            sums.push_back(golden);--stream_remaining;++input_index;
        } else {
            for(unsigned c=0;c<N;++c) {dut.input_row[c]=0;dut.initial_sum[c]=0;}
        }
        dut.clk=0;dut.eval();
        if(dut.store_weight_req) {
            require(!sends.empty(),"An unrequested weight vector reached the array");
            auto &send=sends.front();
            for(unsigned c=0;c<N;++c) {
                const unsigned k=(send.physical_row+c)%N;
                require(signed_bits(dut.weight_out[c],WIDTH)==coefficient(send.tile,c,k),
                        "Weight permutation differs at row "+std::to_string(send.physical_row)+
                        " lane "+std::to_string(c));
                ++weight_checks;
            }
            require(bool(dut.weight_sending_done)==(send.physical_row==0),"Weight completion phase differs");
            if(send.physical_row) --send.physical_row;
            else sends.pop_front();
            ++weight_vectors;
        } else require(!dut.weight_sending_done,"Weight completion requires a final vector");
        if (!dut.rst_n) {
            row_tiles={}; row_select={}; input_select=false;
        } else {
            if (dut.weight_commit) input_select=!input_select;
            for (unsigned row=N-1;row>0;--row) {
                row_tiles[row]=row_tiles[row-1]; row_select[row]=row_select[row-1];
            }
            row_tiles[0]=dut.input_valid ? active : std::nullopt;
            row_select[0]=input_select;
        }
        dut.clk=1;dut.eval();++cycles;
        if(dut.output_valid) {
            require(!sums.empty(),"An unexpected output row reached writeback");
            for(unsigned c=0;c<N;++c) {
                require(dut.output_row[c]==sums.front()[c],
                        "Matrix product differs at cycle "+std::to_string(cycles)+" lane "+std::to_string(c));
                ++result_checks;
            }
            sums.pop_front();++result_rows;
        }
        bool select_zero=false,select_one=false;
        for(unsigned r=0;r<N;++r) {
            require(bool(dut.row_select&(1U<<r))==row_select[r],"Row selector timing differs");
            require(bool(dut.valid_pipe&(1U<<r))==row_tiles[r].has_value(),"Row valid timing differs");
            ++select_checks;
            if(row_tiles[r]) {
                select_zero|=!row_select[r];select_one|=row_select[r];
                for(unsigned c=0;c<N;++c) {
                    require(signed_bits(dut.resident_weight[r*N+c],WIDTH)==coefficient(*row_tiles[r],c,(r+c)%N),
                            "Preloading changed a weight used by a valid physical row");
                    ++shadow_checks;
                }
            }
        }
        mixed_valid_cycles+=select_zero&&select_one;
    }
    template<class Predicate> void wait(Predicate predicate,const std::string &reason) {
        for(unsigned i=0;!predicate();++i) {require(i<10000,reason+" timed out");tick();}
    }
    void idle(unsigned count) {while(count--)tick();}
    void start_load() {
        wait([&]{return bool(dut.load_ready);},"Load admission");
        dut.load_start=1;tick();dut.load_start=0;
    }
    void load_row(const Tile &tile,unsigned lane,bool final) {
        dut.row_idx=lane;dut.row_valid=1;dut.load_done=final;
        for(unsigned k=0;k<N;++k) dut.row_data[k]=std::uint16_t(coefficient(tile,lane,k));
        tick();dut.row_valid=dut.load_done=0;
    }
    void load(const Tile &tile) {
        start_load();
        for(unsigned c=0;c<tile.lanes;++c) {
            if(random()%3U==0U)idle(random()%3U);
            load_row(tile,c,c+1U==tile.lanes);
        }
        idle(2);
    }
    void send(const Tile &tile) {
        wait([&]{return bool(dut.weight_data_valid);},"Send admission");
        sends.push_back({tile,N-1});dut.send_start=1;tick();dut.send_start=0;
        wait([&]{return sends.empty();},"Weight vector emission");
    }
    void drain() {wait([&]{return !stream_remaining && sums.empty();},"Array drain");}
    void finish_input() {wait([&]{return !stream_remaining;},"Input completion");}
    void commit(const Tile &tile) {
        finish_input();require(sends.empty(),"Commit requires a complete shadow tile");
        active=tile;dut.weight_commit=1;tick();dut.weight_commit=0;++commits;
        ws_tiles+=!tile.is_mode;is_tiles+=tile.is_mode;
        tail_tiles+=tile.lanes<N || tile.reduction<N;
    }
    void stream(unsigned count) {require(!stream_remaining,"A stream is already active");stream_remaining=count;}
    void flush() {dut.cache_flush=1;tick();dut.cache_flush=0;idle(2);}
};

int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Check check;
        Tile a{1,N,N,false},b{2,N-1U,N-1U,true};
        check.load(a);check.load(b);
        require(!check.dut.load_ready,"Two queued tiles must fill both slots");
        check.send(a);check.commit(a);check.stream(3*N+7);
        check.send(b);check.commit(b);check.stream(2*N+1);check.drain();
        for(unsigned trial=0;trial<64;++trial) {
            Tile next{trial+3,1U+unsigned(check.random()%N),1U+unsigned(check.random()%N),bool(trial&1U)};
            check.stream(5*N+11);
            check.load(next);check.send(next);
            check.commit(next);check.stream(N+3);check.drain();
        }
        Tile discarded{101,N,N,false},kept{102,1,N/2+1,true};
        check.load(discarded);check.load(kept);
        check.wait([&]{return bool(check.dut.discard_ready);},"Discard admission");
        check.dut.discard_head=1;check.tick();check.dut.discard_head=0;
        check.send(kept);check.commit(kept);check.stream(N+1);check.drain();
        check.start_load();check.load_row(discarded,0,false);check.flush();
        require(!check.dut.weight_data_valid && check.dut.load_ready,"Flush must empty the load queue");
        check.load(a);check.send(a);check.commit(a);check.stream(N+1);check.drain();
        require(check.ws_tiles && check.is_tiles && check.tail_tiles && check.shadow_checks && check.mixed_valid_cycles,
                "Required DiP weight scenarios did not execute");
        std::cout<<"{\"passed\":true,\"size\":"<<N<<",\"weight_width\":"<<WIDTH
                 <<",\"weight_vectors\":"<<check.weight_vectors<<",\"weight_checks\":"<<check.weight_checks
                 <<",\"result_rows\":"<<check.result_rows<<",\"result_checks\":"<<check.result_checks
                 <<",\"shadow_checks\":"<<check.shadow_checks<<",\"commits\":"<<check.commits
                 <<",\"ws_tiles\":"<<check.ws_tiles<<",\"is_tiles\":"<<check.is_tiles
                 <<",\"tail_tiles\":"<<check.tail_tiles
                 <<",\"mixed_valid_cycles\":"<<check.mixed_valid_cycles
                 <<",\"select_checks\":"<<check.select_checks<<"}\n";
    } catch(const std::exception &error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
