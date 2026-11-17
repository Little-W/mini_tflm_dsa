#ifndef PS_COMPRESSION_CPP_ROW_CODEC_HPP
#define PS_COMPRESSION_CPP_ROW_CODEC_HPP

#include <algorithm>
#include <array>
#include <cstdint>
#include <functional>
#include <iomanip>
#include <istream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace ps_codec {

using Row = std::array<std::int32_t, 16>;
enum Mode : std::uint8_t { ZERO=0, S8=1, S16=2, S24=3, RAW=4, CONST=13, PCR=14,
    LANE_TAGS=16, SPARSE=17, GROUP4=18, GROUP8=19, BASE4=20, BASE8=21,
    PATCH4=22, PATCH8=23, PATCH16=24, BITPLANE=25 };

struct Encoded {
    std::uint8_t mode = RAW;
    std::vector<std::uint8_t> bytes;
    std::size_t words() const { return (bytes.size() + 15) / 16; }
};
using Record = Encoded;

inline std::int32_t signed32(std::uint32_t value) {
    return value < 0x80000000U ? static_cast<std::int32_t>(value)
        : static_cast<std::int32_t>(static_cast<std::int64_t>(value) - 0x100000000LL);
}

inline unsigned signed_width(std::int32_t value) {
    if (!value) return 0;
    for (unsigned width=1; width<32; ++width)
        if (-(std::int64_t(1) << (width-1)) <= value && value < (std::int64_t(1) << (width-1)))
            return width;
    return 32;
}

inline unsigned unsigned_width(std::uint32_t value) {
    return value ? 32U - static_cast<unsigned>(__builtin_clz(value)) : 0;
}

inline std::int32_t sign_extend(std::uint32_t value, unsigned width) {
    if (!width) return 0;
    if (width >= 32) return signed32(value);
    const std::uint32_t sign = std::uint32_t(1) << (width-1);
    return signed32((value ^ sign) - sign);
}

class BitWriter {
public:
    std::vector<std::uint8_t> bytes;
    std::size_t bits = 0;
    void write(std::uint64_t value, unsigned width) {
        while (width) {
            const unsigned offset=bits%8, count=std::min(width,8U-offset);
            if (!offset) bytes.push_back(0);
            bytes.back() |= static_cast<std::uint8_t>((value & ((1U<<count)-1)) << offset);
            value >>= count; width -= count; bits += count;
        }
    }
    void align_byte() { if (bits%8) write(0,8-bits%8); }
};

class BitReader {
    const std::vector<std::uint8_t> &bytes;
public:
    std::size_t bits = 0;
    explicit BitReader(const std::vector<std::uint8_t> &value):bytes(value) {}
    std::uint64_t read(unsigned width) {
        if (bits+width > bytes.size()*8) throw std::runtime_error("Truncated encoded row");
        std::uint64_t result=0; unsigned shift=0;
        while (width) {
            const unsigned offset=bits%8, count=std::min(width,8U-offset);
            result |= std::uint64_t((bytes[bits/8] >> offset) & ((1U<<count)-1)) << shift;
            width -= count; shift += count; bits += count;
        }
        return result;
    }
    void align_byte() { if (bits%8) read(8-bits%8); }
};

inline Encoded pack_fixed(const Row &values, unsigned width, std::uint8_t mode) {
    BitWriter writer;
    for (auto value:values) writer.write(static_cast<std::uint32_t>(value),width);
    return {mode,std::move(writer.bytes)};
}

inline Encoded fixed_encode(const Row &values) {
    unsigned width=0;
    for (auto value:values) width=std::max(width,signed_width(value));
    return width<=16 ? pack_fixed(values,16,S16)
         : width<=24 ? pack_fixed(values,24,S24) : pack_fixed(values,32,RAW);
}

inline Row fixed_decode(const Encoded &record) {
    unsigned width=record.mode==S8 ? 8 : record.mode==S16 ? 16 : record.mode==S24 ? 24 : 32;
    BitReader reader(record.bytes); Row result{};
    if (record.mode==ZERO) return result;
    if (record.mode==CONST) { result.fill(signed32(reader.read(32))); return result; }
    for (auto &value:result) value=sign_extend(reader.read(width),width);
    return result;
}

