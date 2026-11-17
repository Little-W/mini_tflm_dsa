#include "Vframe_store_tb.h"
#include "verilated.h"
#include "stream_test_vectors.hpp"
#include <algorithm>
#include <iostream>
#include <optional>
#include <numeric>

using namespace ps_stream_test;
constexpr unsigned Frames=16,Rows=47,Depth=64;

template<class Wide> unsigned field(const Wide &value,unsigned offset,unsigned bits) {
    const unsigned word=offset/32,shift=offset%32;
    std::uint64_t data=std::uint64_t(value[word])>>shift;
    if (shift+bits>32) data|=std::uint64_t(value[word+1])<<(32-shift);
    return static_cast<unsigned>(data&((std::uint64_t(1)<<bits)-1));
}

struct Entry {
    bool live=false,known=false;
    Row row{};
    Record record;
    unsigned rotation=0,descriptor=0;
    std::array<unsigned,4> addresses{};
};
struct StoredFrame { bool valid=false;unsigned max_words=0;std::vector<Row> rows; };
struct Pending { Row row{};Record record;unsigned index=0;std::uint64_t due=0; };
struct Current {
    unsigned id=0,length=0,captured=0,committed=0,prefetched=0;
    unsigned cap=4,max_words=0;
    bool initial=false,final=false,raw=false,accepted=false,ended=false;
    std::vector<Row> input,previous;
};

class Check {
public:
    Vframe_store_tb dut;
    ps_adaptive::Encoder encoder;
    std::mt19937 random{0x246fb71U};
    std::array<StoredFrame,Frames> frames;
    std::array<std::array<Entry,Rows>,Frames> directory;
    std::array<std::array<int,Depth>,4> owners{};
    std::optional<Current> current;
    std::vector<Row> requested_output;
    std::deque<Pending> encoding,decoding;
    std::deque<Row> expected_replay,fifo;
    std::uint64_t cycle=0,commands=0,written_rows=0,read_rows=0,commit_rows=0;
    std::uint64_t payload_write_words=0,payload_read_words=0,fifo_writes=0,fifo_reads=0,bypass_rows=0;
    std::uint64_t pressure_checks=0,pressure_cycles=0,random_commands=0,runtime_raw_commands=0;
    std::uint64_t read_write_cycles=0,consecutive_write_pairs=0,consecutive_replay_pairs=0;
    std::uint64_t consecutive_commit_pairs=0;
    std::uint64_t pressure_preserved_frames=0,protected_completions=0,bank_imbalance_cases=0;
    std::uint64_t reserve_pressure_cases=0,tail_protected_completions=0;
    std::uint64_t s24_three_frame_cases=0,s16_four_frame_cases=0,narrow_tail_cases=0;
    std::uint64_t tight_prefix_commits=0,wide_reserve_cases=0,raw_cap_override_cases=0;
    std::uint64_t invalid_cap_cases=0,old_cap_fault_cases=0,new_cap_fault_cases=0,prefix_fault_cases=0;
    std::uint64_t rejected_records=0,fault_recoveries=0;
    std::uint64_t reset_cases=0,s16_values=0,peak_words=0;
    std::array<unsigned,2> prepare_min{UINT32_MAX,UINT32_MAX},prepare_max{};
    std::array<std::uint64_t,8> opcodes{};
    std::uint64_t replay_start=UINT64_MAX,last_write=UINT64_MAX,last_replay=UINT64_MAX,last_commit=UINT64_MAX;
    unsigned replay_length=0;
    bool last_complete=false,allow_fault=false;

