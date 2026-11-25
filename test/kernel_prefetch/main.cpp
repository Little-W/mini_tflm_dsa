#include "Vkernel_prefetch_tb.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr unsigned bus_bytes=TEST_BUS_WIDTH/8;
static void require(bool condition,const std::string &message) {
    if(!condition) throw std::runtime_error(message);
}
static std::int32_t sign16(std::uint32_t value) {
    value&=65535U;return value>=32768U?std::int32_t(value)-65536:std::int32_t(value);
}
struct Tag {
    std::uint32_t base=0x10000,stride=256,p0=0,q0=0,group=0,rows=16,cols=16;
    std::int32_t zp=0;
    bool use16=false,im2col=false,packed=false;
    bool operator==(const Tag&) const=default;
};
static std::string describe(const Tag &t) {
    return "base="+std::to_string(t.base)+" stride="+std::to_string(t.stride)+
        " p0="+std::to_string(t.p0)+" q0="+std::to_string(t.q0)+
        " group="+std::to_string(t.group)+" rows="+std::to_string(t.rows)+
        " cols="+std::to_string(t.cols)+" zp="+std::to_string(t.zp)+
        " s16="+std::to_string(t.use16)+" im2col="+std::to_string(t.im2col);
}
static std::int32_t memory_value(const Tag &t,unsigned row,unsigned column) {
    std::uint32_t address=t.base+t.stride*row+(t.use16?2U:1U)*column;
    if(t.im2col) address+=(t.p0+row)*0x9185U+(t.q0+column)*0x714bU+t.group*0x2483U;
    std::uint32_t value=address*0x45d9f3bU;
    value=(value^(value>>15))*0x119de1f3U;value^=value>>13;
    std::int32_t raw=t.use16?sign16(value):std::int32_t(value&255U)-128;
    return sign16(std::uint32_t(raw+t.zp));
}
static std::int32_t output_value(const Tag &t,unsigned row,unsigned column) {
    return row<t.rows && column<t.cols?memory_value(t,row,column):0;
}
struct ExpectedDma {Tag tag;bool prefetch=false;unsigned delay=0;};
struct Transfer {ExpectedDma expected;unsigned row=0,column=0,wait=0,slot=0;};
struct ExpectedSend {Tag tag;unsigned column=15;};

class Check {
public:
    Vkernel_prefetch_tb dut;
    std::mt19937 random{0x1794ba51U};
    std::deque<ExpectedDma> dma_expected;
    std::deque<ExpectedSend> sends_expected;
    std::optional<Transfer> transfer,queued_transfer;
    bool grant_enabled=true,random_waits=true;
    std::uint64_t cycles=0,dma_starts=0,dma_completions=0,prefetch_starts=0;
    std::uint64_t captures=0,hits=0,discards=0,logical_loads=0,tiles_sent=0,checked_values=0;
    std::uint64_t ram_write_words=0,ram_read_words=0,overlap_cycles=0,max_valid_slots=0;
    std::uint64_t max_dma_contexts=0,overlapping_dma_starts=0;
    std::uint64_t default_tiles=0,cached_hit_cases=0,inflight_hit_cases=0,pending_cases=0;
    std::uint64_t mismatch_cases=0,delayed_prediction_cases=0,flush_cases=0,random_cases=0;
    std::uint64_t comparison_change_cases=0,comparison_cancel_cases=0;
    std::uint64_t s8_tiles=0,s16_tiles=0,im2col_tiles=0,tail_tiles=0,flush_drain_cycles=0;

