#include "Vshared_storage_tb.h"
#include "verilated.h"
#include "stream_test_vectors.hpp"
#include <array>
#include <iostream>
#include <optional>

using namespace ps_stream_test;
using Word=std::array<std::uint32_t,4>;
constexpr unsigned TotalBanks=TEST_BANK_COUNT,Banks=TotalBanks-1,MaxDepth=TEST_BANK_BYTES/16;
constexpr unsigned Frames=16,DirectoryRows=1024,MaxFrameRows=TEST_BANK_BYTES/8;
constexpr unsigned AddressBits=MaxDepth==64?6:MaxDepth==128?7:8;

template<class T> Word get_word(const T& value) {
    Word word{};for(unsigned i=0;i<4;++i) word[i]=value[i];return word;
}
template<class T> void put_word(T& output,const Word& value) {
    for(unsigned i=0;i<4;++i) output[i]=value[i];
}
struct Entry {
    bool live=false,known=false;
    Row row{};Record record;
    unsigned rotation=0;
    std::uint64_t descriptor=0;
    std::array<unsigned,4> addresses{};
};
struct Stored { bool valid=false;unsigned max_words=0;std::vector<Row> rows; };
struct Pending { Row row{};Record record;unsigned index=0;std::uint64_t due=0; };
struct Current {
    unsigned id=0,length=0,captured=0,committed=0,prefetched=0,max_words=0;
    bool initial=false,final=false,raw=false,accepted=false;
    std::vector<Row> output;
};

class Check {
public:
    Vshared_storage_tb dut;
    std::mt19937 random{0x539b61aU};
    std::array<Word,TotalBanks*MaxDepth> memory{};
    std::array<std::uint16_t,TotalBanks*MaxDepth> known{};
    std::array<Stored,Frames> frames{};
    std::array<Entry,DirectoryRows> directory{};
    std::array<std::array<unsigned,MaxDepth>,Banks> owner{};
    std::optional<Current> current;
    std::vector<Row> requested;
    std::deque<Pending> encoded,decoded;
    std::deque<Row> replay_expected;
    ps_adaptive::Encoder encoder;
    unsigned ia_banks=1,active_banks=Banks,depth=MaxDepth,stride=16;
    bool checking_store=false,allow_fault=false;
    std::uint64_t cycle=0,commands=0,write_rows=0,replay_rows=0,pressure_checks=0;
    std::uint64_t ia_reads=0,ia_writes=0,ps_reads=0,ps_writes=0,masked_bytes=0;
    std::uint64_t simultaneous=0,same_address=0,bypasses=0,physical_fifo_writes=0,physical_fifo_reads=0;
    std::uint64_t consecutive_commits=0,consecutive_replays=0,last_commit=UINT64_MAX,last_replay=UINT64_MAX;
    std::uint64_t directory_pressure=0,reconfigurations=0,invalid_cases=0,reset_cases=0;
    std::array<std::uint64_t,7> opcode_counts{};
    std::uint64_t expected_replay_start=UINT64_MAX;
    unsigned expected_replay_length=0;

