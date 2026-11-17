#include "cpp_adaptive_codec.hpp"
#include <fstream>
#include <iostream>

using ps_codec::Row;
using ps_codec::Encoded;
struct Item { std::uint32_t group, first, raw, ordinal; Row row; };
static_assert(sizeof(Item)==80);
struct Count {
    std::uint64_t rows=0, first=0, payload=0, useful=0, metadata_bits=0, raw_metadata_bits=0, nonzero=0, first_payload=0;
    std::array<std::uint64_t,5> words{};
    std::map<unsigned,std::uint64_t> formats;
};

Encoded sparse_byte(const Row &row) {
    unsigned mask=0,width=0;
    for(unsigned i=0;i<16;i++) if(row[i]) { mask|=1u<<i; width=std::max(width,ps_codec::signed_width(row[i])); }
    width=std::max(8u,((width+7u)/8u)*8u);
    ps_codec::BitWriter w;w.write(mask,16);w.write(width/8-1,2);
    for(auto x:row)if(x)w.write(std::uint32_t(x),width);
    return {32,std::move(w.bytes)};
}
Row sparse_byte_decode(const Encoded &x) {
    ps_codec::BitReader r(x.bytes);Row out{};
    unsigned mask=r.read(16),width=(r.read(2)+1)*8;
    for(unsigned i=0;i<16;i++)if(mask&(1u<<i))out[i]=ps_codec::sign_extend(r.read(width),width);
    return out;
}
Row decode_adaptive(const ps_adaptive::Record &x,bool first,const Row &prev) {
    if(!x.opcode) { ps_adaptive::require(!first,"COPY first");return prev; }
    if(x.opcode<=3)return ps_codec::fixed_decode({std::uint8_t(x.opcode==1?ps_codec::S16:x.opcode==2?ps_codec::S24:ps_codec::RAW),x.bytes});
    if(x.opcode==7)return sparse_byte_decode({32,x.bytes});
    ps_adaptive::require(!first,"Rice first");
    ps_codec::BitReader r(x.bytes);unsigned h=r.read(6),k=h&31,mask=0;
    if(h&32) { unsigned start=r.read(4),n=r.read(4)+1;mask=((0xffffu>>(16-n))<<start); }
    else mask=r.read(16);
    Row out=prev;
    for(unsigned i=0;i<16;i++)if(mask&(1u<<i))out[i]=ps_codec::signed32(std::uint32_t(prev[i])+std::uint32_t(ps_adaptive::unfold(ps_adaptive::get_rice(r,k))));
    return out;
}

ps_adaptive::Record encode_rice(const Row &row,const Row &previous,bool first) {
    auto fixed=ps_codec::fixed_encode(row);
    ps_adaptive::Record out{std::uint8_t(fixed.mode==ps_codec::S16?1:fixed.mode==ps_codec::S24?2:3),fixed.bytes,unsigned(fixed.bytes.size())};
    if(first)return out;
    const auto input=ps_adaptive::prepare(row,previous);
    if(!input.mask)return {};
    for(bool span:{false,true}) {
        auto variable=ps_adaptive::variable(input,span);
        unsigned words=(variable.bits+127)/128;
        if(words*16<out.bytes.size()) {
            unsigned useful=variable.bytes.size();variable.bytes.resize(words*16,0);
            out={std::uint8_t(words+3),std::move(variable.bytes),useful};
        }
    }
    return out;
}