inline Encoded fallback_fixed(const Row &values, Encoded candidate) {
    auto fixed=fixed_encode(values);
    return candidate.words()<fixed.words() ? std::move(candidate) : std::move(fixed);
}

inline Encoded pcr_encode(const Row &values) {
    std::array<std::uint32_t,16> magnitude{};
    std::array<std::int32_t,16> difference{};
    std::vector<unsigned> active;
    unsigned active_mask=0,signs=0;
    for (unsigned lane=0;lane<16;++lane) {
        const auto bits=static_cast<std::uint32_t>(values[lane]);
        magnitude[lane]=values[lane]<0 ? 0U-bits : bits;
        if (values[lane]) { active.push_back(lane);active_mask|=1U<<lane; }
        if (values[lane]<0) signs|=1U<<lane;
    }
    std::uint32_t anchor=active.empty()?0:magnitude[active[0]];
    if (active.size()>=3) {
        std::array<std::uint32_t,3> first={magnitude[active[0]],magnitude[active[1]],magnitude[active[2]]};
        std::sort(first.begin(),first.end()); anchor=first[1];
    }
    std::array<unsigned,16> trailing{};trailing.fill(32);
    for (auto lane:active) {
        difference[lane]=signed32(magnitude[lane]-anchor);
        if (difference[lane]) trailing[lane]=__builtin_ctz(static_cast<std::uint32_t>(difference[lane]));
    }
    std::sort(trailing.begin(),trailing.end());
    const std::array<unsigned,4> shifts={0,std::min(trailing[0],31U),std::min(trailing[1],31U),std::min(trailing[2],31U)};
    std::tuple<unsigned,unsigned,unsigned> best={65,32,31};unsigned best_exceptions=0;
    for (auto shift:shifts) for (unsigned width=0;width<=32;width+=4) {
        unsigned exceptions=0;
        const auto low_mask=(std::uint32_t(1)<<shift)-1;
        for (auto lane:active) {
            const auto quotient=static_cast<std::int32_t>(static_cast<std::int64_t>(difference[lane])>>shift);
            if ((static_cast<std::uint32_t>(difference[lane])&low_mask) || signed_width(quotient)>width)
                exceptions |= 1U<<lane;
        }
        const unsigned count=__builtin_popcount(exceptions);
        const unsigned bytes=12+(active.size()*width+7)/8+4*count;
        const auto choice=std::make_tuple(bytes,width,shift);
        if (count<=2 && bytes<=64 && choice<best) { best=choice;best_exceptions=exceptions; }
    }
    const auto [length,width,shift]=best;
    if (length>64) return pack_fixed(values,32,RAW);
    BitWriter writer;
    writer.write(active_mask,16);writer.write(signs,16);writer.write(anchor,32);
    writer.write(best_exceptions,16);writer.write(shift,5);writer.write(width,6);writer.write(0,5);
    for (auto lane:active)
        writer.write(static_cast<std::uint32_t>(static_cast<std::int64_t>(difference[lane])>>shift),width);
    writer.align_byte();
    for (auto lane:active) if (best_exceptions&(1U<<lane)) writer.write(static_cast<std::uint32_t>(values[lane]),32);
    if (writer.bytes.size()!=length) throw std::runtime_error("PCR encoded length differs");
    return {PCR,std::move(writer.bytes)};
}

inline Row pcr_decode(const Encoded &record) {
    if (record.mode!=PCR) return fixed_decode(record);
    BitReader reader(record.bytes);Row values{};
    unsigned active=reader.read(16),signs=reader.read(16);
    std::uint32_t anchor=reader.read(32);
    unsigned exceptions=reader.read(16),shift=reader.read(5),width=reader.read(6);reader.read(5);
    for (unsigned lane=0;lane<16;++lane) if (active&(1U<<lane)) {
        auto quotient=sign_extend(reader.read(width),width);
        auto magnitude=anchor+(static_cast<std::uint32_t>(quotient)<<shift);
        values[lane]=signed32(signs&(1U<<lane) ? 0U-magnitude : magnitude);
    }
    reader.align_byte();
    for (unsigned lane=0;lane<16;++lane) if (exceptions&(1U<<lane)) values[lane]=signed32(reader.read(32));
    return values;
}

