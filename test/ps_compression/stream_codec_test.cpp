#include "Vstream_codec_tb.h"
#include "verilated.h"
#include "stream_test_vectors.hpp"
#include <iostream>
#include <map>

using namespace ps_stream_test;

int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Vstream_codec_tb dut;
        std::uint64_t cycle=0,checked=0,encoded=0,malformed=0,raw_rows=0,raw_transitions=0;
        std::array<std::uint64_t,8> opcodes{};
        std::array<std::uint64_t,4> sparse_widths{};
        std::uint64_t sparse_first_rows=0,sparse_zero_rows=0,sparse_noncontiguous_rows=0;
        auto tick=[&] { dut.clk=0;dut.eval();dut.clk=1;dut.eval();++cycle; };
        dut.rst_n=0;dut.encode_start=0;dut.read_start=0;dut.inject_start=0;
        tick();tick();dut.rst_n=1;
        const auto values=codec_rows();
        ps_adaptive::Encoder encoder;
        ps_adaptive::Decoder decoder;
        std::map<std::uint64_t,Record> expected_encoding;
        std::map<std::uint64_t,Row> expected_decoding;
        std::map<std::uint64_t,unsigned> reads;
        bool force_raw=false;
        unsigned frame_index=0;
        for (std::size_t index=0;index<values.size()+20;++index) {
            const auto next_cycle=cycle+1;
            dut.encode_start=index<values.size();
            if (dut.encode_start) {
                const auto &[row,first]=values[index];
                if (first) {
                    const bool next_raw=(frame_index++%3)==1 && index+18<values.size();
                    raw_transitions+=next_raw!=force_raw;force_raw=next_raw;
                }
                auto record=encode(encoder,row,first,force_raw);
                if (record.opcode==7) {
                    const unsigned mask=record.bytes[0]|(unsigned(record.bytes[1])<<8);
                    ++sparse_widths[record.bytes[2]&3U];
                    sparse_first_rows+=first;sparse_zero_rows+=mask==0;
                    if (mask) {
                        const unsigned normalized=mask>>__builtin_ctz(mask);
                        sparse_noncontiguous_rows+=(normalized&(normalized+1U))!=0;
                    }
                }
                raw_rows+=force_raw;
                require(decoder.decode(record.opcode,record.bytes,first)==row,"C++ round trip differs");
                dut.encode_first=first;dut.encode_force_raw=force_raw;
                put_row(dut.encode_row,row);dut.encode_slot=index%512;
                expected_encoding.emplace(next_cycle+3,record);
                reads.emplace(next_cycle+9,index%512);
                expected_decoding.emplace(next_cycle+14,row);
            }
            auto read=reads.find(next_cycle);
            dut.read_start=read!=reads.end();
            if (dut.read_start) dut.read_slot=read->second;
            tick();
            auto record=expected_encoding.find(cycle);
            require(bool(dut.encode_done)==(record!=expected_encoding.end()),"Encoder valid latency differs at "+std::to_string(cycle));
            if (record!=expected_encoding.end()) {
                require(dut.encode_opcode==record->second.opcode,"Encoder opcode differs");
                require(dut.encode_words*16==record->second.bytes.size(),"Encoder word count differs");
                check_packet(dut.encode_packet,record->second,"Encoder");
                ++opcodes[dut.encode_opcode];++encoded;
            }
            auto row=expected_decoding.find(cycle);
            require(bool(dut.decode_done)==(row!=expected_decoding.end()),"Decoder valid latency differs at "+std::to_string(cycle));
            if (row!=expected_decoding.end()) {
                require(!dut.decode_fault,"Decoder rejected stored record at "+std::to_string(cycle));
                require(get_row(dut.decode_row)==row->second,"RAM round trip differs at row "+std::to_string(checked));
                ++checked;
            }
        }
        require(encoded==values.size() && checked==values.size(),"Codec record count differs");
#ifndef FORCE_RAW
        for (auto count:opcodes) require(count!=0,"An adaptive opcode was not exercised");
        for (auto count:sparse_widths) require(count!=0,"A sparse signed width was not exercised");
        require(sparse_first_rows && sparse_zero_rows && sparse_noncontiguous_rows,"Sparse row coverage is incomplete");