    Check() { reset(); }
    void reset() {
        dut.rst_n=0;dut.frame_request=0;dut.frame_accept=0;dut.write_valid=0;
        dut.write_frame_end=0;dut.replay_trigger=0;dut.force_raw_i=0;dut.inspect_address=0;
        dut.frame_reserve_rows=0;dut.frame_word_cap=4;
        for(unsigned n=0;n<2;++n) {dut.clk=0;dut.eval();dut.clk=1;dut.eval();++cycle;}
        dut.rst_n=1;
        frames={};directory={};owners={};current.reset();requested_output.clear();
        encoding.clear();decoding.clear();expected_replay.clear();fifo.clear();
        encoder=ps_adaptive::Encoder();replay_start=UINT64_MAX;replay_length=0;
        last_write=last_replay=last_commit=UINT64_MAX;last_complete=false;allow_fault=false;
        dut.clk=0;dut.eval();check_counts();
    }
    std::array<unsigned,4> free_counts() const {
        std::array<unsigned,4> result{};
        for(unsigned b=0;b<4;++b) for(auto owner:owners[b]) result[b]+=owner==0;
        return result;
    }
    unsigned frame_bank_count(unsigned id,unsigned bank) const {
        unsigned result=0;
        for(auto owner:owners[bank]) if(owner && unsigned(owner-1)/Rows==id) ++result;
        return result;
    }
    static unsigned effective_cap(unsigned cap,bool raw) {
#ifdef FORCE_RAW
        (void)cap;(void)raw;return 4;
#else
        return raw?4:cap;
#endif
    }
    bool fits(unsigned id,unsigned length,bool initial,bool final,unsigned reserve=0,
              unsigned cap=4,bool raw=false) const {
        if(final) return true;
        const std::uint64_t budget=(std::uint64_t(effective_cap(cap,raw))*std::max(length,reserve)+3)/4;
        const auto free=free_counts();
        for(unsigned b=0;b<4;++b)
            if(free[b]+(initial?0:frame_bank_count(id,b))<budget) return false;
        return true;
    }
    void check_counts() {
        const auto free=free_counts();unsigned total=0;
        for(unsigned b=0;b<4;++b) {
            require(dut.free_counts[b]==free[b],"Free bank count differs at "+std::to_string(cycle));
            for(unsigned address=0;address<Depth;++address)
                require(field(dut.free_bits,b*64+address,1)==unsigned(owners[b][address]==0),"Free bitmap differs");
            for(unsigned id=0;id<Frames;++id)
                require(field(dut.frame_bank_counts,(b*Frames+id)*6,6)==frame_bank_count(id,b),"Frame bank ownership differs");
            total+=Depth-free[b];
        }
        peak_words=std::max(peak_words,std::uint64_t(total));
        for(unsigned id=0;id<Frames;++id) {
            require(((dut.frame_valid>>id)&1U)==unsigned(frames[id].valid),"Frame validity differs");
            require(field(dut.frame_lengths,id*6,6)==(frames[id].valid?frames[id].rows.size():0),"Frame length differs");
            require(((dut.frame_max_words>>(id*3))&7U)==frames[id].max_words,"Frame maximum record length differs");
        }
        if(current && dut.command_present) {
            require(dut.selected_word_cap==current->cap,"Selected word cap differs");
            require(dut.current_max_words==current->max_words,"Current maximum record length differs");
        }
        require(dut.decoder_inflight==decoding.size(),"Decoder in-flight count differs");
        require(dut.decoded_count==fifo.size(),"Decoded FIFO count differs");
        require(fifo.size()+decoding.size()<=7,"Prefetch credit limit exceeded");
    }
    void inspect_directory() {
        for(unsigned id=0;id<Frames;++id) for(unsigned row=0;row<Rows;++row) {
            const auto &entry=directory[id][row];
            if(!entry.known) continue;
            dut.inspect_address=id*Rows+row;dut.eval();
            require(dut.inspect_descriptor==entry.descriptor,"Stored directory descriptor differs");
        }
    }
    void tick() {
        dut.clk=0;dut.eval();check_counts();
        const auto edge=cycle+1;
        if(dut.prepare_start) {
            require(!current,"Two frame commands overlap");
            require(fits(dut.frame_id,dut.frame_rows,dut.frame_init,dut.frame_final,dut.frame_reserve_rows,
                         dut.frame_word_cap,dut.force_raw_i),"Prepared frame lacks reserved bank capacity");
            Current c;c.id=dut.frame_id;c.length=dut.frame_rows;c.initial=dut.frame_init;
            c.final=dut.frame_final;c.raw=dut.force_raw_i;c.input=requested_output;
            c.cap=effective_cap(dut.frame_word_cap,dut.force_raw_i);
            require(c.initial?!frames[c.id].valid:frames[c.id].valid,"Selected frame existence differs");
            if(!c.initial) {
                c.previous=frames[c.id].rows;
                require(c.previous.size()==c.length,"Selected old frame length differs");
                for(const auto &row:c.previous) expected_replay.push_back(row);
            }
            require(c.final || c.input.size()==c.length,"New frame length differs");
            current=std::move(c);
        }
        if(dut.frame_accept) {
            require(current && dut.frame_ready,"Frame accepted before it is ready");
            current->accepted=true;runtime_raw_commands+=current->raw;
        }
        if(dut.replay_trigger && dut.replay_armed && (dut.command_accepted || dut.frame_accept)) {
            require(current && !current->initial,"Unexpected replay trigger");
            replay_start=edge+1;replay_length=current->length;
        }
        if(dut.encoder_start) {
            require(current && current->accepted && !current->final,"Encoder ran outside an output command");
            const auto row=get_row(dut.write_data);
            require(row==current->input.at(current->captured),"Write input differs");
            auto record=encode(encoder,row,current->captured==0,current->raw);
            encoding.push_back({row,record,current->captured,edge+4});
            ++current->captured;++written_rows;
            consecutive_write_pairs+=last_write+1==edge;last_write=edge;
        }
        if(dut.write_frame_end) {
            require(current && current->accepted,"Frame end without command");
            current->ended=true;
        }
        std::optional<Row> arrived;
        const bool expect_decode=!decoding.empty() && decoding.front().due==edge;
        require(bool(dut.decoder_done)==expect_decode,"Decoder latency differs at "+std::to_string(edge));
        if(expect_decode) {
            const auto value=decoding.front();decoding.pop_front();arrived=value.row;
            require(!dut.decoder_fault && get_row(dut.decoded_row)==value.row,"Decoded bank data differs");
            require(bool(dut.decoder_first)==(value.index==0),"Decoded first-row marker differs");
        }
        const bool encoded_due=!encoding.empty() && encoding.front().due==edge;
        const bool permitted_record=encoded_due && current &&
            encoding.front().record.bytes.size()/16<=current->cap &&
            (current->initial || current->prefetched>=std::min(current->length,encoding.front().index+2));
        const bool expect_commit=encoded_due && permitted_record && !dut.capacity_fault;
        require(bool(dut.commit_valid)==expect_commit,"Encoder commit latency differs at "+std::to_string(edge));
        if(encoded_due && !expect_commit) {
            require(allow_fault,"Unexpected encoded record rejection");
            encoding.pop_front();++rejected_records;
        }
        std::optional<Pending> committed;
        std::array<unsigned,4> allocation{};
        if(expect_commit) {
            committed=encoding.front();encoding.pop_front();
            require(current && committed->index==current->committed && dut.commit_row==current->committed,"Commit row differs");
            const auto required=std::min(current->length,committed->index+2);
            require(current->initial || current->prefetched>=required,"Commit lacks the required old-row prefix");
            require(dut.required_read_rows==required,"Required old-row prefix differs");
            tight_prefix_commits+=!current->initial && required<current->length && current->prefetched==required;
            require(dut.commit_opcode==committed->record.opcode && dut.commit_words*16==committed->record.bytes.size(),"Commit format differs");
            check_packet(dut.commit_packet,committed->record,"Encoded frame row");
            for(unsigned b=0;b<4;++b) {
                allocation[b]=dut.allocated_addresses[b];
                if((dut.payload_we>>b)&1U) {
                    require(allocation[b]<Depth && owners[b][allocation[b]]==0,"Commit reused a live or same-edge released address");
                }
            }
            require(unsigned(__builtin_popcount(dut.payload_we))==dut.commit_words,"Write bank mask differs");
        } else require(!dut.payload_we,"Data RAM wrote without a commit");
        if(dut.prefetch_fire) {
            require(current && !current->initial,"Prefetch outside the selected old frame");
            const unsigned id=current->id,index=current->prefetched;
            require(dut.read_row==index && dut.selected_id==id,"Prefetch identity differs");
            auto &entry=directory[id][index];
            require(entry.live && entry.row==current->previous[index],"Prefetch lost an old row");
            require(dut.prefetch_opcode==entry.record.opcode && dut.read_rotation==entry.rotation,"Read directory fields differ");
            require(unsigned(__builtin_popcount(dut.payload_re))*16==entry.record.bytes.size(),"Read bank mask differs");
            for(unsigned b=0;b<4;++b) if((dut.payload_re>>b)&1U) {
                const unsigned address=dut.read_addresses[b];
                require(address==entry.addresses[b] && address<Depth,"Read bank address differs");
                require(owners[b][address]==int(id*Rows+index+1),"Read address belongs to another row");
                owners[b][address]=0;
            }
            entry.live=false;
            decoding.push_back({entry.row,entry.record,index,edge+6});
            payload_read_words+=entry.record.bytes.size()/16;
            ++current->prefetched;
        } else require(!dut.payload_re,"Data RAM read without a selected row");
        if(committed) {
            auto &entry=directory[current->id][committed->index];
            require(!entry.live,"Directory overwrite preceded the old row read");
            entry.live=true;entry.known=true;entry.row=committed->row;entry.record=committed->record;
            entry.rotation=dut.write_rotation;entry.addresses=allocation;
            entry.descriptor=entry.record.opcode | (entry.rotation<<3);
            for(unsigned b=0;b<4;++b) {
                entry.descriptor|=allocation[b]<<(5+b*6);
                if((dut.payload_we>>b)&1U) owners[b][allocation[b]]=int(current->id*Rows+committed->index+1);
            }
            ++current->committed;++commit_rows;++opcodes[committed->record.opcode];
            consecutive_commit_pairs+=last_commit+1==edge;last_commit=edge;
            current->max_words=std::max(current->max_words,unsigned(committed->record.bytes.size()/16));
            payload_write_words+=committed->record.bytes.size()/16;
        }
        read_write_cycles+=bool(dut.payload_we)&&bool(dut.payload_re);
        if(dut.decoded_read_en) {
            require(!fifo.empty(),"Decoded FIFO underflow");fifo.pop_front();++fifo_reads;
        }
        if(dut.replay_bypass) {
            require(arrived.has_value() && !dut.decoded_read_en && !dut.decoded_write_en,"Bypass accessed decoded RAM");++bypass_rows;
        }
        if(dut.decoded_write_en) {
            require(arrived.has_value(),"Decoded FIFO write lacks a decoded row");fifo.push_back(*arrived);++fifo_writes;
        }
        if(dut.frame_pressure) {
            ++pressure_cycles;
            require(!current && !dut.prepare_start && !dut.payload_we && !dut.payload_re && !dut.prefetch_fire,
                    "Capacity pressure changed a resident frame");
        }
        dut.clk=1;dut.eval();cycle=edge;
        require(!dut.capacity_fault || allow_fault,"Store reported a fault at cycle "+std::to_string(cycle));
        const bool expected_valid=replay_start!=UINT64_MAX && edge>=replay_start && edge<replay_start+replay_length;
        require(bool(dut.replay_valid)==expected_valid,"Continuous replay timing differs at "+std::to_string(cycle));
        if(dut.replay_valid) {
            require(!expected_replay.empty(),"Unexpected replay row");
            require(get_row(dut.replay_data)==expected_replay.front(),"Replayed INT32 row differs");
            expected_replay.pop_front();++read_rows;
            consecutive_replay_pairs+=last_replay+1==edge;last_replay=edge;
        } else require(get_row(dut.replay_data)==Row{},"Inactive replay output is nonzero");
        if(dut.frame_complete) {
            require(!last_complete && current && current->accepted && current->ended,"Invalid frame completion");
            require(encoding.empty() && decoding.empty() && fifo.empty() && expected_replay.empty(),"Frame completed before data finished");
            require(current->final || current->committed==current->length,"Frame completed before all writes");
            require(current->initial || current->prefetched==current->length,"Frame completed before all reads");
            auto &stored=frames[current->id];stored.valid=!current->final;
            stored.rows=current->final?std::vector<Row>{}:current->input;
            stored.max_words=current->final?0:current->max_words;
            current.reset();++commands;replay_start=UINT64_MAX;replay_length=0;
        }
        last_complete=dut.frame_complete;check_counts();
    }
    bool request(unsigned id,unsigned length,bool initial,bool final,bool raw,const std::vector<Row>& output,
                 unsigned hold=0,unsigned reserve=0,unsigned cap=4) {
        require(!current,"Request overlaps an unfinished command");
        requested_output=output;
        dut.frame_id=id;dut.frame_rows=length;dut.frame_init=initial;dut.frame_final=final;
        dut.frame_reserve_rows=reserve;dut.frame_word_cap=cap;
        dut.force_raw_i=raw;dut.frame_request=1;dut.frame_accept=0;
        const bool expected_fit=fits(id,length,initial,final,reserve,cap,raw);
        dut.clk=0;dut.eval();
        if(!expected_fit) {
            require(dut.frame_pressure && !dut.frame_ready,"Insufficient bank capacity did not report pressure");
            const auto old_frames=frames;inspect_directory();
            for(unsigned i=0;i<5;++i) tick();
            inspect_directory();
            for(unsigned f=0;f<Frames;++f)
                require(frames[f].valid==old_frames[f].valid && frames[f].rows==old_frames[f].rows,"Pressure changed saved values");
            for(const auto &frame:frames) pressure_preserved_frames+=frame.valid;
            ++pressure_checks;dut.frame_request=0;tick();return false;
        }
        require(!dut.frame_pressure,"Admissible frame reported pressure");
        unsigned waited=0;
        while(!dut.frame_ready) {tick();require(++waited<80,"Frame preparation did not finish");}
        const unsigned category=initial?0:1;
        prepare_min[category]=std::min(prepare_min[category],waited);
        prepare_max[category]=std::max(prepare_max[category],waited);
        for(unsigned n=0;n<hold;++n) tick();
        dut.frame_accept=1;tick();dut.frame_accept=0;dut.frame_request=0;return true;
    }
    bool run(unsigned id,unsigned length,bool initial,bool final,const std::vector<Row>& output,
             bool raw=false,unsigned delay=3,unsigned hold=0,unsigned reserve=0,unsigned cap=4,
             unsigned trigger_delay=0) {
        if(!request(id,length,initial,final,raw,output,hold,reserve,cap)) return false;
        const unsigned last=final ? (initial?1:trigger_delay+length+3) :
            std::max(delay+length-1,initial?0:trigger_delay);
        for(unsigned t=0;t<=last;++t) {
            dut.replay_trigger=!initial && (t==trigger_delay || t==trigger_delay+4);
            dut.write_valid=!final && t>=delay && t<delay+length;
            if(dut.write_valid) put_row(dut.write_data,output[t-delay]);
            dut.write_frame_end=t==last;tick();
        }
        dut.replay_trigger=0;dut.write_valid=0;dut.write_frame_end=0;
        unsigned waited=0;
        while(current) {tick();require(++waited<80,"Frame completion did not finish");}
        tick();return true;
    }
    void finish(unsigned id) {
        require(frames[id].valid,"Final command lacks a frame");
        const auto length=frames[id].rows.size();
        require(run(id,length,false,true,{}),"Final command reported pressure");
    }
    void finish_all() {
        for(unsigned id=Frames;id--;) if(frames[id].valid) finish(id);
        const auto free=free_counts();for(auto count:free) require(count==Depth,"Final frames leaked capacity");
    }
    void invalid_request(unsigned id,unsigned length,bool initial,unsigned cap) {
        require(!current,"Invalid request overlaps an active command");
        inspect_directory();const auto before=owners;
        dut.frame_request=1;dut.frame_accept=0;dut.frame_id=id;dut.frame_rows=length;
        dut.frame_reserve_rows=0;dut.frame_word_cap=cap;dut.frame_init=initial;
        dut.frame_final=0;dut.force_raw_i=0;allow_fault=true;
        dut.clk=0;dut.eval();
        require(!dut.prepare_start && !dut.frame_pressure && !dut.frame_ready,
                "Invalid cap request changed the command state");
        tick();dut.frame_request=0;
        require(dut.capacity_fault && owners==before,"Invalid cap request changed bank ownership");
        inspect_directory();tick();
    }
    void recover_fault() {
        require(dut.capacity_fault,"Fault recovery lacks a fault");
        reset();
        require(run(15,3,true,false,frame(3,0,random),true),"RAW task after fault reset failed");
        finish(15);++fault_recoveries;
    }
};