inline Encoded legacy_encode(const Row &values, unsigned enabled=63) {
    auto best=pack_fixed(values,32,RAW);
    auto choose=[&](Encoded candidate) {
        if (std::make_pair(candidate.bytes.size(),candidate.mode)<std::make_pair(best.bytes.size(),best.mode))
            best=std::move(candidate);
    };
    unsigned width=0;bool same=true;
    for (auto value:values) { width=std::max(width,signed_width(value));same &= value==values[0]; }
    if (enabled&32) choose(pcr_encode(values));
    if ((enabled&8) && width<=24) choose(pack_fixed(values,24,S24));
    if ((enabled&4) && width<=16) choose(pack_fixed(values,16,S16));
    if ((enabled&2) && width<=8) choose(pack_fixed(values,8,S8));
    if ((enabled&16) && same) {
        BitWriter writer;writer.write(static_cast<std::uint32_t>(values[0]),32);choose({CONST,std::move(writer.bytes)});
    }
    if ((enabled&1) && !width) choose({ZERO,{}});
    return best;
}

inline Encoded lane_encode(const Row &values) {
    BitWriter writer;std::array<unsigned,16> widths{};
    for (unsigned lane=0;lane<16;++lane) {
        widths[lane]=(signed_width(values[lane])+7)/8*8;
        writer.write(widths[lane]/8,3);
    }
    for (unsigned lane=0;lane<16;++lane) writer.write(static_cast<std::uint32_t>(values[lane]),widths[lane]);
    return {LANE_TAGS,std::move(writer.bytes)};
}

inline Encoded sparse_encode(const Row &values) {
    unsigned mask=0,width=0;
    for (unsigned lane=0;lane<16;++lane) if (values[lane]) { mask|=1U<<lane;width=std::max(width,signed_width(values[lane])); }
    BitWriter writer;writer.write(mask,16);writer.write(width,6);
    for (auto value:values) if (value) writer.write(static_cast<std::uint32_t>(value),width);
    return {SPARSE,std::move(writer.bytes)};
}

inline Encoded group_encode(const Row &values,unsigned group) {
    BitWriter writer;
    for (unsigned first=0;first<16;first+=group) {
        unsigned width=0;
        for (unsigned lane=first;lane<first+group;++lane) width=std::max(width,signed_width(values[lane]));
        writer.write(width,6);
        for (unsigned lane=first;lane<first+group;++lane) writer.write(static_cast<std::uint32_t>(values[lane]),width);
    }
    return {std::uint8_t(group==4?GROUP4:GROUP8),std::move(writer.bytes)};
}

inline Encoded base_encode(const Row &values,unsigned group) {
    BitWriter writer;
    for (unsigned first=0;first<16;first+=group) {
        const auto base=values[first];std::array<std::int32_t,8> differences{};unsigned width=0;
        for (unsigned offset=1;offset<group;++offset) {
            differences[offset]=signed32(static_cast<std::uint32_t>(values[first+offset])-static_cast<std::uint32_t>(base));
            width=std::max(width,signed_width(differences[offset]));
        }
        const unsigned base_width=signed_width(base);
        writer.write(base_width,6);writer.write(width,6);writer.write(static_cast<std::uint32_t>(base),base_width);
        for (unsigned offset=1;offset<group;++offset) writer.write(static_cast<std::uint32_t>(differences[offset]),width);
    }
    return {std::uint8_t(group==4?BASE4:BASE8),std::move(writer.bytes)};
}