#endif
        std::vector<std::tuple<unsigned,bool,std::vector<std::uint8_t>>> invalid;
        invalid.emplace_back(0,true,std::vector<std::uint8_t>{});
        invalid.emplace_back(4,true,std::vector<std::uint8_t>(16));
        auto bad=std::vector<std::uint8_t>(16);bad[0]=31;invalid.emplace_back(4,false,bad);
        bad.assign(16,0);bad[0]=0xe0;bad[1]=0x07;invalid.emplace_back(4,false,bad);
        bad.assign(16,0);invalid.emplace_back(4,false,bad);
        bad.assign(16,0);bad[0]=0x40;invalid.emplace_back(4,false,bad);
        bad.assign(16,0);bad[0]=0x40;bad[2]=0x40;bad[15]=0x80;invalid.emplace_back(4,false,bad);
        bad.assign(16,0);bad[0]=0xde;bad[1]=0xff;bad[2]=0xff;invalid.emplace_back(4,false,bad);
        auto sparse_packet=[](unsigned mask,unsigned width,const std::vector<std::uint32_t> &values) {
            ps_codec::BitWriter writer;writer.write(mask,16);writer.write(width/8-1,2);
            for (auto value:values) writer.write(value,width);
            writer.bytes.resize(16,0);return writer.bytes;
        };
        bad.assign(16,0);bad[0]=0xff;bad[1]=0xff;invalid.emplace_back(7,true,bad);
        bad=sparse_packet(0x8001,8,{1,127});bad[15]=0x80;invalid.emplace_back(7,false,bad);
        bad=sparse_packet(0x0081,16,{1,127});invalid.emplace_back(7,true,bad);
        bad=sparse_packet(0x0401,8,{0,1});invalid.emplace_back(7,false,bad);
        bad=sparse_packet(0,16,{});invalid.emplace_back(7,true,bad);
        bad=sparse_packet(0x8888,24,{0x7fffff,0x800000,0x7fffff,0x800000});
        bad[2]|=3;invalid.emplace_back(7,false,bad);
        for (const auto &[opcode,first,packet]:invalid) {
            bool rejected=false;
            try { ps_adaptive::Decoder reference;reference.decode(opcode,packet,first); }
            catch (const std::exception &) { rejected=true; }
            require(rejected,"Malformed test is accepted by C++ reference");
            dut.encode_start=0;dut.read_start=0;dut.inject_start=1;
            dut.inject_opcode=opcode;dut.inject_first=first;put_packet(dut.inject_packet,packet);
            tick();
            for (unsigned delay=1;delay<=4;++delay) {
                dut.inject_start=0;tick();
                require(bool(dut.decode_done)==(delay==4),"Malformed decode latency differs");
            }
            require(dut.decode_fault,"Malformed record did not report a fault");
            tick();require(!dut.decode_done && !dut.decode_fault,"Decoder valid or fault outlasted its result");
            ++malformed;
        }
        // Reset cancels every valid stage, including a pending result.
        dut.encode_start=1;dut.encode_first=1;put_row(dut.encode_row,values.front().first);
        dut.inject_start=1;dut.inject_first=1;dut.inject_opcode=3;
        put_packet(dut.inject_packet,ps_codec::pack_fixed(values.front().first,32,ps_codec::RAW).bytes);tick();
        dut.rst_n=0;dut.encode_start=0;dut.inject_start=0;tick();dut.rst_n=1;
        for (unsigned i=0;i<8;++i) { tick();require(!dut.encode_done && !dut.decode_done,"Reset left a valid pipeline stage"); }
        std::cout<<"{\"passed\":true,\"rows\":"<<checked<<",\"int32_values\":"<<checked*16
                 <<",\"packet_bytes_checked\":"<<encoded*64<<",\"malformed_records\":"<<malformed
                 <<",\"runtime_raw_rows\":"<<raw_rows<<",\"runtime_raw_transitions\":"<<raw_transitions
                 <<",\"sparse_first_rows\":"<<sparse_first_rows<<",\"sparse_zero_rows\":"<<sparse_zero_rows
                 <<",\"sparse_noncontiguous_rows\":"<<sparse_noncontiguous_rows<<",\"sparse_widths\":[";
        for (unsigned i=0;i<4;++i) std::cout<<(i ? "," : "")<<sparse_widths[i];
        std::cout<<"]"
                 <<",\"encoder_latency\":3,\"decoder_latency\":4,\"initiation_interval\":1,\"opcodes\":[";
        for (unsigned i=0;i<8;++i) std::cout<<(i ? "," : "")<<opcodes[i];
        std::cout<<"]}\n";
    } catch (const std::exception &error) { std::cerr<<error.what()<<"\n";return 1; }
}