    Check() {reset();}
    Word random_word() {Word word{};for(auto& value:word)value=random();return word;}
    void clear_ports() {
        dut.cfg_valid=0;dut.ia_read_en=0;dut.ia_write_en=0;
        dut.direct_read_en=0;dut.direct_write_en=0;
        dut.frame_request=0;dut.frame_accept=0;dut.write_valid=0;dut.write_frame_end=0;dut.replay_trigger=0;
    }
    void clear_reference() {
        frames={};directory={};owner={};current.reset();requested.clear();
        encoded.clear();decoded.clear();replay_expected.clear();encoder=ps_adaptive::Encoder();
        expected_replay_start=UINT64_MAX;expected_replay_length=0;
        last_commit=last_replay=UINT64_MAX;
    }
    void reset() {
        clear_ports();checking_store=false;allow_fault=false;dut.direct_mode=1;
        dut.rst_n=0;dut.frame_reserve_rows=0;dut.frame_word_cap=4;dut.inspect_address=0;
        dut.cfg_ia_banks=1;dut.cfg_pool_bank_words=MaxDepth;dut.cfg_pool_bank_count=Banks;dut.cfg_directory_stride=16;
        for(unsigned i=0;i<2;++i){dut.clk=0;dut.eval();dut.clk=1;dut.eval();++cycle;}
        dut.rst_n=1;dut.clk=0;dut.eval();clear_reference();
        require(!dut.configuration_ready,"External store accepted requests before configuration");
    }
    unsigned ps_address(unsigned address) const {return (ia_banks+address/MaxDepth)*MaxDepth+address%MaxDepth;}
    unsigned ia_address(unsigned address) const {return (address%ia_banks)*MaxDepth+address/ia_banks;}
    std::array<unsigned,Banks> free_counts() const {
        std::array<unsigned,Banks> result{};
        for(unsigned b=0;b<active_banks;++b)for(unsigned a=0;a<depth;++a)result[b]+=owner[b][a]==0;
        return result;
    }
    unsigned owned(unsigned bank,unsigned id) const {
        unsigned count=0;
        for(unsigned a=0;a<depth;++a) if(owner[bank][a] && (owner[bank][a]-1)/stride==id) ++count;
        return count;
    }
    void check_state() {
        if(!checking_store)return;
        const auto free=free_counts();
        std::array<std::array<unsigned,Frames>,Banks> counts{};
        for(unsigned b=0;b<Banks;++b)for(unsigned a=0;a<depth;++a)
            if(owner[b][a])++counts[b][(owner[b][a]-1)/stride];
        for(unsigned b=0;b<Banks;++b) {
            require(dut.free_counts[b]==free[b],"Bank free count differs");
            for(unsigned a=0;a<MaxDepth;++a) {
                const bool actual=(dut.free_bits[b][a/32]>>(a%32))&1U;
                require(actual==(b<active_banks && a<depth && owner[b][a]==0),"Configured free bitmap differs");
            }
            for(unsigned id=0;id<Frames;++id)
                require(dut.frame_bank_counts[b][id]==counts[b][id],"Frame bank count differs");
        }
        for(unsigned id=0;id<Frames;++id) {
            require(bool((dut.frame_valid>>id)&1U)==frames[id].valid,"Frame validity differs");
            require(dut.frame_lengths[id]==frames[id].rows.size(),"Frame length differs");
            require(dut.frame_max_words[id]==frames[id].max_words,"Frame maximum record differs");
        }
    }
    void inspect() {
        for(unsigned i=0;i<DirectoryRows;++i)if(directory[i].known) {
            dut.inspect_address=i;dut.eval();
            require(dut.inspect_descriptor==directory[i].descriptor,"Physical directory descriptor differs");
        }
    }
    void tick() {
        dut.clk=0;dut.eval();check_state();const auto edge=cycle+1;
        if(checking_store) before_store(edge);
        std::array<std::optional<Word>,2> expected_ia;
        std::array<std::optional<Word>,4> expected_ps;
        std::vector<unsigned> read_targets;
        const bool memory_active=!dut.memory_fault && !dut.cfg_valid;
        if(memory_active) {
            for(unsigned p=0;p<2;++p)if((dut.ia_read_en>>p)&1U) {
                const unsigned address=dut.ia_read_addr[p];
                if(address<ia_banks*MaxDepth) {
                    const auto physical=ia_address(address);
                    require(known[physical]==65535,"Read of uninitialized IA bytes");expected_ia[p]=memory[physical];read_targets.push_back(physical);++ia_reads;
                }
            }
            for(unsigned b=0;b<4;++b)if((dut.memory_read_en>>b)&1U) {
                const unsigned address=dut.memory_read_addr[b];
                if(address/MaxDepth<active_banks && address%MaxDepth<depth) {
                    const unsigned physical=ps_address(address);
                    require(known[physical]==65535,"Read of uninitialized PS bytes");expected_ps[b]=memory[physical];read_targets.push_back(physical);++ps_reads;
                }
            }
            for(unsigned p=0;p<2;++p)if((dut.ia_write_en>>p)&1U) {
                const unsigned address=dut.ia_write_addr[p];
                if(address>=ia_banks*MaxDepth)continue;
                const auto physical=ia_address(address);
                const auto value=get_word(dut.ia_write_data[p]);const auto mask=dut.ia_write_mask[p];
                if(mask && std::find(read_targets.begin(),read_targets.end(),physical)!=read_targets.end()){++same_address;continue;}
                for(unsigned byte=0;byte<16;++byte)if((mask>>byte)&1U) {
                    const auto byte_mask=std::uint32_t(255)<<(8*(byte%4));
                    memory[physical][byte/4]=(memory[physical][byte/4]&~byte_mask)|(value[byte/4]&byte_mask);++masked_bytes;
                }
                known[physical]|=mask;++ia_writes;
                for(unsigned r=0;r<2;++r)same_address+=((dut.ia_read_en>>r)&1U) && dut.ia_read_addr[r]==address;
            }
            for(unsigned b=0;b<4;++b)if((dut.memory_write_en>>b)&1U) {
                const unsigned address=dut.memory_write_addr[b];if(address/MaxDepth>=active_banks || address%MaxDepth>=depth)continue;
                const auto physical=ps_address(address);
                if(std::find(read_targets.begin(),read_targets.end(),physical)!=read_targets.end()){++same_address;continue;}
                memory[physical]=get_word(dut.memory_write_data[b]);
                known[physical]=65535;++ps_writes;
                same_address+=((dut.memory_read_en>>b)&1U) && dut.memory_read_addr[b]==address;
            }
            simultaneous+=bool(dut.ia_read_en || dut.ia_write_en) && bool(dut.memory_read_en || dut.memory_write_en);
        }
        dut.clk=1;dut.eval();cycle=edge;
        for(unsigned p=0;p<2;++p)if(expected_ia[p])require(get_word(dut.ia_read_data[p])==*expected_ia[p],"Synchronous IA read differs");
        for(unsigned b=0;b<4;++b)if(expected_ps[b])require(get_word(dut.memory_read_data[b])==*expected_ps[b],"Synchronous PS bank read differs");
        require(allow_fault || (!dut.memory_fault && !dut.capacity_fault),"Fault at cycle "+std::to_string(cycle)+
            " memory="+std::to_string(dut.memory_fault)+" store="+std::to_string(dut.capacity_fault)+
            " banks="+std::to_string(active_banks)+" stride="+std::to_string(stride)+
            " id="+std::to_string(dut.frame_id)+" rows="+std::to_string(dut.frame_rows)+
            " init="+std::to_string(dut.frame_init)+" final="+std::to_string(dut.frame_final)+
            " cap="+std::to_string(dut.frame_word_cap)+" raw="+std::to_string(dut.force_raw_i)+
            " read="+std::to_string(dut.read_row)+" commit="+std::to_string(dut.commit_row));
        if(checking_store)after_store(edge);
    }
    void before_store(std::uint64_t edge) {
        if(dut.prepare_start) {
            require(!current,"Two commands overlap");Current c;
            c.id=dut.frame_id;c.length=dut.frame_rows;c.initial=dut.frame_init;c.final=dut.frame_final;
            c.raw=dut.force_raw_i;c.output=requested;current=std::move(c);
            if(!current->initial)for(const auto& row:frames[current->id].rows)replay_expected.push_back(row);
            encoder=ps_adaptive::Encoder();
        }
        if(dut.frame_accept){require(current && dut.frame_ready,"Accept without ready");current->accepted=true;}
        if(dut.replay_trigger && dut.replay_armed && (dut.command_accepted || dut.frame_accept)) {
            expected_replay_start=edge+1;expected_replay_length=current->length;
        }
        if(dut.encoder_start) {
            require(current && current->accepted && !current->final,"Unexpected encoder input");
            const auto value=get_row(dut.write_data);
            require(value==current->output.at(current->captured),"Captured row differs");
            encoded.push_back({value,encode(encoder,value,current->captured==0,current->raw),current->captured,edge+4});
            ++current->captured;++write_rows;
        }
        const bool decode_due=!decoded.empty() && decoded.front().due==edge;
        require(bool(dut.decoder_done)==decode_due,"Decoder pipeline latency differs");
        if(decode_due){require(!dut.decoder_fault && get_row(dut.decoded_row)==decoded.front().row,"Decoded INT32 row differs");decoded.pop_front();}
        const bool commit_due=!encoded.empty() && encoded.front().due==edge;
        require(bool(dut.commit_valid)==commit_due,"Encoder pipeline latency differs");
        std::optional<Pending> commit;
        std::array<unsigned,4> allocation{};
        const unsigned mask=dut.memory_write_en;
        if(commit_due) {
            commit=encoded.front();encoded.pop_front();
            require(dut.commit_opcode==commit->record.opcode && dut.commit_words*16==commit->record.bytes.size(),"Encoded record format differs");
            check_packet(dut.commit_packet,commit->record,"Encoded row");
            require(current && dut.commit_row==commit->index && dut.directory_base==current->id*stride,"Commit directory address differs");
            unsigned cap=dut.frame_word_cap;
#ifdef FORCE_RAW
            cap=4;
#else
            if(current->raw)cap=4;
#endif
            const unsigned lead=(active_banks+cap-1)/cap;
            require(current->initial || current->prefetched>=std::min(current->length,commit->index+1+lead),"Commit preceded old-row prefix read");
            for(unsigned b=0;b<4;++b) {
                allocation[b]=dut.memory_write_addr[b];
                if((mask>>b)&1U)require(allocation[b]/MaxDepth<active_banks && owner[allocation[b]/MaxDepth][allocation[b]%MaxDepth]==0,"Write reused an allocated or same-cycle released word");
            }
        } else require(!mask,"Payload RAM write without an encoded row");
        if(dut.prefetch_fire) {
            require(current && !current->initial,"Prefetch outside selected old frame");
            const unsigned index=current->id*stride+current->prefetched;
            auto& entry=directory[index];
            require(entry.live && dut.directory_base==current->id*stride && dut.read_row==current->prefetched,"Prefetch directory differs");
            require(entry.record.opcode==dut.prefetch_opcode && entry.rotation==dut.read_rotation,"Read descriptor differs");
            for(unsigned b=0;b<4;++b)if((dut.memory_read_en>>b)&1U) {
                const unsigned address=dut.memory_read_addr[b];
                require(address==entry.addresses[b] && owner[address/MaxDepth][address%MaxDepth]==index+1,"Read address owner differs");owner[address/MaxDepth][address%MaxDepth]=0;
            }
            decoded.push_back({entry.row,entry.record,current->prefetched,edge+6});entry.live=false;++current->prefetched;
        } else require(!dut.memory_read_en,"RAM read without prefetch");
        if(commit) {
            const unsigned index=current->id*stride+commit->index;auto& entry=directory[index];
            require(!entry.live,"Directory overwritten before old row read");
            entry.live=entry.known=true;entry.row=commit->row;entry.record=commit->record;
            entry.rotation=dut.write_rotation;entry.addresses=allocation;
            entry.descriptor=entry.record.opcode|(entry.rotation<<3);
            for(unsigned b=0;b<4;++b) {
                entry.descriptor|=std::uint64_t(allocation[b]%MaxDepth)<<(6+AddressBits*b);
                if((mask>>b)&1U)owner[allocation[b]/MaxDepth][allocation[b]%MaxDepth]=index+1;
            }
            ++current->committed;current->max_words=std::max(current->max_words,unsigned(commit->record.bytes.size()/16));
            ++opcode_counts[entry.record.opcode];consecutive_commits+=last_commit+1==edge;last_commit=edge;
        }
        if(dut.frame_pressure)require(!dut.prepare_start && !dut.prefetch_fire && !dut.memory_read_en && !dut.memory_write_en,"Pressure altered resident data");
        bypasses+=dut.replay_bypass;physical_fifo_reads+=dut.decoded_read_en;physical_fifo_writes+=dut.decoded_write_en;
        if(dut.replay_bypass)require(!dut.decoded_read_en && !dut.decoded_write_en,"Bypass accessed FIFO RAM");
    }
    void after_store(std::uint64_t edge) {
        const bool expected=expected_replay_start!=UINT64_MAX && edge>=expected_replay_start && edge<expected_replay_start+expected_replay_length;
        require(bool(dut.replay_valid)==expected,"Replay did not deliver one row per cycle");
        if(expected) {
            require(!replay_expected.empty() && get_row(dut.replay_data)==replay_expected.front(),"Replayed INT32 values differ");
            replay_expected.pop_front();++replay_rows;consecutive_replays+=last_replay+1==edge;last_replay=edge;
        } else require(get_row(dut.replay_data)==Row{},"Inactive replay data is nonzero");
        if(dut.frame_complete) {
            require(current && current->accepted && encoded.empty() && decoded.empty() && replay_expected.empty(),"Store completed before data finished");
            auto& saved=frames[current->id];saved.valid=!current->final;
            saved.rows=current->final?std::vector<Row>{}:current->output;
            saved.max_words=current->final?0:current->max_words;
            current.reset();++commands;expected_replay_start=UINT64_MAX;expected_replay_length=0;
        }
        check_state();
    }
    void configure(unsigned banks,unsigned directory_stride,unsigned store_banks=0) {
        require(!current && dut.frame_valid==0,"Configuration changed a live task");
        clear_ports();checking_store=false;clear_reference();
        ia_banks=banks;active_banks=store_banks?store_banks:TotalBanks-banks;depth=MaxDepth;stride=directory_stride;
        dut.cfg_ia_banks=banks;dut.cfg_pool_bank_words=depth;dut.cfg_pool_bank_count=active_banks;dut.cfg_directory_stride=stride;
        dut.cfg_valid=1;tick();dut.cfg_valid=0;tick();
        require(dut.configuration_ready,"Configuration did not complete after one following edge");++reconfigurations;
        checking_store=!dut.direct_mode;check_state();
    }
    void fill_memory() {
        dut.direct_mode=1;checking_store=false;
        const unsigned ia_ports=ia_banks==1?1:2;
        for(unsigned address=0;address<ia_banks*MaxDepth;address+=ia_ports) {
            dut.ia_write_en=(1U<<ia_ports)-1;
            for(unsigned p=0;p<ia_ports;++p){dut.ia_write_addr[p]=address+p;dut.ia_write_mask[p]=65535;put_word(dut.ia_write_data[p],random_word());}
            tick();
        }
        dut.ia_write_en=0;
        for(unsigned bank=0;bank<active_banks;bank+=4) {
            const unsigned ports=std::min(4U,active_banks-bank);dut.direct_write_en=(1U<<ports)-1;
            for(unsigned row=0;row<depth;++row) {
                for(unsigned p=0;p<ports;++p){dut.direct_write_addr[p]=(bank+p)*MaxDepth+row;put_word(dut.direct_write_data[p],random_word());}tick();
            }
        }
        clear_ports();
    }
    void memory_tests() {
        for(unsigned banks:{1U,2U,4U}) {
            configure(banks,64);fill_memory();
            const unsigned ia_ports=ia_banks==1?1:2,ps_ports=std::min(4U,active_banks);
            for(unsigned iteration=0;iteration<1800;++iteration) {
                const unsigned base=ia_ports*(random()%(ia_banks*MaxDepth/ia_ports));
                dut.ia_read_en=dut.ia_write_en=(1U<<ia_ports)-1;
                for(unsigned p=0;p<ia_ports;++p) {
                    dut.ia_read_addr[p]=base+p;
                    dut.ia_write_addr[p]=(base+p+ia_banks)%(ia_banks*MaxDepth);
                    dut.ia_write_mask[p]=random()&65535;put_word(dut.ia_write_data[p],random_word());
                }
                dut.direct_read_en=dut.direct_write_en=(1U<<ps_ports)-1;
                const unsigned rotation=random()%active_banks;
                for(unsigned p=0;p<ps_ports;++p) {
                    const unsigned bank=(rotation+p)%active_banks;
                    dut.direct_read_addr[p]=bank*MaxDepth+random()%depth;
                    dut.direct_write_addr[p]=bank*MaxDepth+(dut.direct_read_addr[p]%MaxDepth+1+random()%(depth-1))%depth;
                    put_word(dut.direct_write_data[p],random_word());
                }
                tick();
            }
            clear_ports();
            if(ia_banks>=2) {
                // Four signed 16-bit values beginning at column seven span two words.
                dut.ia_write_en=3;dut.ia_write_addr[0]=0;dut.ia_write_addr[1]=1;
                dut.ia_write_mask[0]=0xc000;dut.ia_write_mask[1]=0x003f;
                Word first{},second{};first[3]=0x80000000U;second[0]=0x00017fffU;second[1]=0xffffU;
                put_word(dut.ia_write_data[0],first);put_word(dut.ia_write_data[1],second);tick();
                dut.ia_write_en=0;dut.ia_read_en=3;dut.ia_read_addr[0]=0;dut.ia_read_addr[1]=1;tick();clear_ports();
            }
        }
    }
    bool fits(unsigned id,unsigned length,bool initial,bool final,unsigned reserve,unsigned cap,bool raw)const {
        if(initial && final)return true;
        if(length>stride || (id+1)*stride>DirectoryRows)return false;
        if(final)return true;
#ifdef FORCE_RAW
        raw=true;
#endif
        const std::uint64_t budget=(std::uint64_t(raw?4:cap)*std::max(length,reserve)+active_banks-1)/active_banks;
        const auto free=free_counts();
        for(unsigned b=0;b<active_banks;++b)if(free[b]+(initial?0:owned(b,id))<budget)return false;
        return true;
    }
    bool run(unsigned id,unsigned length,bool initial,bool final,const std::vector<Row>& output,
             bool raw=false,unsigned cap=4,unsigned reserve=0,unsigned delay=3) {
        require(!current,"Frame request overlaps active command");
        dut.direct_mode=0;checking_store=true;requested=output;
        dut.frame_id=id;dut.frame_rows=length;dut.frame_reserve_rows=reserve;dut.frame_word_cap=cap;
        dut.frame_init=initial;dut.frame_final=final;dut.force_raw_i=raw;dut.frame_request=1;
        dut.clk=0;dut.eval();
        if(!fits(id,length,initial,final,reserve,cap,raw)) {
            require(dut.frame_pressure && !dut.frame_ready,"Insufficient storage did not report pressure");
            const auto saved=owner;inspect();for(unsigned t=0;t<7;++t)tick();inspect();
            require(owner==saved,"Pressure changed bank ownership");++pressure_checks;
            directory_pressure+=(id+1)*stride>DirectoryRows || length>stride;
            dut.frame_request=0;tick();return false;
        }
        unsigned waits=0;while(!dut.frame_ready){tick();require(++waits<40,"Frame prepare timeout");}
        for(unsigned t=0;t<random()%5;++t)tick();
        dut.frame_accept=1;tick();dut.frame_accept=0;dut.frame_request=0;
        const unsigned last=final?(initial?1:length+2):delay+length-1;
        for(unsigned t=0;t<=last;++t) {
            dut.replay_trigger=!initial && (t==0 || t==4);
            dut.write_valid=!final && t>=delay;
            if(dut.write_valid)put_row(dut.write_data,output.at(t-delay));
            dut.write_frame_end=t==last;tick();
        }
        dut.replay_trigger=0;dut.write_valid=0;dut.write_frame_end=0;
        waits=0;while(current){tick();require(++waits<40,"Frame completion timeout");}tick();return true;
    }
    void finish(unsigned id) {require(frames[id].valid,"Final command has no old frame");require(run(id,frames[id].rows.size(),false,true,{}),"Final frame pressure");}
    void finish_all(){for(unsigned id=Frames;id--;)if(frames[id].valid)finish(id);const auto free=free_counts();for(unsigned b=0;b<Banks;++b)require(free[b]==(b<active_banks?depth:0),"Frame completion leaked addresses");}
    void background_ia() {
        const unsigned ports=ia_banks==1?1:2;const unsigned base=ports*(random()%(ia_banks*MaxDepth/ports));dut.ia_read_en=dut.ia_write_en=(1U<<ports)-1;
        for(unsigned p=0;p<ports;++p){dut.ia_read_addr[p]=base+p;dut.ia_write_addr[p]=(base+p+ia_banks)%(ia_banks*MaxDepth);dut.ia_write_mask[p]=random()&65535;put_word(dut.ia_write_data[p],random_word());}
    }
    void store_tests() {
        dut.direct_mode=0;
        for(unsigned banks:{1U,2U,4U})for(unsigned span:{16U,32U,64U,128U,256U,512U}) {
            if(span>MaxFrameRows)continue;
            configure(banks,span);fill_memory();dut.direct_mode=0;checking_store=true;background_ia();
            const unsigned slots=std::min(Frames,DirectoryRows/span);
            const unsigned cap=std::min(4U,active_banks);
#ifdef FORCE_RAW
            if(active_banks<4){require(run(slots-1,span,true,true,{}),"Single-K command failed");clear_ports();continue;}
#endif
            const unsigned length=std::min(span,depth*active_banks/cap);
            const unsigned id=slots-1;
            require(!run(0,1,true,false,frame(1,3,random),false,cap,UINT32_MAX),
                    "Maximum reserve arithmetic admitted an oversized command");
            require(run(id,length,true,false,frame(length,cap==4?0:cap==3?5:4,random),cap==4,cap),"One maximum bounded frame failed");
            require(run(id,length,false,false,frame(length,cap==4?6:cap==3?5:4,random),cap==4,cap),"Bounded replacement failed");finish(id);
            if(slots<Frames)require(!run(slots,1,true,false,frame(1,3,random),false,cap),"Directory capacity was exceeded");
            if(span<MaxFrameRows)require(!run(0,span+1,true,false,frame(span+1,3,random),false,cap),"Directory stride was exceeded");
            for(unsigned command=0;command<100;++command) {
                const unsigned chosen=random()%Frames;
                if(frames[chosen].valid && random()%4==0){finish(chosen);continue;}
                const bool initial=!frames[chosen].valid;
                const unsigned count=initial?1+random()%std::min(span,depth):frames[chosen].rows.size();
                auto values=frame(count,cap==4?random()%7:3+random()%(cap==3?3:2),random);
                if(!run(chosen,count,initial,false,values,cap==4 && random()%5==0,cap,0,2+random()%12)) {
                    for(unsigned victim=0;victim<Frames;++victim)if(frames[victim].valid){finish(victim);break;}
                }
            }
            inspect();finish_all();clear_ports();
        }
        configure(1,MaxFrameRows);fill_memory();dut.direct_mode=0;checking_store=true;background_ia();
#ifndef FORCE_RAW
        const unsigned long_slots=DirectoryRows/MaxFrameRows;
        for(unsigned id=0;id<long_slots;++id) {
            auto values=frame(MaxFrameRows,3,random);
            require(run(id,MaxFrameRows,true,false,values,false,2),"Long COPY frame failed");
        }
        require(!run(long_slots,1,true,false,frame(1,3,random),false,2),"Excess long directory slot was accepted");
        finish_all();
        configure(2,MaxDepth);fill_memory();dut.direct_mode=0;checking_store=true;
        const unsigned s24_id=std::min(Frames,DirectoryRows/MaxDepth)-1;
        auto narrow=frame(MaxDepth,4,random);
        require(run(s24_id,MaxDepth,true,false,narrow,false,3),"S24 bounded long frame failed");
        auto changed=frame(MaxDepth,5,random);
        require(run(s24_id,MaxDepth,false,false,changed,false,3),"S24 bounded update failed");finish(s24_id);
#endif
        configure(2,64);fill_memory();dut.direct_mode=0;checking_store=true;
        require(run(15,7,true,false,frame(7,0,random),true,4,64),"Tail frame reserve failed");finish(15);
        // Reset while old rows occupy the decoder pipeline.
        require(run(3,64,true,false,frame(64,0,random),true),"Reset source failed");
        requested=frame(64,4,random);dut.frame_id=3;dut.frame_rows=64;dut.frame_reserve_rows=0;
        dut.frame_init=0;dut.frame_final=0;dut.force_raw_i=0;dut.frame_word_cap=4;dut.frame_request=1;
        for(unsigned t=0;t<4;++t)tick();reset();++reset_cases;
        configure(2,32);fill_memory();dut.direct_mode=0;checking_store=true;
        require(run(8,32,true,false,frame(32,0,random),true),"Post-reset RAW frame failed");finish(8);
    }
    void invalid_tests() {
        for(unsigned type=0;type<8;++type) {
            reset();configure(1,16);fill_memory();allow_fault=true;
            if(type==0){dut.ia_read_en=1;dut.ia_read_addr[0]=MaxDepth;}
            if(type==1){dut.direct_read_en=1;dut.direct_read_addr[0]=Banks*MaxDepth;}
            if(type==2){dut.cfg_valid=1;dut.cfg_ia_banks=3;}
            if(type==3){dut.cfg_valid=1;dut.cfg_directory_stride=MaxFrameRows+1;}
            if(type==4){dut.cfg_valid=1;dut.cfg_pool_bank_words=MaxDepth+1;}
            if(type==5){dut.ia_read_en=1;dut.ia_write_en=1;dut.ia_read_addr[0]=0;dut.ia_write_addr[0]=0;
                dut.ia_write_mask[0]=65535;put_word(dut.ia_write_data[0],random_word());}
            if(type==6){dut.direct_read_en=1;dut.direct_write_en=1;dut.direct_read_addr[0]=0;dut.direct_write_addr[0]=0;
                put_word(dut.direct_write_data[0],random_word());}
            if(type==7){dut.cfg_valid=1;dut.cfg_pool_bank_count=Banks+1;}
            tick();clear_ports();tick();
            require(dut.memory_fault || dut.capacity_fault,"Invalid configuration or address did not report a fault");++invalid_cases;
            if(type==5 || type==6) {
                reset();configure(1,16);dut.direct_mode=1;
                if(type==5){dut.ia_read_en=1;dut.ia_read_addr[0]=0;}
                else{dut.direct_read_en=1;dut.direct_read_addr[0]=0;}
                tick();clear_ports();
            }
        }
        reset();configure(1,32);fill_memory();dut.direct_mode=0;checking_store=true;
        require(run(2,16,true,false,frame(16,0,random),true),"Live configuration source failed");
        const auto saved=owner;allow_fault=true;checking_store=false;clear_ports();dut.cfg_valid=1;tick();
        require(dut.capacity_fault && dut.frame_valid==(1U<<2),"Live configuration discarded a frame");
        require(owner==saved,"Live configuration changed reference ownership");clear_ports();++invalid_cases;reset();
        configure(1,16,3);fill_memory();dut.direct_mode=0;checking_store=false;allow_fault=true;
        dut.frame_request=1;dut.frame_id=0;dut.frame_rows=1;dut.frame_reserve_rows=0;
        dut.frame_word_cap=4;dut.force_raw_i=0;dut.frame_init=1;dut.frame_final=0;
        dut.clk=0;dut.eval();require(!dut.prepare_start && !dut.frame_pressure,"Four-word request entered a three-bank pool");
        tick();require(dut.capacity_fault && !dut.memory_write_en,"Four-word request was not rejected before payload storage");
        clear_ports();++invalid_cases;reset();configure(4,16);dut.direct_mode=0;checking_store=true;
        require(run(0,16,true,true,{},true),"Single-K RAW command incorrectly required four PS banks");
        configure(4,MaxFrameRows);dut.direct_mode=0;checking_store=true;
        require(run(15,MaxFrameRows,true,true,{},true),"Single-K high frame ID incorrectly consumed directory capacity");
    }
};