int main(int argc,char **argv) {
  try {
    ps_adaptive::require(argc==4,"Expected rows.bin, recorded codec (rice or adaptive), and physical directory bits per row");
    const std::string directory_arg=argv[3];std::size_t parsed=0;
    const auto directory_value=std::stoul(directory_arg,&parsed);
    ps_adaptive::require(parsed==directory_arg.size() && directory_value>=4 && directory_value<=256,"Invalid directory width");
    const unsigned directory_bits=unsigned(directory_value);
    const bool recorded_sparse=std::string(argv[2])=="adaptive";
    ps_adaptive::require(recorded_sparse || std::string(argv[2])=="rice","Unknown recorded codec");
    const std::uint32_t endian=1;
    ps_adaptive::require(*reinterpret_cast<const unsigned char*>(&endian)==1,"Corpus input uses little endian words");
    const std::array<const char*,13> names={"observed", "raw32", "rice", "independent_s8_s16_s24_raw", "adaptive", "independent_sparse128", "rice_plus_s8_sparse128", "rice_plus_sparse_bitpack", "rice_plus_bitplane", "rice_plus_lane_tags", "rice_plus_group4", "rice_plus_base4", "rice_plus_base8"};
    std::map<unsigned,std::array<Count,13>> counts;
    std::map<unsigned,ps_adaptive::Encoder> encoders;
    std::map<unsigned,ps_adaptive::Decoder> decoders;
    std::map<unsigned,Row> previous;
    std::map<unsigned,unsigned> last_ordinal;
    std::ifstream input(argv[1],std::ios::binary);Item item{};std::uint64_t checked=0;
    while(input.read(reinterpret_cast<char*>(&item),sizeof(item))) {
        ps_adaptive::require(item.first<=1 && item.raw<=1 && bool(item.first)==(item.ordinal==0),"Invalid corpus row flags");
        ps_adaptive::require(item.first || (last_ordinal.count(item.group) && item.ordinal==last_ordinal[item.group]+1),"Nonconsecutive corpus row");
        last_ordinal[item.group]=item.ordinal;
        const auto &row=item.row;auto current=encoders[item.group].encode(row,item.first);
        ps_adaptive::require(decoders[item.group].decode(current.opcode,current.bytes,item.first)==row,"Current C++ roundtrip");
        ps_adaptive::require(decode_adaptive(current,item.first,previous[item.group])==row,"Explicit adaptive roundtrip");
        const auto rice=encode_rice(row,previous[item.group],item.first);
        const auto fixed=ps_codec::fixed_encode(row);
        unsigned width=0,nonzero=0;
        for(auto x:row){width=std::max(width,ps_codec::signed_width(x));nonzero+=x!=0;}
        const auto s8=ps_codec::pack_fixed(row,8,ps_codec::S8);
        const auto sparse=sparse_byte(row);
        const std::array<Encoded,6> extended={ps_codec::sparse_encode(row),ps_codec::bitplane_encode(row),ps_codec::lane_encode(row),ps_codec::group_encode(row,4),ps_codec::base_encode(row,4),ps_codec::base_encode(row,8)};
        for(unsigned profile=0;profile<names.size();profile++) {
            const auto &base=(profile==4 || (profile==0 && recorded_sparse))?current:rice;
            unsigned bytes=base.bytes.size(), useful=base.useful_bytes, meta=directory_bits, format=base.opcode;
            Row recovered=decode_adaptive(base,item.first,previous[item.group]);
            auto choose=[&](const Encoded &x,unsigned extra,unsigned tag,bool force=false){
                unsigned size=(x.bytes.size()+extra+15)/16*16;
                if(!force&&size>=bytes)return;
                bytes=size;useful=x.bytes.size()+extra;format=tag;
                if(extra) {
                    const std::array<unsigned,6> modes={ps_codec::SPARSE,ps_codec::BITPLANE,ps_codec::LANE_TAGS,ps_codec::GROUP4,ps_codec::BASE4,ps_codec::BASE8};
                    const auto index=std::find(modes.begin(),modes.end(),x.mode)-modes.begin();
                    ps_adaptive::require(index<6,"Unknown escaped format");
                    std::vector<std::uint8_t> packet{std::uint8_t(31u|(index<<5))};
                    packet.insert(packet.end(),x.bytes.begin(),x.bytes.end());packet.resize(size,0);
                    ps_adaptive::require((packet[0]&31u)==31u && (packet[0]>>5)<6,"Invalid escaped format header");
                    Encoded body{std::uint8_t(modes[packet[0]>>5]),{packet.begin()+1,packet.end()}};
                    recovered=ps_codec::decode(body);
                } else recovered=x.mode==32?sparse_byte_decode(x):ps_codec::decode(x);
            };
            if(profile==1||(profile==0&&item.raw)) {
                choose(ps_codec::pack_fixed(row,32,ps_codec::RAW),0,3,true);
            } else if(profile==3) {
                choose(fixed,0,100+fixed.mode,true);
                if(width<=8)choose(s8,0,107);
            } else if(profile==5) {
                choose(fixed,0,100+fixed.mode,true);
                if(sparse.bytes.size()<=16)choose(sparse,0,7);
            } else if(profile==6) {
                meta=directory_bits+1;
                if(sparse.bytes.size()<=16)choose(sparse,0,7);
                if(width<=8)choose(s8,0,8);
            } else if(profile>=7) {
                const auto &x=extended[profile-7];
                if(x.bytes.size()+1<=48)choose(x,1,200+x.mode);
            }
            ps_adaptive::require(recovered==row,"Candidate INT32 roundtrip");
            ps_adaptive::require(bytes%16==0 && bytes<=64,"Candidate physical length");
            auto &c=counts[item.group][profile];c.rows++;c.first+=item.first;c.payload+=bytes;c.useful+=useful;c.metadata_bits+=meta;c.raw_metadata_bits+=directory_bits;c.nonzero+=nonzero;c.first_payload+=item.first?bytes:0;c.words[bytes/16]++;c.formats[format]++;
            checked+=16;
        }
        previous[item.group]=row;
    }
    ps_adaptive::require(input.eof() && input.gcount()==0,"Incomplete row input");
    std::cout<<"{\"passed\":true,\"physical_payload_word_bytes\":16,\"physical_directory_bits_per_row\":"<<directory_bits<<",\"int32_roundtrip_checks\":"<<checked<<",\"groups\":[";
    bool first_group=true;
    for(const auto &[id,profiles]:counts) {
        std::cout<<(first_group?"":",")<<"{\"id\":"<<id<<",\"profiles\":[";first_group=false;
        for(unsigned p=0;p<names.size();p++) {
            const auto &c=profiles[p];std::cout<<(p?",":"")<<"{\"name\":\""<<names[p]<<"\",\"rows\":"<<c.rows<<",\"first_rows\":"<<c.first<<",\"payload_bytes\":"<<c.payload<<",\"useful_bytes\":"<<c.useful<<",\"directory_bits\":"<<c.metadata_bits<<",\"raw_directory_bits\":"<<c.raw_metadata_bits<<",\"nonzero_lanes\":"<<c.nonzero<<",\"first_payload_bytes\":"<<c.first_payload<<",\"words_histogram\":[";
            for(unsigned i=0;i<5;i++)std::cout<<(i?",":"")<<c.words[i];
            std::cout<<"],\"formats\":{";bool first_mode=true;for(auto [f,n]:c.formats){std::cout<<(first_mode?"":",")<<"\""<<f<<"\":"<<n;first_mode=false;}std::cout<<"}}";
        }
        std::cout<<"]}";
    }
    std::cout<<"]}\n";
  }catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}
}