    Check() {reset();}
    void reset() {
        dut.rst_n=0;dut.init_cfg=0;dut.cache_flush=0;dut.cfg_command_mode=0;
        dut.send_weight_trigger=0;dut.prefetch_valid=0;dut.load_weight_granted=0;dut.cfg_tile_packed=0;
        dut.ext_dma_busy=0;dut.ext_dma_done=0;dut.ext_dma_wr_slot=0;
        for(unsigned i=0;i<bus_bytes;++i) {dut.ext_dma_wr_valid[i]=0;dut.ext_dma_wr_data[i]=0;}
        for(unsigned i=0;i<2;++i) {dut.clk=0;dut.eval();dut.clk=1;dut.eval();++cycles;}
        dut.rst_n=1;dut.clk=0;dut.eval();
        transfer.reset();queued_transfer.reset();dma_expected.clear();sends_expected.clear();grant_enabled=true;
    }
    Tag dma_tag() const {
        Tag t;t.base=dut.ext_dma_base_addr;t.stride=dut.ext_dma_row_stride;
        t.p0=dut.ext_dma_p0;t.q0=dut.ext_dma_q0;t.group=dut.ext_dma_group;
        t.rows=dut.ext_dma_rows_to_read;t.cols=dut.dbg_dma_valid_cols;
        const std::uint32_t zp=dut.ext_dma_lhs_zp;
        t.zp=zp<=0x7fffffffU?std::int32_t(zp):std::int32_t(std::int64_t(zp)-0x100000000LL);
        t.use16=dut.ext_dma_use_16bits;t.im2col=dut.ext_dma_im2col;t.packed=dut.dbg_tile_packed;return t;
    }
    void tick() {
        dut.ext_dma_busy=transfer.has_value();dut.ext_dma_done=0;
        for(unsigned lane=0;lane<bus_bytes;++lane) {dut.ext_dma_wr_valid[lane]=0;dut.ext_dma_wr_data[lane]=0;}
        bool response_done=false,response_beat=false;unsigned beat_elements=0;
        if(transfer && transfer->wait==0) {
            auto &active=*transfer;const auto &tag=active.expected.tag;
            dut.ext_dma_wr_slot=active.slot;
            if(active.row==tag.rows) {
                dut.ext_dma_done=1;dut.ext_dma_busy=0;response_done=true;
            } else {
                const unsigned elements=bus_bytes/(tag.use16?2:1);
                const unsigned physical_cols=(tag.im2col||tag.packed)?16:((tag.cols+elements-1)/elements)*elements;
                unsigned chunk=elements;
                if(tag.im2col) chunk=1+random()%elements;
                beat_elements=std::min(chunk,physical_cols-active.column);
                dut.ext_dma_wr_row=active.row;dut.ext_dma_wr_col_base=active.column;
                for(unsigned lane=0;lane<beat_elements;++lane) {
                    const auto col=active.column+lane;
                    dut.ext_dma_wr_valid[lane]=1;
                    const auto value=tag.im2col && col>=tag.cols?0:memory_value(tag,active.row,col);
                    dut.ext_dma_wr_data[lane]=std::uint16_t(value);
                }
                response_beat=true;
            }
        }
        dut.load_weight_granted=0;dut.clk=0;dut.eval();
        if(grant_enabled && (!transfer || (!dut.dbg_managed_mode && !queued_transfer)) &&
                dut.load_weight_req && (!random_waits || random()%4!=0))
            dut.load_weight_granted=1;
        dut.eval();
        std::optional<ExpectedDma> started;
        unsigned started_slot=0;
        if(dut.ext_dma_start) {
            require(!queued_transfer && !dma_expected.empty(),"Unexpected DMA at "+std::to_string(cycles));
            auto expected=dma_expected.front();dma_expected.pop_front();
            const auto actual=dma_tag();
            require(actual==expected.tag,"DMA descriptor differs: "+describe(actual)+" expected "+describe(expected.tag));
            require(bool(dut.dbg_prefetch_start)==expected.prefetch,"DMA demand/prefetch classification differs");
            const unsigned elements=bus_bytes/(actual.use16?2:1);
            require(dut.ext_dma_burst_len_m1==((actual.packed?16:actual.cols)+elements-1)/elements-1,"DMA burst length differs");
            require(!dut.ext_dma_is_write && !dut.ext_dma_linear_read_mode,
                    "Kernel read mode differs");
            started_slot=dut.ext_dma_slot_id;
            if(transfer) {
                require(!dut.dbg_managed_mode && started_slot!=transfer->slot,
                        "Overlapping descriptors share a kernel slot");
                ++overlapping_dma_starts;
            }
            started=expected;++dma_starts;prefetch_starts+=expected.prefetch;
        }
        if(transfer && dut.dbg_managed_mode && !dut.cache_flush)
            require(dma_tag()==transfer->expected.tag,"An in-flight DMA descriptor changed");
        captures+=dut.dbg_prefetch_capture;hits+=dut.dbg_cache_hit;discards+=dut.dbg_discard;
        logical_loads+=dut.load_weight_done;
        if(dut.dbg_raw_done && dut.dbg_transfer_prefetch && !dut.dbg_cache_hit)
            require(!dut.load_weight_done,"A speculative completion advanced demand progress");
        if(dut.cache_flush || dut.dbg_transfer_discard)
            require(!dut.dbg_ram_write_en,"Flushed DMA data wrote the kernel RAM");
        ram_write_words+=unsigned(__builtin_popcount(dut.dbg_ram_write_en));
        ram_read_words+=unsigned(__builtin_popcount(dut.dbg_ram_read_en));
        require(dut.dbg_valid_count<=2,"Kernel buffer exceeded two physical slots");
        max_valid_slots=std::max(max_valid_slots,std::uint64_t(dut.dbg_valid_count));
        overlap_cycles+=bool(transfer)&&bool(dut.store_weight_req);
        flush_drain_cycles+=dut.dbg_transfer_discard;
        if(dut.store_weight_req) {
            require(!sends_expected.empty(),"Unrequested weights reached the array");
            auto &expected=sends_expected.front();
            for(unsigned lane=0;lane<16;++lane) {
                const auto actual=sign16(dut.weight_out[lane]);
                const auto reduction=(expected.column+lane)%16;
                require(actual==output_value(expected.tag,lane,reduction),
                        "Kernel RAM output differs at lane "+std::to_string(lane)+
                        " column "+std::to_string(expected.column)+" cycle "+std::to_string(cycles)+
                        " actual "+std::to_string(actual)+" expected "+
                        std::to_string(output_value(expected.tag,lane,reduction)));
                ++checked_values;
            }
            require(bool(dut.weight_sending_done)==(expected.column==0),"Weight done phase differs");
            if(expected.column==0) {
                s8_tiles+=!expected.tag.use16;s16_tiles+=expected.tag.use16;
                im2col_tiles+=expected.tag.im2col;
                tail_tiles+=expected.tag.rows<16 || expected.tag.cols<16;
                sends_expected.pop_front();++tiles_sent;
            } else --expected.column;
        } else require(!dut.weight_sending_done,"Weight done lacks its final vector");
        dut.clk=1;dut.eval();++cycles;
        if(transfer) {
            auto &active=*transfer;
            if(response_done) {transfer.reset();++dma_completions;}
            else if(active.wait) --active.wait;
            else if(response_beat) {
                const unsigned elements=bus_bytes/(active.expected.tag.use16?2:1);
                const unsigned total=(active.expected.tag.im2col||active.expected.tag.packed)?16:
                    ((active.expected.tag.cols+elements-1)/elements)*elements;
                active.column+=beat_elements;
                if(active.column==total) {active.column=0;++active.row;}
                active.wait=random_waits?random()%3:0;
            }
        }
        if(!transfer && queued_transfer) {transfer=queued_transfer;queued_transfer.reset();}
        if(started) {
            auto next=Transfer{*started,0,0,started->delay+unsigned(random_waits?random()%4:0),started_slot};
            if(transfer) queued_transfer=next;else transfer=next;
        }
        max_dma_contexts=std::max(max_dma_contexts,
            std::uint64_t(transfer.has_value())+std::uint64_t(queued_transfer.has_value()));
    }
    template<class Predicate> void wait(Predicate predicate,const std::string &reason,unsigned limit=5000) {
        for(unsigned count=0;!predicate();++count) {
            require(count<limit,reason+" timed out at "+std::to_string(cycles));tick();
        }
    }
    void idle(unsigned count) {for(unsigned i=0;i<count;++i) tick();}
    void prediction(const std::optional<Tag> &tag) {
        dut.prefetch_valid=tag.has_value();
        if(tag) {
            dut.prefetch_base_addr=tag->base;dut.prefetch_p0=tag->p0;dut.prefetch_q0=tag->q0;
            dut.prefetch_rows=tag->rows;dut.prefetch_valid_cols=tag->cols;
        }
    }
    void configure(const Tag &tag,bool mode=true) {
        require(dut.dbg_top_state==0 && dut.dbg_ctrl_state==0,"A command began before its controller retired");
        dut.cfg_command_mode=mode;dut.cfg_im2col=tag.im2col;dut.cfg_tile_packed=tag.packed;
        dut.cfg_p0_base=tag.p0;dut.cfg_q0_base=tag.q0;
        dut.k=16;dut.n=tag.cols;dut.m=tag.rows;
        dut.rhs_base=tag.base;dut.rhs_row_stride_b=tag.stride;dut.rhs_zp=std::uint32_t(tag.zp);
        dut.use_16bits=tag.use16;dut.ia_reuse_num=1;dut.w_reuse_num=1;
        dut.row_groups=1;dut.row_tail_tiles=1;dut.col_groups=1;dut.col_tail_tiles=1;
        sends_expected.push_back({tag,15});
        dut.init_cfg=1;tick();dut.init_cfg=0;
    }
    void wait_valid() {wait([&]{return bool(dut.weight_data_valid);},"Demand weights");}
    void send() {
        wait_valid();dut.send_weight_trigger=1;tick();dut.send_weight_trigger=0;
    }
    void finish_command(unsigned expected_loads=1) {
        wait([&]{return sends_expected.empty();},"Weight send");
        wait([&]{return dut.dbg_top_state==0 && dut.dbg_ctrl_state==0;},"Kernel controller retirement",100);
        require(dut.dbg_loaded_count==expected_loads && dut.dbg_sent_count==expected_loads,
                "Kernel controller completion counters differ");
    }
    void run(const Tag &tag,bool mode=true) {configure(tag,mode);send();finish_command();}
    void wait_cached() {
        wait([&]{return dut.dbg_prefetch_state==3 && bool(dut.prefetch_idle);},"Prefetched tile commit");
        require(!transfer && !dut.weight_data_valid,"Unconfirmed prefetched weights became visible");
    }
    void finish_case() {
        prediction(std::nullopt);
        wait([&]{return !transfer && bool(dut.prefetch_idle);},"DMA drain");
        require(dma_expected.empty() && sends_expected.empty(),"A case left an expected transaction unfinished");
        require(!dut.weight_data_valid,"A case left unrequested weights visible");
    }
    void flush() {dut.cache_flush=1;tick();dut.cache_flush=0;++flush_cases;}
};