int main() {
    try {
        Check check;check.memory_tests();check.store_tests();check.invalid_tests();
        require(check.simultaneous && check.same_address && check.bypasses && check.consecutive_commits && check.consecutive_replays,
                "Concurrent port or row-throughput coverage is incomplete");
        require(check.directory_pressure && check.invalid_cases==10,"Configuration coverage is incomplete");
        std::cout<<"{\"passed\":true,\"cycles\":"<<check.cycle<<",\"commands\":"<<check.commands
            <<",\"write_rows\":"<<check.write_rows<<",\"replay_rows\":"<<check.replay_rows
            <<",\"checked_int32_values\":"<<16*(check.write_rows+check.replay_rows)
            <<",\"ia_read_words\":"<<check.ia_reads<<",\"ia_write_words\":"<<check.ia_writes
            <<",\"ps_read_words\":"<<check.ps_reads<<",\"ps_write_words\":"<<check.ps_writes
            <<",\"ia_masked_write_bytes\":"<<check.masked_bytes<<",\"simultaneous_ia_ps_cycles\":"<<check.simultaneous
            <<",\"same_address_write_rejections\":"<<check.same_address<<",\"replay_bypass_rows\":"<<check.bypasses
            <<",\"decoded_ram_writes\":"<<check.physical_fifo_writes<<",\"decoded_ram_reads\":"<<check.physical_fifo_reads
            <<",\"consecutive_commit_pairs\":"<<check.consecutive_commits<<",\"consecutive_replay_pairs\":"<<check.consecutive_replays
            <<",\"pressure_checks\":"<<check.pressure_checks<<",\"directory_pressure_checks\":"<<check.directory_pressure
            <<",\"task_reconfigurations\":"<<check.reconfigurations<<",\"invalid_cases\":"<<check.invalid_cases
            <<",\"pipeline_reset_cases\":"<<check.reset_cases<<",\"opcodes\":[";
        for(unsigned i=0;i<7;++i)std::cout<<(i?",":"")<<check.opcode_counts[i];std::cout<<"]}\n";
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
