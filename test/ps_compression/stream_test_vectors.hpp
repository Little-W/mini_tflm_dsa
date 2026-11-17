#ifndef PS_STREAM_TEST_VECTORS_HPP
#define PS_STREAM_TEST_VECTORS_HPP
#include "cpp_adaptive_codec.hpp"
#include <deque>
#include <random>

namespace ps_stream_test {
using ps_codec::Row;
using ps_adaptive::Record;

inline void require(bool value,const std::string &message) {
    if (!value) throw std::runtime_error(message);
}

inline Record encode(ps_adaptive::Encoder &encoder,const Row &row,bool first,bool force_raw=false) {
    auto record=encoder.encode(row,first);
#ifdef FORCE_RAW
    force_raw=true;
#endif
    if (force_raw) {
    const auto raw=ps_codec::pack_fixed(row,32,ps_codec::RAW);
    record={3,raw.bytes,64};
    }
    return record;
}

template<class Wide> inline void put_row(Wide &destination,const Row &row) {
    for (unsigned lane=0;lane<16;++lane) destination[lane]=static_cast<std::uint32_t>(row[lane]);
}
template<class Wide> inline Row get_row(const Wide &source) {
    Row row{};
    for (unsigned lane=0;lane<16;++lane) row[lane]=ps_codec::signed32(source[lane]);
    return row;
}
template<class Wide> inline void put_packet(Wide &destination,const std::vector<std::uint8_t> &packet) {
    for (unsigned word=0;word<16;++word) destination[word]=0;
    for (unsigned byte=0;byte<packet.size();++byte)
        destination[byte/4]|=std::uint32_t(packet[byte])<<(8*(byte%4));
}
template<class Wide> inline void check_packet(const Wide &source,const Record &record,const std::string &where) {
    for (unsigned byte=0;byte<64;++byte) {
        const auto actual=(source[byte/4]>>(8*(byte%4)))&255U;
        const auto expected=byte<record.bytes.size() ? record.bytes[byte] : 0U;
        require(actual==expected,where+" packet byte "+std::to_string(byte));
    }
}

inline std::vector<Row> frame(unsigned count,unsigned pattern,std::mt19937 &random) {
    std::vector<Row> result;
    Row previous{};
    for (unsigned row=0;row<count;++row) {
        Row value=previous;
        for (unsigned lane=0;lane<16;++lane) {
            switch (pattern%7) {
            case 0: value[lane]=ps_codec::signed32(random());break;
            case 1: value[lane]=row ? ps_codec::signed32(std::uint32_t(previous[lane])+1024) : 100000;break;
            case 2: value[lane]=row ? ps_codec::signed32(std::uint32_t(previous[lane])+8192) : INT32_MIN;break;
            case 3: value[lane]=row ? (row==1 && lane<11 ? -128 : previous[lane]) : 0;break;
            case 4: value[lane]=row ? previous[lane]+1 : 20000;break;
            case 5: value[lane]=static_cast<std::int32_t>(random()%8000000)-4000000;break;
            case 6:
                if (!row) value[lane]=lane%2 ? 67108864 : -67108864;
                else if (row%3==1 && lane==row%16)
                    value[lane]=ps_codec::signed32(std::uint32_t(previous[lane])+1);
                else if (row%3==2 && lane==row%16) value[lane]=row%2 ? INT32_MIN : INT32_MAX;
                break;
            }
        }
        result.push_back(value);previous=value;
    }
    return result;
}

inline std::vector<std::pair<Row,bool>> codec_rows() {
    std::mt19937 random(0x629fe17U);
    std::vector<std::pair<Row,bool>> rows;
    for (unsigned byte_width=1;byte_width<=4;++byte_width) {
        const unsigned bits=byte_width*8;
        const auto positive=ps_codec::sign_extend(bits==32 ? 0x7fffffffU : (1U<<(bits-1))-1U,bits);
        const auto negative=ps_codec::sign_extend(1U<<(bits-1),bits);
        for (unsigned count=0;count<=16;++count) {
            Row row{};
            for (unsigned lane=0;lane<count;++lane)
                row[(lane*5)%16]=lane%2 ? negative : positive;
            rows.emplace_back(row,true);
            rows.emplace_back(row,false);
            Row next=row;
            next[15]=next[15] ? 0 : negative;
            rows.emplace_back(next,false);
            rows.emplace_back(Row{},false);
        }
    }
    for (unsigned sample=0;sample<2048;++sample) {
        Row row{};
        const unsigned count=random()%17,bits=(1+random()%4)*8;
        for (unsigned lane=0;lane<count;++lane)
            row[(lane*5+sample)%16]=ps_codec::sign_extend(random(),bits);
        rows.emplace_back(row,sample%19==0);
    }
    for (unsigned pattern=0;pattern<7;++pattern)
        for (unsigned count:{1U,2U,3U,16U,17U,31U,40U,47U,128U}) {
            const auto values=frame(count,pattern,random);
            for (unsigned i=0;i<count;++i) rows.emplace_back(values[i],i==0);
        }
    for (unsigned repetition=0;repetition<2;++repetition) {
        auto values=frame(4096,repetition ? 6 : 0,random);
        for (unsigned i=0;i<values.size();++i) rows.emplace_back(values[i],i==0);
    }
    for (auto base:{INT32_MIN,INT32_MAX,-8388609,-8388608,-32769,-32768,0,32767,32768,8388607,8388608}) {
        Row previous{};previous.fill(base);rows.emplace_back(previous,true);
        for (unsigned i=0;i<32;++i) {
            Row next=previous;
            next[i%16]=ps_codec::signed32(std::uint32_t(next[i%16])+(std::uint32_t(1)<<i));
            rows.emplace_back(next,false);previous=next;
        }
    }
    for (unsigned target:{127U,128U,129U,255U,256U,257U,383U,384U,385U}) {
        Row previous{};
        if (target>200) previous.fill(INT32_MIN);
        Row value=previous;
        if (target<200) {
            for (unsigned lane=0;lane<16;++lane) if (lane<=12 || lane==15)
                value[lane]=ps_adaptive::unfold(1);
            value[0]=ps_adaptive::unfold(128);
            for (unsigned lane=1;lane<=target-122;++lane) value[lane]=ps_adaptive::unfold(64);
        } else if (target<300) {
            for (unsigned lane=0;lane<16;++lane) if (lane!=7)
                value[lane]=ps_codec::signed32(std::uint32_t(previous[lane])-1);
            value[0]=ps_codec::signed32(std::uint32_t(previous[0])+16384);
            unsigned remaining=target-249;
            for (unsigned lane=1;lane<16 && remaining;++lane) if (lane!=7) {
                value[lane]=ps_codec::signed32(std::uint32_t(previous[lane])+8192);--remaining;
            }
        } else {
            for (unsigned lane=0;lane<16;++lane) if (lane!=7)
                value[lane]=ps_codec::signed32(std::uint32_t(previous[lane])-1);
            value[0]=ps_codec::signed32(std::uint32_t(previous[0])+(1U<<22));
            unsigned remaining=target-369;
            for (unsigned lane=1;lane<16 && remaining;++lane) if (lane!=7) {
                const unsigned quotient=std::min(remaining,3U);remaining-=quotient;
                value[lane]=ps_codec::signed32(std::uint32_t(previous[lane])+
                    std::uint32_t(ps_adaptive::unfold((quotient<<22)|1)));
            }
        }
        const auto bits=ps_adaptive::variable(ps_adaptive::prepare(value,previous),false).bits;
        require(bits==target,"Directed Rice bit length differs");
        rows.emplace_back(previous,true);rows.emplace_back(value,false);
    }
    return rows;
}
} // namespace ps_stream_test
#endif