inline Encoded patch_encode(const Row &values,unsigned group) {
    BitWriter writer;
    for (unsigned first=0;first<16;first+=group) {
        unsigned best_width=32,best_mask=0,best_bits=32*group;
        for (unsigned width=0;width<=32;++width) {
            unsigned mask=0;
            for (unsigned offset=0;offset<group;++offset) if (signed_width(values[first+offset])>width) mask|=1U<<offset;
            unsigned exceptions=__builtin_popcount(mask),bits=(group-exceptions)*width+exceptions*32;
            if (bits<best_bits || (bits==best_bits && width<best_width)) { best_bits=bits;best_width=width;best_mask=mask; }
        }
        writer.write(best_width,6);writer.write(best_mask,group);
        for (unsigned offset=0;offset<group;++offset)
            writer.write(static_cast<std::uint32_t>(values[first+offset]),best_mask&(1U<<offset)?32:best_width);
    }
    return {std::uint8_t(group==4?PATCH4:group==8?PATCH8:PATCH16),std::move(writer.bytes)};
}

inline Encoded bitplane_encode(const Row &values) {
    std::array<std::uint16_t,32> planes{};
    for (unsigned lane=0;lane<16;++lane) {
        auto value=(static_cast<std::uint32_t>(values[lane])<<1)^(values[lane]<0?UINT32_MAX:0);
        for (unsigned bit=0;bit<32;++bit) planes[31-bit]|=((value>>bit)&1U)<<lane;
    }
    BitWriter writer;
    for (unsigned plane=0;plane<32;) {
        const unsigned value=planes[plane];
        if (!value) {
            unsigned count=1;while (plane+count<32 && !planes[plane+count]) ++count;
            writer.write(0,3);writer.write(count-1,5);plane+=count;
        } else {
            if (value==65535) writer.write(1,3);
            else if (__builtin_popcount(value)==1) { writer.write(2,3);writer.write(__builtin_ctz(value),4); }
            else if (value==(3U<<__builtin_ctz(value))) { writer.write(3,3);writer.write(__builtin_ctz(value),4); }
            else { writer.write(4,3);writer.write(value,16); }
            ++plane;
        }
    }
    return {BITPLANE,std::move(writer.bytes)};
}

inline Row decode(const Encoded &record) {
    if (record.mode<=CONST) return fixed_decode(record);
    if (record.mode==PCR) return pcr_decode(record);
    BitReader reader(record.bytes);Row values{};
    if (record.mode==LANE_TAGS) {
        std::array<unsigned,16> widths{};for (auto &width:widths) width=8*reader.read(3);
        for (unsigned lane=0;lane<16;++lane) values[lane]=sign_extend(reader.read(widths[lane]),widths[lane]);
    } else if (record.mode==SPARSE) {
        unsigned mask=reader.read(16),width=reader.read(6);
        for (unsigned lane=0;lane<16;++lane) if (mask&(1U<<lane)) values[lane]=sign_extend(reader.read(width),width);
    } else if (record.mode==GROUP4 || record.mode==GROUP8) {
        unsigned group=record.mode==GROUP4?4:8;
        for (unsigned first=0;first<16;first+=group) {
            unsigned width=reader.read(6);
            for (unsigned lane=first;lane<first+group;++lane) values[lane]=sign_extend(reader.read(width),width);
        }
    } else if (record.mode==BASE4 || record.mode==BASE8) {
        unsigned group=record.mode==BASE4?4:8;
        for (unsigned first=0;first<16;first+=group) {
            unsigned base_width=reader.read(6),width=reader.read(6);
            auto base=sign_extend(reader.read(base_width),base_width);values[first]=base;
            for (unsigned lane=first+1;lane<first+group;++lane)
                values[lane]=signed32(static_cast<std::uint32_t>(base)+static_cast<std::uint32_t>(sign_extend(reader.read(width),width)));
        }
    } else if (record.mode==PATCH4 || record.mode==PATCH8 || record.mode==PATCH16) {
        unsigned group=record.mode==PATCH4?4:record.mode==PATCH8?8:16;
        for (unsigned first=0;first<16;first+=group) {
            unsigned width=reader.read(6),mask=reader.read(group);
            for (unsigned offset=0;offset<group;++offset) {
                unsigned bits=mask&(1U<<offset)?32:width;
                values[first+offset]=sign_extend(reader.read(bits),bits);
            }
        }
    } else if (record.mode==BITPLANE) {
        std::array<std::uint32_t,16> unsigned_values{};
        for (unsigned plane=0;plane<32;) {
            unsigned tag=reader.read(3),value=0;
            if (tag==0) {
                unsigned count=reader.read(5)+1;
                if (plane+count>32) throw std::runtime_error("Invalid bitplane zero run");
                plane+=count;continue;
            }
            if (tag==1) value=65535;
            else if (tag==2) value=1U<<reader.read(4);
            else if (tag==3) { unsigned position=reader.read(4);if(position>=15) throw std::runtime_error("Invalid adjacent bit pair");value=3U<<position; }
            else if (tag==4) value=reader.read(16);
            else throw std::runtime_error("Invalid bitplane tag");
            for (unsigned lane=0;lane<16;++lane) unsigned_values[lane]|=((value>>lane)&1U)<<(31-plane);
            ++plane;
        }
        for (unsigned lane=0;lane<16;++lane)
            values[lane]=signed32((unsigned_values[lane]>>1)^(0U-(unsigned_values[lane]&1U)));
    } else throw std::runtime_error("Unknown codec mode");
    return values;
}

