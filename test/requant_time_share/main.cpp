#include "Vrequant_time_share_tb.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

constexpr unsigned N=TEST_VLEN, LANES=TEST_LANES, REUSE=TEST_REUSE, BUS=TEST_BUS;
static int64_t signed32(uint32_t v){return v<0x80000000U ? int64_t(v) : int64_t(v)-0x100000000LL;}
static void require(bool v,const std::string &s){if(!v)throw std::runtime_error(s);}
static int64_t rounded_even(int64_t value,unsigned amount){
    const int64_t divisor=int64_t(1)<<amount;
    int64_t quotient=value/divisor,remainder=value%divisor;
    if(remainder<0){--quotient;remainder+=divisor;}
    return quotient+int(remainder*2>divisor || (remainder*2==divisor && quotient%2));
}
struct Row { std::array<uint8_t,N>s8{};std::array<uint16_t,N>s16{};bool last=false; };
struct Response {uint32_t address=0;unsigned words=0,delay=0;};
class Check {
public:
    Vrequant_time_share_tb dut;
    std::mt19937 random{0x6198ac43U};
    std::deque<Row> expected[2];
    std::vector<std::pair<uint32_t,unsigned>> commands[2];
    Response response[2];
    uint64_t cycles=0,outputs=0,elements=0,groups=0,clears=0,resets=0,full_groups=0,commands_count=0;
    uint64_t boundary_cases=0,boundary_rows=0,parameter_boundaries=0,overlap_starts=0;
    unsigned scenario=0;
    std::array<unsigned,2> received{};
    uint32_t multiplier(unsigned index) const {
        static const std::array<uint32_t,10> edge={0,1,0xffffffffU,0x80000000U,0x7fffffffU,0x7fff8000U,0xffff8000U,0x40000000U,0x60000000U,0x12345678U};
        if((index+scenario)%3==0)return edge[(index+scenario)%edge.size()];
        return uint32_t((index+1U)*0x4817543U+scenario*0x97123U)^0x8841abc3U;
    }
    uint32_t shift(unsigned index) const {
        static const std::array<uint32_t,22> shifts={0,1,14,15,16,30,31,32,63,64,65,0x7fffffffU,
            uint32_t(-1),uint32_t(-16),uint32_t(-31),uint32_t(-32),uint32_t(-33),uint32_t(-48),uint32_t(-49),uint32_t(-63),0x80000000U,0x8000000fU};
        return shifts[(index+scenario)%shifts.size()];
    }
    uint32_t memory(uint32_t addr)const{return addr>=0x20000U ? shift((addr-0x20000U)/4) : multiplier((addr-0x10000U)/4);}
    Row golden(unsigned row,unsigned column)const{
        Row result;result.last=dut.input_tile_done;
        for(unsigned lane=0;lane<N;++lane){
            if(column+lane>=dut.cfg_columns)continue;
            const unsigned index=dut.cfg_is ? row : column+lane;
            const uint32_t raw_multiplier=dut.cfg_per_channel ? multiplier(index) : dut.cfg_multiplier;
            const uint32_t raw_shift=dut.cfg_per_channel ? shift(index) : dut.cfg_shift;
            int64_t coefficient=signed32(raw_multiplier), amount=0;
            const int64_t shift_value=signed32(raw_shift);
            if(dut.cfg_s16){
                coefficient=std::min<int64_t>(32767,rounded_even(coefficient,16));
                if(shift_value>=15 || (raw_shift>>4)==0x8000000U)amount=0;
                else if(shift_value<-48)amount=63;
                else amount=15-shift_value;
            }else{
                if(shift_value>0)amount=(raw_shift&63U)>=31 ? 0 : 31-int64_t(raw_shift&63U);
                else if(raw_shift==0x80000000U)amount=31;
                else if(shift_value<-32)amount=64;
                else amount=31-shift_value;
            }
            __int128 quotient=0;bool increment=false;
            const __int128 product=__int128(signed32(dut.input_data[lane]))*coefficient;
            if(amount<64){
                const __int128 divisor=__int128(1)<<amount;
                quotient=product/divisor;__int128 remainder=product%divisor;
                if(remainder<0){--quotient;remainder+=divisor;}
                increment=amount!=0 && (remainder*2>divisor || (remainder*2==divisor && quotient%2));
                quotient=std::max<__int128>(-8589934592LL,std::min<__int128>(8589934591LL,quotient));
            }
            const int64_t value=int64_t(quotient)+int(increment)+(dut.cfg_s16 ? 0 : signed32(dut.cfg_offset));
            if(value<signed32(dut.cfg_min)){result.s8[lane]=uint8_t(dut.cfg_min);result.s16[lane]=uint16_t(dut.cfg_min);}
            else if(value>signed32(dut.cfg_max)){result.s8[lane]=uint8_t(dut.cfg_max);result.s16[lane]=uint16_t(dut.cfg_max);}
            else{
                result.s8[lane]=uint8_t(std::clamp<int64_t>(value,-128,127));
                result.s16[lane]=uint16_t(std::clamp<int64_t>(value,-32768,32767));
            }
        }
        return result;
    }
    void tick(){
        dut.dma_granted=uint8_t(random()&3U);dut.dma_raw_valid=0;
        for(unsigned variant=0;variant<2;++variant){
            auto &r=response[variant];
            if(r.words && !r.delay && random()%4U){
                dut.dma_raw_valid|=1U<<variant;
                uint64_t word=memory(r.address);
                if(BUS==64)word|=uint64_t(memory(r.address+4))<<32;
                dut.dma_raw_data[variant]=word;
            }
        }
        dut.clk=0;dut.eval();
        if(!dut.rst_n || dut.init_cfg){
            for(unsigned variant=0;variant<2;++variant){expected[variant].clear();response[variant]={};}
            dut.dma_raw_valid=0;
            dut.eval();
        }else{
            for(unsigned variant=0;variant<2;++variant){
                auto &r=response[variant];
                if(dut.dma_raw_valid&(1U<<variant)){r.address+=BUS/8;--r.words;}
                if(r.delay)--r.delay;
                if(dut.dma_start&(1U<<variant)){
                    require(!r.words,"Parameter DMA commands overlap");
                    r.address=dut.dma_addr[variant];r.words=unsigned(dut.dma_burst[variant])+1;r.delay=1+random()%5;
                    commands[variant].push_back({r.address,r.words});++commands_count;
                }
            }
        }
        dut.clk=1;dut.eval();++cycles;
        for(unsigned variant=0;variant<2;++variant)if(dut.output_valid&(1U<<variant)){
            require(!expected[variant].empty(),"Unexpected output");
            const Row &row=expected[variant].front();
            require(bool(dut.output_tile_done&(1U<<variant))==row.last,"Output tile boundary differs");
            for(unsigned lane=0;lane<N;++lane){
                if(dut.output_s8[variant][lane]!=row.s8[lane] || dut.output_s16[variant][lane]!=row.s16[lane]){
                    std::cerr<<"scenario="<<scenario<<" variant="<<variant<<" cycle="<<cycles<<" row="<<received[variant]<<" lane="<<lane
                             <<" actual="<<unsigned(dut.output_s8[variant][lane])<<","<<dut.output_s16[variant][lane]
                             <<" expected="<<unsigned(row.s8[lane])<<","<<row.s16[lane]<<'\n';
                    throw std::runtime_error("Quantized value differs");
                }
                elements+=2;
            }
            expected[variant].pop_front();++received[variant];++outputs;
        }
    }
    template<class Predicate>void wait(Predicate predicate){for(unsigned n=0;!predicate();++n){require(n<100000,"Quantization wait exceeded");tick();}}
    void idle(unsigned n){dut.input_valid=0;dut.input_tile_done=0;while(n--)tick();}
    void check_parallel_boundaries(){
        if(LANES!=N)return;
        struct Group {unsigned base,column,rows;};
        const std::array<unsigned,8> row_counts={1,N-1,N+1,2*N-1,2*N+1,REUSE*N,REUSE*N+1,2*REUSE*N+N};
        const std::array<unsigned,5> column_counts={1,N-1,N+1,2*N,2*N+1};
        for(unsigned mode=0;mode<8;++mode){
            for(unsigned row_count:row_counts)for(unsigned column_count:column_counts){
                ++scenario;++boundary_cases;
                dut.cfg_per_channel=mode&1U;dut.cfg_is=(mode>>1)&1U;dut.cfg_s16=(mode>>2)&1U;
                dut.cfg_min=uint32_t(dut.cfg_s16 ? -30000 : -100);dut.cfg_max=dut.cfg_s16 ? 30000 : 100;
                dut.cfg_offset=uint32_t(int(scenario%17)-8);
                dut.cfg_multiplier=dut.cfg_per_channel ? 0x10000U : multiplier(0);
                dut.cfg_shift=dut.cfg_per_channel ? 0x20000U : shift(0);
                dut.cfg_rows=row_count;dut.cfg_columns=column_count;
                dut.cfg_reuse=(scenario%3==0 ? 1U : scenario%3==1 ? std::min<unsigned>(2,REUSE) : REUSE);
                dut.input_valid=0;dut.input_tile_done=0;dut.group_start=0;
                dut.init_cfg=1;tick();dut.init_cfg=0;commands[0].clear();commands[1].clear();received={};
                std::vector<Group> work;
                for(unsigned base=0;base<row_count;base+=dut.cfg_reuse*N)
                    for(unsigned column=0;column<column_count;column+=N)
                        work.push_back({base,column,std::min<unsigned>(dut.cfg_reuse*N,row_count-base)});
                bool reserved=false;
                for(unsigned group=0;group<work.size();++group){
                    const auto current=work[group];
                    if(!reserved){
                        dut.input_valid=0;dut.input_tile_done=0;dut.group_start=0;dut.eval();
                        wait([&]{return dut.group_ready==3 && dut.params_ready==3;});
                        dut.group_rows=current.rows;dut.group_start=1;tick();dut.group_start=0;
                    }else{
                        // The array output and bias registers precede quantization input.
                        idle(2);
                    }
                    reserved=false;++groups;
                    for(unsigned row=0;row<current.rows;++row){
                        const bool final_row=row+1==current.rows;
                        const bool parameter_change=dut.cfg_per_channel && final_row &&
                            (!dut.cfg_is || current.column+N>=column_count);
                        dut.input_valid=1;dut.input_tile_done=(row%N==N-1 || final_row);
                        for(unsigned lane=0;lane<N;++lane)dut.input_data[lane]=random();
                        dut.clk=0;dut.eval();
                        require(dut.params_ready==3,"An admitted group reached unavailable parameters");
                        require(dut.group_ready==(parameter_change ? 0U : 3U),
                                "Parallel group admission differs at a parameter boundary");
                        parameter_boundaries+=parameter_change;
                        if(final_row && group+1<work.size() && dut.group_ready==3){
                            dut.group_start=1;dut.group_rows=work[group+1].rows;
                            reserved=true;++overlap_starts;
                        }
                        Row value=golden(current.base+row,current.column);
                        expected[0].push_back(value);expected[1].push_back(value);tick();
                        dut.group_start=0;++boundary_rows;
                    }
                }
                dut.input_valid=0;dut.input_tile_done=0;dut.group_start=0;
                wait([&]{return expected[0].empty() && expected[1].empty();});
                require(commands[0]==commands[1],"Parallel parameter DMA sequences differ");
                idle(8);
            }
        }
        require(boundary_cases==320 && parameter_boundaries && overlap_starts,
                "Parallel boundary coverage is incomplete");
    }
    void run(){
        dut.rst_n=0;dut.init_cfg=0;dut.input_valid=0;dut.group_start=0;tick();tick();dut.rst_n=1;
        for(scenario=0;scenario<96;++scenario){
            dut.cfg_per_channel=scenario&1;dut.cfg_is=(scenario>>1)&1;dut.cfg_s16=(scenario>>2)&1;
            dut.cfg_min=scenario%11==0 ? 0x80000000U : uint32_t(dut.cfg_s16 ? -30000 : -100);
            dut.cfg_max=scenario%11==0 ? 0x7fffffffU : uint32_t(dut.cfg_s16 ? 30000 : 100);
            dut.cfg_offset=scenario%5==0 ? 0x80000000U : scenario%5==1 ? 0x7fffffffU : uint32_t(int(random()%255)-128);
            dut.cfg_multiplier=dut.cfg_per_channel ? 0x10000U : multiplier(0);
            dut.cfg_shift=dut.cfg_per_channel ? 0x20000U : shift(0);
            unsigned reuse=1U<<(scenario%7);if(reuse>REUSE)reuse=REUSE;
            const bool maximum=scenario>=88;
            if(maximum)reuse=REUSE;
            dut.cfg_reuse=reuse;
            dut.cfg_rows=maximum ? REUSE*N+(scenario&1U) : 1+random()%(3*N+1);
            dut.cfg_columns=1+random()%(2*N+1);
            if(scenario<8)dut.cfg_rows=1;
            dut.init_cfg=1;dut.input_valid=0;dut.group_start=0;tick();dut.init_cfg=0;
            commands[0].clear();commands[1].clear();received={};
            bool canceled=false;
            for(unsigned base=0;base<dut.cfg_rows && !canceled;base+=reuse*N){
                for(unsigned column=0;column<dut.cfg_columns && !canceled;column+=N){
                    wait([&]{return (dut.group_ready&2U) && dut.params_ready==3;});
                    unsigned rows=std::min<unsigned>(reuse*N,dut.cfg_rows-base);
                    dut.group_rows=rows;dut.group_start=1;tick();dut.group_start=0;++groups;
                    full_groups+=rows==REUSE*N;
                    if(LANES<N)require(!(dut.group_ready&2U),"Group reservation did not hold");
                    for(unsigned row=0;row<rows;++row){
                        if(scenario%3==0)idle(random()%3);
                        dut.input_valid=1;dut.input_tile_done=(row%N==N-1U || row+1==rows);
                        for(unsigned lane=0;lane<N;++lane){
                            static const uint32_t edge[]={0,1,0xffffffffU,0x80000000U,0x7fffffffU};
                            dut.input_data[lane]=(row+lane+scenario)%5==0 ? edge[(row+lane)%5] : random();
                        }
                        Row value=golden(base+row,column);expected[0].push_back(value);expected[1].push_back(value);tick();
                        if((scenario%13==7 || scenario%17==9) && row+1==std::min<unsigned>(rows, N+1)){
                            dut.input_valid=0;dut.input_tile_done=0;idle(random()%8);
                            if(scenario%13==7){dut.init_cfg=1;tick();dut.init_cfg=0;++clears;}
                            else{dut.rst_n=0;tick();dut.rst_n=1;++resets;}
                            canceled=true;break;
                        }
                    }
                    dut.input_valid=0;dut.input_tile_done=0;
                    if(!canceled)wait([&]{return expected[0].empty() && expected[1].empty() && (dut.group_ready&2U);});
                }
            }
            if(!canceled)require(commands[0]==commands[1],"Parameter DMA sequence differs");
            idle(16);
        }
        check_parallel_boundaries();
        require(groups && outputs && clears && resets && full_groups,"Coverage incomplete");
        std::cout<<"{\"passed\":true,\"vlen\":"<<N<<",\"lanes\":"<<LANES<<",\"reuse\":"<<REUSE<<",\"bus\":"<<BUS
                 <<",\"cycles\":"<<cycles<<",\"outputs\":"<<outputs<<",\"elements\":"<<elements<<",\"groups\":"<<groups
                 <<",\"clears\":"<<clears<<",\"resets\":"<<resets<<",\"full_groups\":"<<full_groups<<",\"dma_commands\":"<<commands_count
                 <<",\"boundary_cases\":"<<boundary_cases<<",\"boundary_rows\":"<<boundary_rows
                 <<",\"parameter_boundaries\":"<<parameter_boundaries<<",\"overlap_starts\":"<<overlap_starts<<"}\n";
    }
};
int main(int argc,char **argv){Verilated::commandArgs(argc,argv);try{Check check;check.run();check.dut.final();}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
