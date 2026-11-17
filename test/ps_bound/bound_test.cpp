#include "dsa_ps_bound.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
std::uint64_t checks=0, cases=0, prefixes=0, padding=0, endpoints=0;
std::array<std::uint64_t,4> formats{};

void require(bool value, const char *message) {
    ++checks;
    if (!value) throw std::runtime_error(message);
}

std::uint32_t reference(const std::vector<std::int8_t> &weights, unsigned rows,
                        unsigned depth, int input_offset, int weight_offset) {
    const unsigned retained=(depth-1u)&~15u;
    if (!retained) return 0;
    const std::int64_t low=-128+input_offset, high=127+input_offset;
    std::int64_t minimum=0, maximum=0;
    for (unsigned row=0; row<rows; ++row) {
        std::int64_t row_minimum=0, row_maximum=0;
        for (unsigned k=0; k<retained; ++k) {
            const auto w=std::int64_t(weights[row*depth+k])+weight_offset;
            row_minimum+=std::min(w*low,w*high);
            row_maximum+=std::max(w*low,w*high);
            if (k%16==15) {
                minimum=std::min(minimum,row_minimum);
                maximum=std::max(maximum,row_maximum);
                ++prefixes;
            }
        }
    }
    return minimum < -8388608 || maximum > 8388607 ? 64u :
           minimum < -32768 || maximum > 32767 ? 48u : 32u;
}

void check_case(const std::vector<std::int8_t> &weights, unsigned rows,
                unsigned depth, int input_offset=0, int weight_offset=0) {
    const unsigned wanted=reference(weights,rows,depth,input_offset,weight_offset);
    const unsigned stride=depth+7, kt=(depth+15)/16, rt=(rows+15)/16;
    std::vector<std::int8_t> ordinary(rows*stride+1,127), packed(rt*kt*256+1,-128);
    for (unsigned row=0; row<rows; ++row)
        for (unsigned k=0; k<depth; ++k) {
            ordinary[1+row*stride+k]=weights[row*depth+k];
            packed[1+((row/16)*kt+k/16)*256+(row%16)*16+k%16]=weights[row*depth+k];
        }
    require(dsa_ps_bound_s8(ordinary.data()+1,rows,depth,stride,0,
                           input_offset,weight_offset)==wanted,"Ordinary prefix bound");
    require(dsa_ps_bound_s8(packed.data()+1,rows,depth,0,1,
                           input_offset,weight_offset)==wanted,"Packed prefix bound");
    padding+=(rows*stride-rows*depth)+(rt*kt*256-rows*depth);
    ++formats[wanted==0?0:wanted==32?1:wanted==48?2:3];
    ++cases;
}

void boundaries() {
    std::vector<std::int8_t> row(17,0);
    row[0]=127; row[1]=2; row[2]=-128;
    require(reference(row,1,17,0,0)==32,"Inclusive S16 bounds");
    check_case(row,1,17);
    row[1]=3;
    require(reference(row,1,17,0,0)==48,"Outside S16 bounds");
    check_case(row,1,17);
    row.assign(529,0);
    std::fill_n(row.begin(),259,127); row[259]=4;
    std::fill_n(row.begin()+260,257,-128);
    require(reference(row,1,529,0,0)==48,"Inclusive S24 bounds");
    check_case(row,1,529);
    row[259]=5;
    require(reference(row,1,529,0,0)==64,"Outside S24 maximum");
    check_case(row,1,529);
    row[259]=4; row[517]=-1;
    require(reference(row,1,529,0,0)==64,"Outside S24 minimum");
    check_case(row,1,529);

    row.assign(17,0);
    for (unsigned k=0;k<16;++k) row[k]=std::int8_t(int(k)*11-77);
    std::int64_t minimum=INT64_MAX, maximum=INT64_MIN;
    for (unsigned mask=0;mask<65536;++mask) {
        std::int64_t sum=0;
        for (unsigned k=0;k<16;++k) sum+=std::int64_t(row[k])*((mask&(1u<<k))?127:-128);
        minimum=std::min(minimum,sum); maximum=std::max(maximum,sum); ++endpoints;
    }
    const unsigned expected=minimum < -32768 || maximum > 32767 ? 48u : 32u;
    require(dsa_ps_bound_s8(row.data(),1,17,17,0,0,0)==expected,
            "Exhaustive legal endpoint bound");
    check_case(row,1,17);
}
}

int main() {
    try {
        boundaries();
        std::mt19937 random(0x5a2416u);
        for (unsigned index=0;index<2048;++index) {
            const unsigned rows=1+random()%34, depth=1+random()%897;
            const std::array<int,5> offsets={-127,-1,0,1,128};
            const int input=offsets[random()%offsets.size()], weight=offsets[random()%offsets.size()];
            const unsigned magnitude=std::array<unsigned,5>{1,2,7,31,127}[index%5];
            std::vector<std::int8_t> weights(rows*depth);
            for (auto &value:weights) value=std::int8_t(int(random()%(2*magnitude+1))-int(magnitude));
            check_case(weights,rows,depth,input,weight);
        }
        for (unsigned depth:{1u,16u,17u,31u,32u,33u,783u,784u,785u,65535u})
            for (unsigned rows:{1u,15u,16u,17u}) {
                std::vector<std::int8_t> weights(rows*depth);
                for (unsigned i=0;i<weights.size();++i) weights[i]=std::int8_t(int(i%255)-128);
                check_case(weights,rows,depth,128,-127);
            }
        const std::array<std::int8_t,17> safe{};
        require(!dsa_ps_bound_s8(nullptr,1,17,17,0,0,0),"Null weights");
        require(!dsa_ps_bound_s8(safe.data(),0,17,17,0,0,0),"Empty channel count");
        require(!dsa_ps_bound_s8(safe.data(),1,0,0,0,0,0),"Empty reduction");
        require(!dsa_ps_bound_s8(safe.data(),1,17,16,0,0,0),"Short ordinary stride");
        require(!dsa_ps_bound_s8(safe.data(),1,17,17,2,0,0),"Unsupported packing flag");
        require(!dsa_ps_bound_s8(safe.data(),1,17,17,0,129,0),"Unsupported input offset");
        require(!dsa_ps_bound_s8(safe.data(),1,17,17,0,0,-128),"Unsupported weight offset");
        require(!dsa_ps_bound_s8(safe.data(),1,65536,65536,0,0,0),"Unsupported depth");
        require(!dsa_ps_bound_s8(reinterpret_cast<void *>(UINTPTR_MAX-7),1,17,17,0,0,0),"Address span overflow");
        std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"cases\":"<<cases
                 <<",\"prefix_channel_checks\":"<<prefixes<<",\"padding_bytes\":"<<padding
                 <<",\"endpoint_enumerations\":"<<endpoints<<",\"no_ps\":"<<formats[0]
                 <<",\"s16\":"<<formats[1]<<",\"s24\":"<<formats[2]<<",\"raw32\":"<<formats[3]<<"}\n";
    } catch (const std::exception &error) {
        std::cerr<<error.what()<<"\n";
        return 1;
    }
}