struct Candidate {
    std::string name;
    std::function<Encoded(const Row&)> encode;
    std::function<Row(const Encoded&)> decode;
};

inline std::vector<Candidate> candidates() {
    return {{"lane_tags",lane_encode,decode},{"sparse_bitpack",sparse_encode,decode},
        {"group4_bitwidth",[](const Row &row){return group_encode(row,4);},decode},
        {"group8_bitwidth",[](const Row &row){return group_encode(row,8);},decode},
        {"base4_delta",[](const Row &row){return base_encode(row,4);},decode},
        {"base8_delta",[](const Row &row){return base_encode(row,8);},decode},
        {"patch4",[](const Row &row){return patch_encode(row,4);},decode},
        {"patch8",[](const Row &row){return patch_encode(row,8);},decode},
        {"patch16",[](const Row &row){return patch_encode(row,16);},decode},
        {"bitplane_patterns",bitplane_encode,decode}};
}

inline Row from_hex(const std::string &text) {
    if (text.size()!=128) throw std::runtime_error("Expected 512-bit hexadecimal row");
    Row result{};
    for (unsigned lane=0;lane<16;++lane) result[lane]=signed32(std::stoul(text.substr(120-lane*8,8),nullptr,16));
    return result;
}

struct TraceEvent {
    char kind=0;
    std::uint64_t cycle=0;
    unsigned job=0,flags=0,write_address=0,read_address=0,frame=0,rows=0;
    unsigned conv=0,is_mode=0,k=0,n=0,m=0;
    Row write_row{},read_row{};
    std::map<std::string,std::uint64_t> fields;
};

inline bool read_trace_line(std::istream &stream,TraceEvent &event) {
    std::string line;
    if (!std::getline(stream,line)) return false;
    event=TraceEvent{};std::istringstream fields(line);fields>>event.kind;
    if (event.kind=='E') {
        std::string write,read;
        fields>>event.cycle>>event.job>>event.flags>>event.write_address>>event.read_address>>write>>read;
        event.write_row=from_hex(write);event.read_row=from_hex(read);
    } else if (event.kind=='J') fields>>event.cycle>>event.job>>event.conv>>event.is_mode>>event.k>>event.n>>event.m;
    else if (event.kind=='F') fields>>event.cycle>>event.job>>event.frame>>event.rows;
    else if (event.kind=='H' || event.kind=='S') {
        std::string entry;
        while (fields>>entry) {
            auto split=entry.find('=');
            if (split==std::string::npos) throw std::runtime_error("Invalid trace metadata");
            event.fields[entry.substr(0,split)]=std::stoull(entry.substr(split+1));
        }
        return true;
    } else throw std::runtime_error("Unknown PS trace record");
    if (!fields) throw std::runtime_error("Incomplete PS trace record");
    return true;
}

inline std::uint64_t record_digest(std::uint64_t hash,const Encoded &record) {
    auto update=[&](std::uint8_t byte){hash=(hash^byte)*1099511628211ULL;};
    update(record.mode);update(record.bytes.size());for (auto byte:record.bytes) update(byte);
    return hash;
}

} // namespace ps_codec
#endif