static std::vector<Row> random_s16(unsigned count,std::mt19937& random) {
    std::vector<Row> result(count);
    for(auto &row:result) for(auto &value:row) value=static_cast<std::int32_t>(random()%65536)-32768;
    return result;
}

static std::vector<Row> literal_rows(const std::vector<unsigned>& widths,std::mt19937& random) {
    ps_adaptive::Encoder encoder;std::vector<Row> result;
    for(unsigned bits:widths) {
        Row value{};bool selected=false;
        for(unsigned attempt=0;attempt<100 && !selected;++attempt) {
            for(auto &lane:value) lane=ps_codec::sign_extend(random()&((std::uint32_t(1)<<bits)-1),bits);
            auto trial=encoder;
            const auto record=trial.encode(value,result.empty());
            if(record.bytes.size()/16==bits/8 && record.opcode==(bits==16?1:2)) {
                encoder=trial;selected=true;
            }
        }
        require(selected,"Directed literal record could not be generated");result.push_back(value);
    }
    return result;
}

int main() {
    try {
        Check check;
        for(unsigned pattern=0;pattern<7;++pattern) for(unsigned length:{1U,2U,3U,15U,16U,17U,31U,32U,46U,47U}) {
            const auto values=frame(length,pattern,check.random);
            require(check.run(7,length,true,false,values,false,1,pattern%4),"One frame must fit");
            auto next=frame(length,(pattern+1)%7,check.random);
            require(check.run(7,length,false,false,next,pattern%3==0,2+pattern,pattern%3),"Same frame RAW update must fit");
            check.finish(7);
        }
        for(unsigned length:{1U,16U,32U,47U})
            require(check.run(3,length,true,true,{}),"Single-K command must fit without PS allocation");

        for (unsigned width:{8U,16U,24U,32U}) for (unsigned length:{1U,47U}) {
            std::vector<Row> sparse_rows(length);
            for (unsigned row=0;row<length;++row) {
                const unsigned count=row%4;
                for (unsigned lane=0;lane<count;++lane)
                    sparse_rows[row][(row+lane*5)%16]=ps_codec::sign_extend(
                        (1U<<(width-1))-(lane&1U),width);
            }
            require(check.run(5,length,true,false,sparse_rows),"Sparse frame initialization failed");
            require(check.run(5,length,false,false,sparse_rows,true),"Sparse frame RAW replacement failed");
            require(check.run(5,length,false,false,sparse_rows),"RAW frame sparse replacement failed");
            check.finish(5);
        }

        check.reset();
        const auto worst=frame(47,0,check.random);
        require(check.run(0,47,true,false,worst,true),"RAW frame did not fit");
        require(!check.run(1,47,true,false,worst,true),"Two RAW frames exceeded pool capacity");
        require(check.run(0,47,false,false,frame(47,6,check.random),true,2),"RAW reclaim failed");
        check.finish(0);require(check.run(1,47,true,false,worst,true),"Freed capacity was not reusable");check.finish(1);

        check.reset();
        for(unsigned id=0;id<3;++id)
            require(check.run(id,16,true,false,frame(16,0,check.random),true,3,0,16),"Uniform-reserve source failed");
        require(!check.run(3,17,true,false,frame(17,0,check.random),true,3,0,7),
                "A smaller reserve reduced the actual RAW bound");
        ++check.reserve_pressure_cases;
        const auto tail=frame(7,3,check.random);
        require(check.run(3,7,true,false,tail,false,3,0,16),"Uniform-reserve tail did not fit");
        require(!check.run(4,7,true,false,tail,false,3,0,16),"Tail reserve did not report capacity pressure");
        ++check.reserve_pressure_cases;
        require(check.run(3,7,false,false,frame(7,0,check.random),true,3,0,16),"Protected tail RAW growth failed");
        require(check.run(3,7,false,false,frame(7,6,check.random),true,3,0,16),"Protected tail could not continue");
        require(check.run(3,7,false,true,{},false,3,0,16),"Protected tail final command failed");
        ++check.tail_protected_completions;
        require(check.run(4,7,true,false,tail,false,3,0,16),"Candidate did not resume after the protected tail");
        check.finish_all();

#ifndef FORCE_RAW
        check.reset();
        for(unsigned id=0;id<5;++id)
            require(check.run(id,32,true,false,frame(32,3,check.random)),"Compressed window did not fit");
        const auto growth=frame(32,0,check.random);
        require(check.run(4,32,false,false,growth),"Protected frame RAW growth failed");
        require(!check.run(0,32,false,false,growth),"Expected per-bank pressure was absent");
        require(check.run(4,32,false,false,frame(32,0,check.random)),"Protected frame could not continue");
        check.finish(4);++check.protected_completions;
        require(check.run(0,32,false,false,growth),"Saved candidate did not resume after protected completion");
        check.finish_all();

        check.reset();
        for(unsigned id=0;id<10;++id) {
            auto values=random_s16(7,check.random);ps_adaptive::Encoder encoder;
            for(unsigned row=0;row<values.size();++row)
                require(encoder.encode(values[row],row==0).opcode==1,"Directed S16 bank distribution differs");
            require(check.run(id,7,true,false,values),"Bank-distribution frame did not fit");
        }
        for(unsigned id=1;id<10;id+=2) check.finish(id);
        const auto free=check.free_counts();
        require(std::accumulate(free.begin(),free.end(),0U)>=4*46 && *std::min_element(free.begin(),free.end())<46,
                "Directed bank imbalance differs");
        require(!check.run(10,46,true,false,frame(46,3,check.random)),"Uneven bank capacity was accepted");
        ++check.bank_imbalance_cases;check.finish_all();

        check.reset();
        std::vector<unsigned> mixed_widths(32,24);
        std::fill(mixed_widths.begin(),mixed_widths.begin()+16,16);
        for(unsigned id=0;id<3;++id) {
            const auto values=literal_rows(mixed_widths,check.random);
            require(check.run(id,32,true,false,values,false,0,0,32,3),"S24 three-frame window did not fit");
            for(unsigned b=0;b<4;++b)
                require(check.frame_bank_count(id,b)==20,"Mixed S16/S24 frame bank count differs");
        }
        ++check.s24_three_frame_cases;
        const auto reverse_widths=std::vector<unsigned>(mixed_widths.rbegin(),mixed_widths.rend());
        require(!check.run(3,32,true,false,literal_rows(mixed_widths,check.random),false,0,0,32,3),
                "Fourth S24 frame did not report pressure");
        require(!check.run(0,32,false,false,literal_rows(reverse_widths,check.random),false,0,0,32,4),
                "RAW reservation unexpectedly fit the three-frame window");
        for(unsigned id:{2U,0U,1U,2U}) {
            require(check.run(id,32,false,false,literal_rows(reverse_widths,check.random),false,0,0,32,3,7),
                    "S24 update with one-row read lead failed");
            for(unsigned b=0;b<4;++b)
                require(check.frame_bank_count(id,b)==20,"Updated S24 frame bank count differs");
        }
        check.finish_all();

        check.reset();
        for(unsigned id=0;id<4;++id)
            require(check.run(id,32,true,false,literal_rows(std::vector<unsigned>(32,16),check.random),
                              false,0,0,32,2),"S16 four-frame window did not fit");
        for(auto free:check.free_counts()) require(free==0,"S16 four-frame window did not fill every bank");
        ++check.s16_four_frame_cases;
        require(!check.run(4,32,true,false,literal_rows(std::vector<unsigned>(32,16),check.random),
                           false,0,0,32,2),"Fifth S16 frame did not report pressure");
        for(unsigned id:{3U,1U,0U,2U})
            require(check.run(id,32,false,false,literal_rows(std::vector<unsigned>(32,16),check.random),
                              false,0,0,32,2,7),"S16 update with one-row read lead failed");
        check.finish_all();

        check.reset();
        for(unsigned id=0;id<4;++id)
            require(check.run(id,16,true,false,literal_rows(std::vector<unsigned>(16,24),check.random),
                              false,1,0,16,3),"S24 tail-window source failed");
        require(check.run(4,7,true,false,literal_rows(std::vector<unsigned>(7,24),check.random),
                          false,1,0,16,3),"S24 protected tail did not fit");
        require(!check.run(5,7,true,false,literal_rows(std::vector<unsigned>(7,24),check.random),
                           false,1,0,16,3),"S24 tail reservation did not report pressure");
        require(check.run(4,7,false,false,literal_rows(std::vector<unsigned>(7,24),check.random),
                          false,0,0,16,3),"S24 protected tail could not continue");
        check.finish(4);
        require(check.run(5,7,true,false,literal_rows(std::vector<unsigned>(7,24),check.random),
                          false,1,0,16,3),"S24 candidate did not resume after tail release");
        ++check.narrow_tail_cases;check.finish_all();

        check.reset();
        for(unsigned reserve:{127U,128U}) {
            require(check.run(4,7,true,false,literal_rows(std::vector<unsigned>(7,16),check.random),
                              false,1,0,reserve,2),"Large S16 reserve was truncated");
            check.finish(4);++check.wide_reserve_cases;
        }
        require(!check.run(4,7,true,false,frame(7,3,check.random),false,1,0,129,2),
                "S16 reserve exceeded bank depth");
        require(!check.run(4,7,true,false,frame(7,3,check.random),false,1,0,UINT32_MAX,3),
                "S24 reserve arithmetic overflowed");

        require(check.run(4,32,true,false,frame(32,3,check.random),false,0,0,32,2),
                "COPY-containing S16 frame did not fit");
        require(check.run(4,32,false,false,literal_rows(std::vector<unsigned>(32,16),check.random),
                          false,0,0,32,2,7),"COPY rows did not advance old-row release progress");
        check.finish_all();
#endif

        check.reset();
        for(unsigned cap:{2U,3U}) {
            auto values=frame(32,0,check.random);values[0].fill(INT32_MIN);
            require(check.run(1,32,true,false,values,true,0,0,32,cap),"Runtime RAW cap override failed");
            require(check.frames[1].max_words==4,"RAW maximum record length differs");
            require(!check.run(2,33,true,false,frame(33,0,check.random),true,0,0,33,cap),
                    "Runtime RAW override admitted a narrow budget");
            check.finish(1);++check.raw_cap_override_cases;
        }
#ifdef FORCE_RAW
        require(check.run(1,32,true,false,frame(32,3,check.random),false,0,0,32,2),
                "Compile-time RAW cap override failed");
        require(check.frames[1].max_words==4,"Compile-time RAW did not override the word cap");
        check.finish(1);++check.raw_cap_override_cases;
#endif
        require(!check.run(4,7,true,false,frame(7,3,check.random),false,1,0,UINT32_MAX,4),
                "RAW reserve arithmetic overflowed");

        for(unsigned cap:{0U,1U,5U,6U,7U}) {
            check.reset();check.invalid_request(0,7,true,cap);
            ++check.invalid_cap_cases;check.recover_fault();
        }
#ifndef FORCE_RAW
        for(unsigned cap:{2U,3U}) {
            check.reset();
            require(check.run(0,7,true,false,frame(7,0,check.random),true),"Old cap test source failed");
            check.invalid_request(0,7,false,cap);++check.old_cap_fault_cases;check.recover_fault();
        }
        check.reset();
        require(check.run(0,7,true,false,literal_rows(std::vector<unsigned>(7,24),check.random),
                          false,0,0,7,3),"S24 old cap test source failed");
        check.invalid_request(0,7,false,2);++check.old_cap_fault_cases;check.recover_fault();
        for(unsigned cap:{2U,3U}) {
            check.reset();
            auto values=literal_rows(std::vector<unsigned>(1,24),check.random);
            if(cap==3) values[0].fill(INT32_MIN);
            require(check.request(0,1,true,false,false,values,0,0,cap),"New cap test preparation failed");
            check.allow_fault=true;const auto before=check.owners;
            check.dut.write_valid=1;check.dut.write_frame_end=1;put_row(check.dut.write_data,values[0]);check.tick();
            check.dut.write_valid=0;check.dut.write_frame_end=0;
            for(unsigned wait=0;!check.dut.capacity_fault && wait<8;++wait) check.tick();
            require(check.dut.capacity_fault && check.owners==before && check.current->committed==0,
                    "Over-cap encoded record changed storage");
            ++check.new_cap_fault_cases;check.recover_fault();
        }
#endif

        check.reset();
        require(check.run(0,32,true,false,frame(32,0,check.random),true),"Prefix safety source failed");
        const auto premature=frame(32,0,check.random);
        require(check.request(0,32,false,false,true,premature),"Prefix safety preparation failed");
        check.allow_fault=true;
        for(unsigned row=0;row<20 && !check.dut.capacity_fault;++row) {
            check.dut.write_valid=1;put_row(check.dut.write_data,premature[row]);check.tick();
        }
        check.dut.write_valid=0;
        require(check.dut.capacity_fault && check.current->committed==6 && check.current->prefetched==7,
                "Insufficient old-row prefix was not rejected before storage");
        for(unsigned wait=0;wait<6;++wait) check.tick();
        ++check.prefix_fault_cases;check.recover_fault();

        check.reset();
        for(unsigned step=0;step<420;++step) {
            unsigned id=check.random()%Frames;
            if(check.frames[id].valid && check.random()%5==0) {check.finish(id);++check.random_commands;continue;}
            const bool initial=!check.frames[id].valid;
            const unsigned length=initial ? 1+check.random()%Rows : check.frames[id].rows.size();
            auto values=frame(length,check.random()%7,check.random);
            const bool raw=check.random()%7==0;
            if(!check.run(id,length,initial,false,values,raw,2+check.random()%18,check.random()%5)) {
                unsigned victim=check.random()%Frames;
                for(unsigned n=0;n<Frames && (!check.frames[victim].valid || victim==id);++n) victim=(victim+1)%Frames;
                if(check.frames[victim].valid && victim!=id) check.finish(victim);
                else if(check.frames[id].valid) check.finish(id);
            }
            ++check.random_commands;
        }
        check.inspect_directory();check.finish_all();

        for(unsigned start=0;start<4096;) {
            const unsigned length=std::min(Rows,4096-start);std::vector<Row> values(length);
            for(unsigned row=0;row<length;++row) for(unsigned lane=0;lane<16;++lane)
                values[row][lane]=ps_codec::sign_extend((start+row)*16+lane,16);
            require(check.run(11,length,true,false,values),"S16 exhaustive frame did not fit");
            check.finish(11);start+=length;check.s16_values+=16*length;
        }

        require(check.run(2,47,true,false,frame(47,0,check.random),true),"Reset source did not fit");
        require(check.request(2,47,false,false,false,frame(47,4,check.random)),"Reset preparation failed");
        check.reset();++check.reset_cases;
        require(check.request(9,47,true,false,true,frame(47,0,check.random)),"Reset capture preparation failed");
        for(unsigned row=0;row<12;++row) {
            check.dut.write_valid=1;put_row(check.dut.write_data,check.requested_output[row]);check.tick();
        }
        check.reset();++check.reset_cases;
        require(check.run(9,47,true,false,frame(47,0,check.random),true),"Full RAW frame after reset failed");
        check.finish(9);

        require(check.pressure_checks>0 && check.read_write_cycles>0 && check.bypass_rows>0,"Directed control coverage is incomplete");
        require(check.consecutive_write_pairs>0 && check.consecutive_commit_pairs>0 && check.consecutive_replay_pairs>0,
                "II=1 rows were not exercised");
        require(check.invalid_cap_cases==5 && check.prefix_fault_cases==1 && check.raw_cap_override_cases>=2,
                "Word-cap control coverage is incomplete");
#ifndef FORCE_RAW
        for(auto count:check.opcodes) require(count>0,"An adaptive opcode was not exercised");
        require(check.s24_three_frame_cases==1 && check.s16_four_frame_cases==1 && check.narrow_tail_cases==1 &&
                check.tight_prefix_commits>0 && check.old_cap_fault_cases==3 && check.new_cap_fault_cases==2,
                "Narrow-cap replacement coverage is incomplete");
#else
        for(unsigned code=0;code<8;++code) if(code!=3) require(check.opcodes[code]==0,"Forced RAW emitted another opcode");
#endif
        std::cout<<"{\"passed\":true,\"commands\":"<<check.commands<<",\"write_rows\":"<<check.written_rows
                 <<",\"read_rows\":"<<check.read_rows<<",\"checked_read_int32\":"<<check.read_rows*16
                 <<",\"commit_rows\":"<<check.commit_rows<<",\"payload_write_words\":"<<check.payload_write_words
                 <<",\"payload_read_words\":"<<check.payload_read_words<<",\"decoded_ram_write_rows\":"<<check.fifo_writes
                 <<",\"decoded_ram_read_rows\":"<<check.fifo_reads<<",\"bypass_rows\":"<<check.bypass_rows
                 <<",\"pressure_checks\":"<<check.pressure_checks<<",\"pressure_cycles\":"<<check.pressure_cycles
                 <<",\"pressure_preserved_frames\":"<<check.pressure_preserved_frames
                 <<",\"protected_completions\":"<<check.protected_completions<<",\"bank_imbalance_cases\":"<<check.bank_imbalance_cases
                 <<",\"reserve_pressure_cases\":"<<check.reserve_pressure_cases
                 <<",\"tail_protected_completions\":"<<check.tail_protected_completions
                 <<",\"s24_three_frame_cases\":"<<check.s24_three_frame_cases
                 <<",\"s16_four_frame_cases\":"<<check.s16_four_frame_cases
                 <<",\"narrow_tail_cases\":"<<check.narrow_tail_cases
                 <<",\"tight_prefix_commits\":"<<check.tight_prefix_commits
                 <<",\"wide_reserve_cases\":"<<check.wide_reserve_cases
                 <<",\"raw_cap_override_cases\":"<<check.raw_cap_override_cases
                 <<",\"invalid_cap_cases\":"<<check.invalid_cap_cases
                 <<",\"old_cap_fault_cases\":"<<check.old_cap_fault_cases
                 <<",\"new_cap_fault_cases\":"<<check.new_cap_fault_cases
                 <<",\"prefix_fault_cases\":"<<check.prefix_fault_cases
                 <<",\"rejected_records\":"<<check.rejected_records
                 <<",\"fault_recoveries\":"<<check.fault_recoveries
                 <<",\"random_commands\":"<<check.random_commands<<",\"runtime_raw_commands\":"<<check.runtime_raw_commands
                 <<",\"simultaneous_bank_read_write_cycles\":"<<check.read_write_cycles
                 <<",\"consecutive_write_pairs\":"<<check.consecutive_write_pairs
                 <<",\"consecutive_commit_pairs\":"<<check.consecutive_commit_pairs
                 <<",\"consecutive_replay_pairs\":"<<check.consecutive_replay_pairs
                 <<",\"reset_cases\":"<<check.reset_cases<<",\"s16_values\":"<<check.s16_values
                 <<",\"initial_prepare_edges\":["<<check.prepare_min[0]<<','<<check.prepare_max[0]<<']'
                 <<",\"update_prepare_edges\":["<<check.prepare_min[1]<<','<<check.prepare_max[1]<<']'
                 <<",\"peak_words\":"<<check.peak_words<<",\"cycles\":"<<check.cycle<<",\"opcodes\":[";
        for(unsigned i=0;i<8;++i) std::cout<<(i?",":"")<<check.opcodes[i];
        std::cout<<"]}\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
