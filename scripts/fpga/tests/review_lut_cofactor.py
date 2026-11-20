#!/usr/bin/env python3
"""编译实际余因子资格检查与 FASM 函数，核对输入排列和拒绝条件。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from review_lut_packing import PREFIX, braced


MAIN = r'''
};
static int accepted=0,rejected=0,comparisons=0;
static void need(bool result,const char *message) {
    if(!result)throw std::runtime_error(message);
}
static void mark(Harness &h,CellInfo &upper,CellInfo &lower) {
    upper.attrs[h.id("X_LUT_COFACTOR_PAIR")]=std::string("group");
    lower.attrs[h.id("X_LUT_COFACTOR_PAIR")]=std::string("group");
    rename_port(h.ctx,&lower,id_O6,id_O5);
    lower.attrs.erase(h.id("X_ORIG_PORT_O6"));
    lower.attrs[h.id("X_ORIG_PORT_O5")]=std::string("O");
    h.set_init(upper,UINT64_C(0x96a50f3c81e7d2b4));
    h.set_init(lower,UINT64_C(0x81e7d2b4));
}
static void verify(Harness &h,CellInfo &upper,CellInfo &lower) {
    need(cofactor_lut_pair_valid(h.ctx,&upper,&lower),"valid cofactor rejected");accepted++;
    auto physical=h.get_lut_init(&upper,&lower);
    for(int value=0;value<64;value++) {
        int physical_index=0;
        for(int pin=0;pin<6;pin++) {
            auto net=get_net_or_empty(&upper,h.id("A"+std::to_string(pin+1)));
            if(net)physical_index|=((value>>std::stoi(net->name.s.substr(1)))&1)<<pin;
        }
        for(auto cell:{&upper,&lower}) {
            int original_index=0;
            for(int pin=0;pin<(cell==&upper?6:5);pin++) {
                auto port=h.id("A"+std::to_string(pin+1));
                auto net=get_net_or_empty(cell,port);
                auto source=cell->attrs.at(h.id("X_ORIG_PORT_"+port.s)).as_string();
                original_index|=((value>>std::stoi(net->name.s.substr(1)))&1)<<std::stoi(source.substr(1));
            }
            bool expected=cell->params.at(h.id("INIT")).str[original_index]=='1';
            bool actual=physical.at(cell==&upper?physical_index:physical_index&31);
            need(expected==actual,"physical cofactor truth table mismatch");comparisons++;
        }
    }
}
int main() {
 try {
    Harness h;
    auto upper=h.make_cell("upper",{0,1,2,3,4,5});
    auto lower=h.make_cell("lower",{0,1,2,3,4});mark(h,upper,lower);
    std::array<int,5> order={0,1,2,3,4};
    do {
        CellInfo u=upper,l=lower;
        for(int pin=0;pin<5;pin++) {
            auto dst=h.id("A"+std::to_string(pin+1)),src=h.id("A"+std::to_string(order[pin]+1));
            for(auto pair:{std::make_pair(&u,&upper),std::make_pair(&l,&lower)}) {
                pair.first->ports[dst]=pair.second->ports.at(src);
                pair.first->ports[dst].name=dst;
                pair.first->attrs[h.id("X_ORIG_PORT_"+dst.s)]=pair.second->attrs.at(h.id("X_ORIG_PORT_"+src.s));
            }
        }
        verify(h,u,l);
    } while(std::next_permutation(order.begin(),order.end()));
    for(auto pins:{std::vector<int>{0,0,2,3,4,5},std::vector<int>{0,1,2,3,4,2}}) {
        auto u=h.make_cell("repeat_upper",pins);
        auto l=h.make_cell("repeat_lower",std::vector<int>(pins.begin(),pins.begin()+5));
        mark(h,u,l);verify(h,u,l);
    }
    for(int bit=0;bit<32;bit++) {
        auto l=lower;l.params[h.id("INIT")].str[bit]^=1;
        need(!cofactor_lut_pair_valid(h.ctx,&upper,&l),"low INIT mismatch accepted");rejected++;
        auto u=upper;u.params[h.id("INIT")].str[bit+32]^=1;verify(h,u,lower);
    }
    for(int mode=0;mode<16;mode++) {
        auto u=upper,l=lower;
        switch(mode) {
        case 0:u.attrs.erase(h.id("X_LUT_COFACTOR_PAIR"));break;
        case 1:l.attrs[h.id("X_LUT_COFACTOR_PAIR")]=std::string("other");break;
        case 2:u.attrs[h.id("X_LUT_COFACTOR_PAIR")]=std::string("");l.attrs[h.id("X_LUT_COFACTOR_PAIR")]=std::string("");break;
        case 3:u.lutInfo.is_memory=true;break;
        case 4:l.lutInfo.is_srl=true;break;
        case 5:u.lutInfo.output_count=2;break;
        case 6:l.lutInfo.output_count=2;break;
        case 7:u.ports[id_A6].net=nullptr;break;
        case 8:l.ports[id_A6]={id_A6,PORT_IN,h.net("N5")};break;
        case 9:u.attrs[h.id("X_ORIG_PORT_A6")]=std::string("I4");break;
        case 10:l.ports[id_A1].net=h.net("other_net");break;
        case 11:l.attrs[h.id("X_ORIG_PORT_A1")]=std::string("I1");break;
        case 12:u.attrs[h.id("X_ORIG_TYPE")]=std::string("LUT5");break;
        case 13:l.params.erase(h.id("INIT"));break;
        case 14:u.ports[id_O6].net=nullptr;break;
        case 15:l.ports[id_O5].net=nullptr;break;
        }
        need(!cofactor_lut_pair_valid(h.ctx,&u,&l),"incompatible cofactor accepted");rejected++;
    }
    need(!cofactor_lut_pair_valid(h.ctx,nullptr,&lower),"missing upper accepted");rejected++;
    need(!cofactor_lut_pair_valid(h.ctx,&upper,nullptr),"missing lower accepted");rejected++;
    std::cout<<"{\"passed\":true,\"accepted_configurations\":"<<accepted
             <<",\"rejected_configurations\":"<<rejected<<",\"output_comparisons\":"<<comparisons<<"}\n";
 } catch(const std::exception &error) {std::cerr<<error.what()<<"\n";return 1;}
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    place = (args.source / 'arch_place.cc').read_text()
    fasm = (args.source / 'fasm.cc').read_text()
    helper = braced(place, place.index('static bool cofactor_lut_pair_valid'))
    prefix = PREFIX.replace('struct Harness {', helper + '\nstruct Harness {')
    cpp = prefix + braced(fasm, fasm.index('std::vector<IdString> get_inputs')) + '\n'
    cpp += braced(fasm, fasm.index('std::vector<bool> get_lut_init')) + MAIN
    source = args.out / 'actual_cofactor.cc'
    source.write_text(cpp)
    binary = args.out / 'actual_cofactor'
    subprocess.run(['g++', '-O2', '-std=c++17', str(source), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    summary = json.loads(result.stdout)
    summary['source_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (args.source / 'arch_place.cc', args.source / 'fasm.cc')}
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
