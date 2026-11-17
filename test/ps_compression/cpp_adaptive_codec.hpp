#ifndef PS_COMPRESSION_CPP_ADAPTIVE_CODEC_HPP
#define PS_COMPRESSION_CPP_ADAPTIVE_CODEC_HPP

#include "cpp_row_codec.hpp"

namespace ps_adaptive {
using ps_codec::Row;

inline void require(bool condition,const char *message) {
    if (!condition) throw std::runtime_error(message);
}

struct Profile {
    const char *name;
    bool allow_actual_values;
    bool allow_shared_width;
};

inline std::array<Profile,1> profiles() {
    return {{{"adaptive_residual_rice_q2",false,false}}};
}

struct Record {
    std::uint8_t opcode=0;
    std::vector<std::uint8_t> bytes;
    unsigned useful_bytes=0;
};

inline unsigned length(unsigned opcode) {
    if (!opcode) return 0;
    if (opcode<=3) return 16*(opcode+1);
    if (opcode<=6) return 16*(opcode-3);
    throw std::runtime_error("Invalid adaptive PS opcode");
}

inline std::uint32_t fold(std::int32_t value) {
    const auto bits=static_cast<std::uint32_t>(value);
    return (bits<<1)^(0U-(bits>>31));
}

inline std::int32_t unfold(std::uint32_t value) {
    return ps_codec::signed32((value>>1)^(0U-(value&1U)));
}

inline void put_rice(ps_codec::BitWriter &writer,std::uint32_t value,unsigned k) {
    require(k<=30,"Adaptive Rice parameter exceeds q2 range");
    const unsigned quotient=value>>k;
    require(quotient<=3,"Adaptive Rice quotient exceeds three");
    writer.write(0,quotient);writer.write(1,1);writer.write(value,k);
}

inline std::uint32_t get_rice(ps_codec::BitReader &reader,unsigned k) {
    require(k<=30,"Invalid adaptive Rice parameter");
    unsigned quotient=0;
    while (!reader.read(1)) require(++quotient<=3,"Invalid adaptive Rice unary quotient");
    const auto value=(std::uint64_t(quotient)<<k)|reader.read(k);
    require(value<=0xffffffffULL,"Adaptive Rice value exceeds uint32");
    return static_cast<std::uint32_t>(value);
}

struct Input {
    Row original{},residual{};
    unsigned mask=0,first=0,last=0;
};

inline Input prepare(const Row &row,const Row &previous) {
    Input result;result.original=row;
    for (unsigned lane=0;lane<16;++lane) {
        result.residual[lane]=ps_codec::signed32(static_cast<std::uint32_t>(row[lane])-
                                               static_cast<std::uint32_t>(previous[lane]));
        if (row[lane]!=previous[lane]) result.mask|=1U<<lane;
    }
    if (result.mask) {
        result.first=__builtin_ctz(result.mask);
        result.last=31U-__builtin_clz(result.mask);
    }
    return result;
}

struct Variable {
    std::vector<std::uint8_t> bytes;
    unsigned bits=0;
};

inline Variable variable(const Input &input,bool span) {
    require(input.mask!=0,"Adaptive variable record requires a changed lane");
    const unsigned mask=span ? ((0xffffU>>(15-(input.last-input.first)))<<input.first) : input.mask;
    unsigned width=0;
    for (unsigned lane=0;lane<16;++lane) if (mask&(1U<<lane))
        width=std::max(width,ps_codec::unsigned_width(fold(input.residual[lane])));
    const unsigned parameter=width>2 ? width-2 : 0;
    ps_codec::BitWriter writer;
    writer.write((unsigned(span)<<5)|parameter,6);
    if (span) { writer.write(input.first,4);writer.write(input.last-input.first,4); }
    else writer.write(input.mask,16);
    for (unsigned lane=0;lane<16;++lane) if (mask&(1U<<lane))
        put_rice(writer,fold(input.residual[lane]),parameter);
    return {std::move(writer.bytes),static_cast<unsigned>(writer.bits)};
}

inline Variable variable(const Input &input,bool rice,bool span,bool actual_values) {
    require(rice && !actual_values,"Adaptive encoding supports residual q2 Rice");
    return variable(input,span);
}

class Encoder {
    Row previous{};
public:
    Encoder()=default;
    explicit Encoder(Profile) {}
    Record encode(const Row &row,bool first_in_frame) {
        auto literal=ps_codec::fixed_encode(row);
        Record selected{std::uint8_t(literal.mode==ps_codec::S16 ? 1 : literal.mode==ps_codec::S24 ? 2 : 3),
                        std::move(literal.bytes),0};
        selected.useful_bytes=selected.bytes.size();
        if (!first_in_frame) {
            const auto input=prepare(row,previous);
            if (!input.mask) selected={};
            else {
                for (bool span:{false,true}) {
                    auto candidate=variable(input,span);
                    const unsigned words=(candidate.bits+127)/128;
                    require(candidate.bytes.size()==(candidate.bits+7)/8,"Adaptive byte count differs from encoded bits");
                    if (words*16<selected.bytes.size()) {
                        require(words>=1 && words<=3,"Adaptive variable allocation exceeds opcode range");
                        const auto useful=candidate.bytes.size();
                        candidate.bytes.resize(words*16,0);
                        selected={std::uint8_t(words+3),std::move(candidate.bytes),static_cast<unsigned>(useful)};
                    }
                }
            }
        }
        previous=row;
        return selected;
    }
};

class Decoder {
    Row previous{};
public:
    Decoder()=default;
    explicit Decoder(Profile) {}
    Row decode(unsigned opcode,const std::vector<std::uint8_t> &bytes,bool first_in_frame) {
        require(bytes.size()==length(opcode),"Adaptive opcode and payload length differ");
        Row row{};
        if (!opcode) {
            require(!first_in_frame,"Adaptive frame begins with COPY");
            row=previous;
        } else if (opcode<=3) {
            row=ps_codec::fixed_decode({std::uint8_t(opcode==1 ? ps_codec::S16 : opcode==2 ? ps_codec::S24 : ps_codec::RAW),bytes});
        } else {
            require(!first_in_frame,"Adaptive frame begins with a dependent record");
            ps_codec::BitReader reader(bytes);
            const unsigned header=reader.read(6),parameter=header&31;
            const bool span=header&32;
            require(parameter<=30,"Invalid adaptive Rice parameter");
            unsigned mask=0;
            if (span) {
                const unsigned first=reader.read(4),count=reader.read(4)+1;
                require(first+count<=16,"Adaptive span extends beyond the row");
                mask=(0xffffU>>(16-count))<<first;
            } else mask=reader.read(16);
            require(mask!=0,"Adaptive variable mask is empty");
            row=previous;
            for (unsigned lane=0;lane<16;++lane) if (mask&(1U<<lane)) {
                const auto value=unfold(get_rice(reader,parameter));
                row[lane]=ps_codec::signed32(static_cast<std::uint32_t>(previous[lane])+static_cast<std::uint32_t>(value));
            }
            while (reader.bits<bytes.size()*8)
                require(!reader.read(1),"Adaptive record has nonzero padding");
        }
        previous=row;
        return row;
    }
};

} // namespace ps_adaptive
#endif