static Tag make_tag(unsigned serial,bool use16=false,bool im2col=false,unsigned rows=16,unsigned cols=16) {
    Tag t;t.base=0x10000U+serial*0x1340U;t.stride=64+(serial%7)*32;t.p0=serial*3;t.q0=serial*16;
    t.rows=rows;t.cols=cols;t.use16=use16;t.im2col=im2col;t.zp=use16?0:std::int32_t(serial%255)-127;
    return t;
}
static Tag next_tag(const Tag &a,unsigned rows=16,unsigned cols=16) {
    auto b=a;b.base+=0x2040;b.p0+=16;b.q0+=16;b.rows=rows;b.cols=cols;return b;
}

int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Check check;
        for(unsigned case_index=0;case_index<24;++case_index) {
            const auto a=make_tag(case_index,case_index%2,case_index%3==0,
                                  1+case_index%16,1+(case_index*7)%16);
            check.prediction(next_tag(a));check.dma_expected.push_back({a,false,case_index%5});
            check.run(a,false);++check.default_tiles;check.finish_case();
        }
        for(unsigned case_index=0;case_index<32;++case_index) {
            auto a=make_tag(500+case_index,case_index%2,false,
                            1+case_index%16,1+(case_index*7)%16);
            a.packed=true;a.stride=16*(a.use16?2:1);
            check.prediction(std::nullopt);check.dma_expected.push_back({a,false,case_index%5});
            check.run(a,case_index>=16);++check.default_tiles;check.finish_case();
        }
        check.dut.cfg_tile_packed=0;
        for(bool use16:{false,true}) {
            const auto a=make_tag(90+use16,use16,false);
            std::vector<Tag> tiles;
            for(unsigned repeat=0;repeat<2;++repeat) for(unsigned reduction=0;reduction<2;++reduction)
                for(unsigned column=0;column<2;++column) {
                    auto t=a;t.base+=column*16*a.stride+reduction*16*(use16?2:1);
                    t.p0+=column*16;t.q0+=reduction*16;t.group=repeat;
                    t.rows=column?7:16;t.cols=reduction?15:16;tiles.push_back(t);
                    check.dma_expected.push_back({t,false,0});check.sends_expected.push_back({t,15});
                }
            check.prediction(next_tag(a));check.dut.cfg_command_mode=0;check.dut.cfg_im2col=0;
            check.dut.cfg_p0_base=a.p0;check.dut.cfg_q0_base=a.q0;
            check.dut.k=35;check.dut.n=31;check.dut.m=23;check.dut.rhs_base=a.base;
            check.dut.rhs_row_stride_b=a.stride;check.dut.rhs_zp=std::uint32_t(a.zp);
            check.dut.use_16bits=use16;check.dut.ia_reuse_num=2;check.dut.w_reuse_num=2;
            check.dut.row_groups=2;check.dut.row_tail_tiles=1;check.dut.col_groups=1;check.dut.col_tail_tiles=2;
            check.dut.init_cfg=1;check.tick();check.dut.init_cfg=0;
            check.wait([&]{return check.dut.dbg_valid_count==2;},"Both kernel slots filled");
            unsigned limit=0;
            while(!check.sends_expected.empty()) {
                check.dut.send_weight_trigger=check.dut.weight_data_valid;
                check.tick();require(++limit<10000,"Legacy task timed out");
            }
            check.dut.send_weight_trigger=0;check.finish_command(8);
            check.default_tiles+=8;check.finish_case();
        }
        for(bool use16:{false,true}) for(bool im2col:{false,true}) for(unsigned rows:{1U,5U,16U}) {
            const auto a=make_tag(110+rows,use16,im2col);
            const auto b=next_tag(a,rows,rows==16?13:rows+1);
            check.prediction(b);check.dma_expected.push_back({a,false,0});check.dma_expected.push_back({b,true,0});
            check.run(a);check.wait_cached();check.idle(8);
            const auto before=check.hits;check.prediction(std::nullopt);check.run(b);
            require(check.hits==before+1,"Cached descriptor hit was not consumed once");
            ++check.cached_hit_cases;check.finish_case();
        }
        for(bool use16:{false,true}) for(bool im2col:{false,true}) {
            const auto a=make_tag(150+use16,use16,im2col);
            const auto b=next_tag(a,13,3);
            check.prediction(b);check.dma_expected.push_back({a,false,0});check.dma_expected.push_back({b,true,100});
            check.run(a);require(check.transfer.has_value(),"In-flight hit case completed too early");
            check.prediction(std::nullopt);const auto before=check.hits;check.run(b);
            require(check.hits==before+1,"In-flight matching transfer was not reused");
            ++check.inflight_hit_cases;check.finish_case();
        }
        for(unsigned variant=0;variant<3;++variant) {
            const auto a=make_tag(170+variant,false,variant==2);
            const auto b=next_tag(a,7,9);auto c=next_tag(b,5,3);
            check.dma_expected.push_back({a,false,0});check.prediction(b);check.configure(a);check.wait_valid();
            check.grant_enabled=false;check.send();check.finish_command();
            require(check.dut.dbg_prefetch_state==1 && !check.transfer,"Prefetch was not retained while arbitration waited");
            check.prediction(c);
            if(variant==0) {
                check.dma_expected.push_back({b,false,0});check.configure(b);check.grant_enabled=true;
                check.prediction(std::nullopt);check.send();check.finish_command();
            } else if(variant==1) {
                check.dma_expected.push_back({c,false,0});check.configure(c);check.grant_enabled=true;
                check.prediction(std::nullopt);check.send();check.finish_command();
            } else {
                check.dma_expected.push_back({b,true,0});check.grant_enabled=true;check.wait_cached();
                check.prediction(std::nullopt);check.run(b);
            }
            ++check.pending_cases;check.finish_case();
        }
        for(unsigned field=0;field<9;++field) {
            const auto a=make_tag(200+field,false,false);
            const auto b=next_tag(a,7,9);auto c=b;
            switch(field) {
            case 0:c.base+=64;break;
            case 1:c.stride+=32;break;
            case 2:c.p0+=1;break;
            case 3:c.q0+=1;break;
            case 4:c.rows-=1;break;
            case 5:c.cols-=1;break;
            case 6:c.zp+=1;break;
            case 7:c.use16=true;break;
            case 8:c.im2col=true;break;
            }
            check.prediction(b);check.dma_expected.push_back({a,false,0});check.dma_expected.push_back({b,true,0});
            check.run(a);check.wait_cached();check.prediction(std::nullopt);
            check.dma_expected.push_back({c,false,0});const auto before=check.discards;check.run(c);
            require(check.discards==before+1,"A mismatched descriptor was not discarded once");
            ++check.mismatch_cases;check.finish_case();
        }
        for(bool im2col:{false,true}) {
            const auto a=make_tag(220+im2col,true,im2col),b=next_tag(a,5,11),c=next_tag(b,3,7);
            check.prediction(b);check.dma_expected.push_back({a,false,0});check.dma_expected.push_back({b,true,90});
            check.run(a);require(check.transfer.has_value(),"In-flight mismatch completed too early");
            check.prediction(std::nullopt);check.dma_expected.push_back({c,false,0});
            const auto before=check.discards;check.run(c);
            require(check.discards==before+1,"In-flight mismatched tile was not discarded");
            ++check.mismatch_cases;check.finish_case();
        }
        for(unsigned same_first=0;same_first<2;++same_first) {
            const auto a=make_tag(240+same_first,false,true),b=next_tag(a,4,6);
            check.prediction(same_first?std::optional<Tag>(a):std::nullopt);
            check.dma_expected.push_back({a,false,0});const auto captures=check.captures;check.run(a);check.idle(7);
            require(check.captures==captures && check.dut.dbg_window_open,"Deferred prediction eligibility was lost");
            check.dma_expected.push_back({b,true,0});check.prediction(b);check.wait_cached();
            check.prediction(std::nullopt);check.run(b);++check.delayed_prediction_cases;check.finish_case();
        }
        for(unsigned phase=0;phase<3;++phase) {
            const auto a=make_tag(260+phase,phase%2,phase==2),b=next_tag(a,7,5);
            auto c=make_tag(280+phase,!a.use16,!a.im2col,9,13);
            check.prediction(b);check.dma_expected.push_back({a,false,0});check.configure(a);check.wait_valid();
            if(phase==0) check.grant_enabled=false;
            else check.dma_expected.push_back({b,true,phase==2?100U:0U});
            check.send();check.finish_command();
            if(phase==1) check.wait_cached();
            if(phase==2) require(check.transfer.has_value(),"Flush did not interrupt a speculative DMA");
            check.prediction(std::nullopt);check.flush();check.grant_enabled=true;
            check.dma_expected.push_back({c,false,0});check.run(c);check.finish_case();
        }
        for(unsigned iteration=0;iteration<64;++iteration) {
            const auto a=make_tag(400+iteration,check.random()%2,check.random()%2,
                                  1+check.random()%16,1+check.random()%16);
            const auto b=next_tag(a,1+check.random()%16,1+check.random()%16);
            auto next=b;const bool miss=check.random()%4==0;
            if(miss) {next.base+=128;next.p0+=16;}
            check.prediction(b);check.dma_expected.push_back({a,false,unsigned(check.random()%6)});
            check.dma_expected.push_back({b,true,unsigned(check.random()%40)});
            check.run(a);
            check.wait([&]{return check.dut.dbg_prefetch_state!=1;},"Random prefetch issue");
            check.idle(check.random()%20);check.prediction(std::nullopt);
            if(miss) check.dma_expected.push_back({next,false,unsigned(check.random()%6)});
            check.run(next);check.finish_case();++check.random_cases;
        }
        for(bool use16:{false,true}) for(bool im2col:{false,true}) {
            const auto a=make_tag(600+2*use16+im2col,use16,im2col);
            auto b=next_tag(a,6,10);
            check.prediction(a);check.dma_expected.push_back({a,false,0});check.run(a);check.idle(3);
            const auto captures=check.captures;
            for(unsigned field=0;field<5;++field) {
                if(field==0) b.base+=64;
                if(field==1) b.p0+=1;
                if(field==2) b.q0+=1;
                if(field==3) b.rows+=1;
                if(field==4) b.cols+=1;
                check.prediction(b);check.dut.eval();
                require(!check.dut.prefetch_idle && !check.dut.dbg_prefetch_capture,
                        "A changed candidate did not wait for its comparison");
                check.tick();
                require(check.captures==captures,"A changing candidate was captured before comparison");
            }
            check.dma_expected.push_back({b,true,0});check.wait_cached();
            check.prediction(std::nullopt);check.run(b);check.finish_case();++check.comparison_change_cases;
        }
        for(unsigned phase=0;phase<4;++phase) {
            const auto a=make_tag(620+phase,phase%2,phase>=2);
            const auto b=next_tag(a,7,9),c=make_tag(640+phase,!a.use16,!a.im2col,5,11);
            check.prediction(a);check.dma_expected.push_back({a,false,0});check.run(a);check.idle(3);
            const auto captures=check.captures;
            check.prediction(b);check.dut.eval();
            require(!check.dut.prefetch_idle && !check.dut.dbg_prefetch_capture,
                    "A comparison cancellation case lacked a waiting candidate");
            check.tick();
            if(phase==0) {
                check.prediction(std::nullopt);check.idle(3);
            } else if(phase==1) {
                check.prediction(std::nullopt);check.flush();
                check.dma_expected.push_back({c,false,0});check.run(c);
            } else if(phase==2) {
                check.dma_expected.push_back({c,false,0});check.configure(c);
                check.prediction(std::nullopt);check.send();check.finish_command();
            } else {
                check.reset();check.dma_expected.push_back({c,false,0});check.run(c);
            }
            require(check.captures==captures,"A cancelled comparison created a prefetch");
            check.finish_case();++check.comparison_cancel_cases;
        }
        require(check.checked_values==check.tiles_sent*256 && check.logical_loads==check.tiles_sent,
                "Demand completion totals differ from consumed tiles");
        require(check.max_valid_slots==2 && check.hits>0 && check.discards>0 && check.overlap_cycles>0,
                "Double-buffer prefetch coverage is incomplete");
        require(check.max_dma_contexts==2 && check.overlapping_dma_starts>0,
                "Overlapping kernel descriptors were not exercised");
        require(check.dma_starts==check.dma_completions,"A DMA transaction did not finish");
        require(check.flush_drain_cycles>0 && check.delayed_prediction_cases==2,"Flush or delayed prediction coverage is incomplete");
        check.dut.final();
        std::cout<<"{\"passed\":true,\"cycles\":"<<check.cycles<<",\"dma_starts\":"<<check.dma_starts
            <<",\"dma_completions\":"<<check.dma_completions<<",\"prefetch_starts\":"<<check.prefetch_starts
            <<",\"prefetch_captures\":"<<check.captures<<",\"cache_hits\":"<<check.hits<<",\"cache_discards\":"<<check.discards
            <<",\"logical_loads\":"<<check.logical_loads<<",\"tiles_sent\":"<<check.tiles_sent
            <<",\"checked_values\":"<<check.checked_values<<",\"kernel_ram_write_words\":"<<check.ram_write_words
            <<",\"kernel_ram_read_words\":"<<check.ram_read_words<<",\"dma_send_overlap_cycles\":"<<check.overlap_cycles
            <<",\"max_valid_slots\":"<<check.max_valid_slots<<",\"default_disabled_tiles\":"<<check.default_tiles
            <<",\"max_dma_contexts\":"<<check.max_dma_contexts<<",\"overlapping_dma_starts\":"<<check.overlapping_dma_starts
            <<",\"cached_hit_cases\":"<<check.cached_hit_cases<<",\"inflight_hit_cases\":"<<check.inflight_hit_cases
            <<",\"pending_cases\":"<<check.pending_cases<<",\"mismatch_cases\":"<<check.mismatch_cases
            <<",\"delayed_prediction_cases\":"<<check.delayed_prediction_cases<<",\"flush_cases\":"<<check.flush_cases
            <<",\"random_cases\":"<<check.random_cases
            <<",\"comparison_change_cases\":"<<check.comparison_change_cases
            <<",\"comparison_cancel_cases\":"<<check.comparison_cancel_cases<<",\"s8_tiles\":"<<check.s8_tiles
            <<",\"s16_tiles\":"<<check.s16_tiles<<",\"im2col_tiles\":"<<check.im2col_tiles
            <<",\"tail_tiles\":"<<check.tail_tiles<<",\"flush_drain_cycles\":"<<check.flush_drain_cycles<<"}\n";
    } catch(const std::exception &error) {std::cerr<<error.what()<<'\n';return 1;}
}
