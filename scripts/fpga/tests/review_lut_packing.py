#!/usr/bin/env python3
"""Extract the actual nextpnr INIT implementation and compare independent tables."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess


def braced(text, start):
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


PREFIX = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <map>
#include <memory>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
struct Context;
struct IdString {
    std::string s;
    IdString() = default;
    IdString(const char *x):s(x) {}
    IdString(const std::string &x):s(x) {}
    const std::string &str(const void *) const { return s; }
    const char *c_str(const void *) const { return s.c_str(); }
    bool operator==(const IdString &x) const { return s == x.s; }
    bool operator!=(const IdString &x) const { return s != x.s; }
    bool operator<(const IdString &x) const { return s < x.s; }
};
namespace std { template<> struct hash<IdString> {
    size_t operator()(const IdString &x) const { return hash<string>{}(x.s); }
}; }
struct Property {
    static constexpr char S1='1';
    std::string str;
    Property() = default;
    Property(const std::string &x):str(x) {}
    Property extract(int low,int width) const {
        Property r; r.str.resize(width,'0');
        for(int i=0;i<width;i++) if(low+i<int(str.size())) r.str[i]=str[low+i];
        return r;
    }
    std::string as_string() const { return str; }
};
struct CellInfo;
struct PortRef { CellInfo *cell=nullptr; IdString port; };
struct NetInfo { IdString name; std::vector<PortRef> users; PortRef driver; };
enum { PORT_IN, PORT_OUT };
struct PortInfo { IdString name; int type=PORT_IN; NetInfo *net=nullptr; };
struct LutInfo {
    int input_count=0,output_count=1;
    NetInfo *input_sigs[6]={};
    NetInfo *output_sigs[2]={};
    bool is_memory=false,is_srl=false,only_drives_carry=false;
};
struct CellInfo {
    IdString name;
    IdString type;
    LutInfo lutInfo;
    struct { NetInfo *d=nullptr; } ffInfo;
    struct { NetInfo *out_sigs[4]={},*cout_sigs[4]={}; } carryInfo;
    CellInfo *constr_parent=nullptr;
    std::vector<CellInfo*> constr_children;
    bool constr_abs_z=false;
    int constr_x=0,constr_y=0,constr_z=0;
    int belStrength=0;
    std::unordered_map<IdString,Property> attrs,params;
    std::unordered_map<IdString,PortInfo> ports;
};
enum { BEL_6LUT=0,BEL_5LUT=1,BEL_FF=2,BEL_FF2=3,BEL_F7MUX=7,BEL_F8MUX=8,BEL_F9MUX=9,BEL_CARRY4=15 };
struct LogicTileStatus { CellInfo *cells[128]={}; };
struct Context {
    IdString id(const std::string &s) const { return IdString(s); }
    const char *nameOf(CellInfo *c) const { return c->name.s.c_str(); }
};
const IdString id_A1("A1"),id_A2("A2"),id_A3("A3"),id_A4("A4"),id_A5("A5"),id_A6("A6"),id_O5("O5"),id_O6("O6"),id_BEL("BEL");
const IdString id_CARRY4("CARRY4"),id_CIN("CIN"),id_Q("Q");
const IdString id_SLICE_LUTX("SLICE_LUTX");
const IdString id_D("D");
const IdString id_DI0("DI0"),id_DI1("DI1"),id_DI2("DI2"),id_DI3("DI3");
std::string str_or_default(const std::unordered_map<IdString,Property>&m,IdString k,const std::string&d="") {
    auto i=m.find(k); return i==m.end()?d:i->second.str;
}
Property get_or_default(const std::unordered_map<IdString,Property>&m,IdString k,Property d) {
    auto i=m.find(k); return i==m.end()?d:i->second;
}
bool bool_or_default(const std::unordered_map<IdString,Property>&m,IdString k,bool d=false) {
    auto i=m.find(k); return i==m.end()?d:i->second.str.find('1')!=std::string::npos;
}
NetInfo *get_net_or_empty(const CellInfo *c, IdString p) {
    auto it=c->ports.find(p); return it==c->ports.end()?nullptr:it->second.net;
}
void disconnect_port(Context *,CellInfo *c,IdString p) {
    auto i=c->ports.find(p); if(i!=c->ports.end()) i->second.net=nullptr;
}
void connect_port(Context *,NetInfo*n,CellInfo*c,IdString p) {
    assert(c->ports.count(p)); assert(!c->ports.at(p).net);
    c->ports.at(p).net=n;
}
void rename_port(Context *,CellInfo*c,IdString from,IdString to) {
    auto i=c->ports.find(from); if(i==c->ports.end()) return;
    PortInfo p=i->second; c->ports.erase(i); p.name=to; c->ports[to]=p;
}
[[noreturn]] void log_error(const char *fmt,...) {
    char s[1024];va_list a;va_start(a,fmt);vsnprintf(s,sizeof(s),fmt,a);va_end(a);throw std::runtime_error(s);
}
void log_warning(const char *,...) {}
void log_info(const char *,...) {}
#define NPNR_ASSERT_FALSE(s) throw std::runtime_error(s)
#define DBG() do {} while (0)
struct Harness {
    Context context; Context *ctx=&context;
    std::unordered_map<IdString,std::unique_ptr<NetInfo>> nets;
    IdString id(const std::string &s) { return ctx->id(s); }
    Context *getCtx() { return ctx; }
    const char *nameOf(CellInfo*c) { return ctx->nameOf(c); }
    NetInfo *net(const std::string &s) {
        auto k=id(s);if(!nets.count(k)) nets[k]=std::make_unique<NetInfo>(NetInfo{k});return nets.at(k).get();
    }
    CellInfo make_cell(const std::string &name,const std::vector<int>&v) {
        CellInfo c;c.name=id(name);c.attrs[id("X_ORIG_TYPE")]=std::string("LUT")+std::to_string(v.size());
        c.attrs[id("X_LUT_LOGICAL_OUTPUT")]=std::string("1");
        for(size_t i=0;i<v.size();i++) {
            auto p=id("A"+std::to_string(i+1));auto n=net("N"+std::to_string(v[i]));
            c.ports[p]={p,PORT_IN,n};c.attrs[id("X_ORIG_PORT_"+p.s)]=std::string("I")+std::to_string(i);
            c.lutInfo.input_sigs[c.lutInfo.input_count++]=n;
        }
        c.ports[id_O6]={id_O6,PORT_OUT,net(name+"_out")}; c.attrs[id("X_ORIG_PORT_O6")]=std::string("O");
        c.lutInfo.output_sigs[0]=net(name+"_out");
        return c;
    }
    void set_init(CellInfo &c,uint64_t value) {
        Property p;for(int i=0;i<64;i++) p.str+=(value>>i&1)?'1':'0';c.params[id("INIT")]=p;
    }
'''

SUFFIX = r'''
};
static long long cases=0,comparisons=0,permutations=0;
static void need(bool value,const char *what) { if(!value) throw std::runtime_error(what); }
static uint64_t basis(int k) {
    uint64_t n=0;for(int i=0;i<32;i++) if(k==5||(i&(1<<k))) n|=uint64_t(1)<<i;return n;
}
static int original(uint64_t init,const std::vector<int>&pins,int assignment) {
    unsigned index=0;for(size_t k=0;k<pins.size();k++) if(assignment&(1<<pins[k])) index|=1u<<k;
    return int(init>>index&1);
}
static void compare(Harness &h,CellInfo &l6,CellInfo &l5,const std::vector<int>&a,const std::vector<int>&b,uint64_t x,uint64_t y) {
    h.set_init(l6,x);h.set_init(l5,y);auto physical=h.get_lut_init(&l6,&l5);
    std::array<NetInfo*,6> wires{};
    for(int k=0;k<6;k++) {
        auto p=h.id("A"+std::to_string(k+1)); auto n6=get_net_or_empty(&l6,p),n5=get_net_or_empty(&l5,p);
        need(!n6||!n5||n6==n5,"different signals share one physical LUT input");wires[k]=n6?n6:n5;
    }
    for(int v=0;v<32;v++) {
        unsigned pi=0;
        for(int k=0;k<6;k++) if(wires[k]) {
            if(wires[k]->name.s=="$PACKER_VCC_NET") pi|=1u<<k;
            else {int n=std::stoi(wires[k]->name.s.substr(1));if(v&(1<<n)) pi|=1u<<k;}
        }
        need(physical.at(pi)==bool(original(x,a,v)),"O6 truth table mismatch");
        need(physical.at(pi&31)==bool(original(y,b,v)),"O5 truth table mismatch");comparisons+=2;
    }
    cases++;
}
static void layouts(std::vector<std::vector<int>>&out,std::vector<int> cur={}) {
    if(!cur.empty()) out.push_back(cur);
    if(cur.size()==5)return;
    for(int n=0;n<5;n++) if(std::find(cur.begin(),cur.end(),n)==cur.end()) {
        auto next=cur;next.push_back(n);layouts(out,next);
    }
}
static int check_outmux(Harness &h) {
    int count=0;
    auto test=[&](bool result,bool wanted) {need(result==wanted,"OUTMUX ownership mismatch");count++;};
    LogicTileStatus lts;
    CellInfo lower=h.make_cell("lower_mux",{0}),outside,ff1,ff2,cy,next_carry;
    cy.type=id_CARRY4;next_carry.type=id_CARRY4;
    lts.cells[BEL_5LUT]=&lower;
    NetInfo *o5=lower.lutInfo.output_sigs[0];o5->users={{&outside,{}}};
    test(h.outmux_check(lts),true);
    lts.cells[BEL_FF2]=&ff2;auto q5=h.net("q5");q5->users={{&outside,{}}};ff2.ports[id_Q]={id_Q,PORT_OUT,q5};
    test(h.outmux_check(lts),false);
    ff2.ffInfo.d=o5;o5->users={{&ff2,id_D}};test(h.outmux_check(lts),true);
    lts.cells[BEL_FF2]=nullptr;ff2.ffInfo.d=nullptr;o5->users={{&outside,{}}};
    lts.cells[BEL_CARRY4]=&cy;auto sum=h.net("carry_sum");sum->users={{&outside,{}}};cy.carryInfo.out_sigs[0]=sum;
    test(h.outmux_check(lts),false);
    lower.lutInfo.only_drives_carry=true;o5->users={{&cy,IdString("DI0")}};test(h.outmux_check(lts),true);
    lower.lutInfo.only_drives_carry=false;o5->users={{&outside,{}}};
    lts.cells[BEL_FF]=&ff1;ff1.ffInfo.d=sum;sum->users={{&ff1,id_D}};test(h.outmux_check(lts),true);
    auto co=h.net("carry_co");co->users={{&outside,{}}};cy.carryInfo.cout_sigs[0]=co;test(h.outmux_check(lts),false);
    co->users={{&next_carry,id_CIN}};test(h.outmux_check(lts),false);
    cy.carryInfo.cout_sigs[0]=nullptr;ff1.ffInfo.d=o5;o5->users={{&ff1,id_D}};sum->users={{&outside,{}}};
    test(h.outmux_check(lts),true);
    return count;
}
static int check_candidates(Harness &h) {
    int n=0;
    for(int width=1;width<=5;width++) {
        std::vector<int>pins(width);for(int i=0;i<width;i++)pins[i]=i;
        auto c=h.make_cell("candidate",pins);need(h.candidate_check(&c),"ordinary LUT candidate rejected");n++;
    }
    auto c=h.make_cell("candidate",{0,1,2});
    c.attrs.erase(h.id("X_LUT_LOGICAL_OUTPUT"));need(!h.candidate_check(&c),"unmarked O6 cell accepted");n++;
    c.attrs[h.id("X_LUT_LOGICAL_OUTPUT")]=std::string("1");
    c.lutInfo.is_memory=true;need(!h.candidate_check(&c),"RAM accepted as ordinary logic candidate");n++;
    c.lutInfo.is_memory=false;c.lutInfo.is_srl=true;need(!h.candidate_check(&c),"SRL accepted as ordinary logic candidate");n++;
    c.lutInfo.is_srl=false;c.lutInfo.output_count=2;need(!h.candidate_check(&c),"dual-output candidate accepted");n++;
    c=h.make_cell("six_candidate",{0,1,2,3,4,0});need(!h.candidate_check(&c),"six-port candidate accepted");n++;
    return n;
}
static int check_muxf(Harness &h) {
    CellInfo mux7,upper=h.make_cell("mux_input0",{0,1}),lower=h.make_cell("mux_input1",{2,3});
    mux7.type=h.id("MUXF7");upper.type=h.id("LUT2");lower.type=h.id("LUT2");
    auto n0=h.net("mux_n0"),n1=h.net("mux_n1");n0->driver={&upper,id_O6};n1->driver={&lower,id_O6};
    mux7.ports[h.id("I0")]={h.id("I0"),PORT_IN,n0};mux7.ports[h.id("I1")]={h.id("I1"),PORT_IN,n1};
    h.constrain_muxf_tree(&mux7,&mux7,0);
    need(upper.constr_parent==&mux7&&lower.constr_parent==&mux7,"MUXF input constraint lost");
    need(upper.constr_z+BEL_F7MUX==16+BEL_6LUT,"MUXF upper input no longer on 6LUT");
    need(lower.constr_z+BEL_F7MUX==BEL_6LUT,"MUXF lower input no longer on 6LUT");
    need(BEL_5LUT+(BEL_FF-BEL_6LUT)==BEL_FF2,"LUT to FF relative position inconsistent");
    return 4;
}
static int check_lut6_2(Harness &h) {
    int checked=0;
    for(int mode=-1;mode<=2;mode++) {
        auto halves=h.split_parameters(mode);
        int upper_count=halves.at(1).first,upper_low=halves.at(1).second;
        need(halves.at(0)==std::make_pair(5,0),"LUT6_2 O5 half not lower 32 bits");
        need(upper_count==(mode==2?6:5),"LUT6_2 O6 width mismatch");
        for(int bit=0;bit<64;bit++) {
            uint64_t init=uint64_t(1)<<bit;
            std::vector<int>up={0,1,2,3,4};if(upper_count==6)up.push_back(5);
            auto l6=h.make_cell("split_upper",up),l5=h.make_cell("split_lower",{0,1,2,3,4});
            h.set_init(l6,init>>upper_low);h.set_init(l5,init&0xffffffffu);
            if(mode!=2)h.fixup(&l6,&l5);
            auto upper_bits=h.get_lut_init(&l6,mode==2?nullptr:&l5);
            auto lower_bits=mode==2?h.get_lut_init(nullptr,&l5):upper_bits;
            for(int i=0;i<(mode==2?64:32);i++) {
                int original_i=i|((mode==1)?32:0),physical_i=i|((mode!=2)?32:0);
                need(upper_bits.at(physical_i)==bool(init>>original_i&1),"LUT6_2 O6 INIT mismatch");
                need(lower_bits.at(i&31)==bool(init>>(i&31)&1),"LUT6_2 O5 INIT mismatch");checked+=2;
            }
        }
    }
    return checked;
}
int main() {
  try {
    Harness h;h.net("$PACKER_VCC_NET");
    std::vector<std::vector<int>> shapes;layouts(shapes);
    for(const auto&a:shapes) for(const auto&b:shapes) {
        CellInfo l6=h.make_cell("upper",a),l5=h.make_cell("lower",b);
        need(h.auto_check(&l6,&l5),"legal union rejected by automatic check");
        h.fixup(&l6,&l5);
        need(get_net_or_empty(&l5,id_O6)==nullptr&&get_net_or_empty(&l5,id_O5),"O6 to O5 rename failed");
        need(get_net_or_empty(&l6,id_A6)==h.net("$PACKER_VCC_NET"),"paired O6 A6 must be high");
        // 五个逻辑地址位和一个上下半区标记可区分全部 64 个 INIT 来源。
        for(int k=0;k<6;k++) compare(h,l6,l5,a,b,basis(k),k==5?0:basis(k));
    }
    std::mt19937 rng(0x159a40);
    for(int n=0;n<4096;n++) {
        std::vector<int>a(1+rng()%5),b(1+rng()%5);for(int&i:a)i=rng()%5;for(int&i:b)i=rng()%5;
        CellInfo l6=h.make_cell("upper",a),l5=h.make_cell("lower",b);
        need(h.auto_check(&l6,&l5),"legal repeated union rejected by automatic check");
        h.fixup(&l6,&l5);
        for(int k=0;k<6;k++) compare(h,l6,l5,a,b,basis(k),k==5?0:basis(k));
        std::array<int,5> permutation={0,1,2,3,4};std::shuffle(permutation.begin(),permutation.end(),rng);
        auto remap=[&](CellInfo&c) {
            auto ports=c.ports;auto attrs=c.attrs;
            for(int k=0;k<5;k++) {
                auto dst=h.id("A"+std::to_string(k+1)),src=h.id("A"+std::to_string(permutation[k]+1));
                c.ports.erase(dst);c.attrs.erase(h.id("X_ORIG_PORT_"+dst.s));
                if(ports.count(src)) {c.ports[dst]=ports.at(src);c.ports[dst].name=dst;}
                if(attrs.count(h.id("X_ORIG_PORT_"+src.s))) c.attrs[h.id("X_ORIG_PORT_"+dst.s)]=attrs.at(h.id("X_ORIG_PORT_"+src.s));
            }
        };
        remap(l6);remap(l5);compare(h,l6,l5,a,b,rng(),rng());permutations++;
    }
    auto u6=h.make_cell("bad_upper",{0,1,2});auto u5=h.make_cell("bad_lower",{3,4,5});
    need(!h.auto_check(&u6,&u5),"six distinct inputs accepted by automatic check");
    auto r6=h.make_cell("repeat_upper",{0,0,0,1,2});auto r5=h.make_cell("repeat_lower",{0,0,3,4,5});
    need(!h.auto_check(&r6,&r5),"six distinct inputs with duplicates accepted by automatic check");
    auto true6=h.make_cell("six_port_upper",{0,0,1,2,3,4});auto true5=h.make_cell("six_port_lower",{0});
    need(!h.auto_check(&true6,&true5),"six input ports sharing five distinct signals must not be fractured");
    auto special6=h.make_cell("special_upper",{0,1,2}),special5=h.make_cell("special_lower",{2,3,4});
    special6.lutInfo.is_memory=true;need(!h.auto_check(&special6,&special5),"RAM mixed with automatic logic");
    special6.lutInfo.is_memory=false;special5.lutInfo.is_srl=true;need(!h.auto_check(&special6,&special5),"SRL mixed with automatic logic");
    special5.lutInfo.is_srl=false;special6.lutInfo.only_drives_carry=true;special5.lutInfo.only_drives_carry=true;
    need(h.auto_check(&special6,&special5),"valid carry inputs rejected");
    h.fixup(&special6,&special5);need(h.auto_check(&special6,&special5),"upper half select counted as an extra input");
    special6.lutInfo.output_count=2;need(!h.auto_check(&special6,&special5),"dual-output LUT accepted in shared pair");
    special6.lutInfo.output_count=1;
    special6.attrs[h.id("X_ORIG_PORT_A6")]=std::string("I5");
    need(!h.auto_check(&special6,&special5),"logical sixth input treated as a partition select");
    special6.attrs.erase(h.id("X_ORIG_PORT_A6"));
    special5.ports[id_A6]={id_A6,PORT_IN,h.net("$PACKER_VCC_NET")};
    need(h.auto_check(&special6,&special5),"unmapped routed A6 constant rejected");
    special5.ports[id_A6].net=h.net("N0");need(!h.auto_check(&special6,&special5),"variable sixth input on O5 accepted");
    int outmux_checks=check_outmux(h);
    int candidate_checks=check_candidates(h),muxf_checks=check_muxf(h),split_checks=check_lut6_2(h);
    std::cout<<"{\n  \"input_order_pairs\": "<<shapes.size()*shapes.size()<<",\n"
             <<"  \"init_configurations\": "<<cases<<",\n  \"output_comparisons\": "<<comparisons<<",\n"
             <<"  \"random_repeated_input_layouts\": 4096,\n  \"physical_permutations\": "<<permutations<<",\n"
             <<"  \"distinct_six_input_union_rejected\": true,\n"
             <<"  \"duplicate_six_input_union_rejected\": true,\n"
             <<"  \"six_logical_ports_rejected\": true,\n"
             <<"  \"ram_srl_logic_mixing_rejected\": true,\n"
             <<"  \"new_shared_input_check_passed\": true,\n  \"outmux_checks\": "<<outmux_checks<<",\n"
             <<"  \"candidate_checks\": "<<candidate_checks<<",\n  \"muxf_ff_checks\": "<<muxf_checks<<",\n"
             <<"  \"lut6_2_output_comparisons\": "<<split_checks<<",\n"
             <<"  \"valid_truth_tables_passed\": true\n}\n";
  } catch(const std::exception&e) { std::cerr<<e.what()<<"\n";return 1; }
}
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True,help='Directory containing nextpnr xilinx C++ sources')
    parser.add_argument('--out',type=Path,default=Path(__file__).parent/'truth_tables')
    args=parser.parse_args()
    place=(args.source/'arch_place.cc').read_text()
    fasm=(args.source/'fasm.cc').read_text()
    pack=(args.source/'pack.cc').read_text()
    get_inputs=braced(fasm,fasm.index('std::vector<IdString> get_inputs'))
    get_init=braced(fasm,fasm.index('std::vector<bool> get_lut_init'))
    fix_start=place.index('            std::unordered_map<IdString, std::vector<int>> lut5Inputs, lut6Inputs;')
    fix_end=place.index('\n        }\n    }\n    for (auto cell : sorted(cells))',fix_start)
    fix=place[fix_start:fix_end]
    # The single-site test supplies the same two cell pointers as the enclosing tile loop.
    fix=fix.replace('            CellInfo *lut6 = lt.cells[z << 4 | BEL_6LUT];\n','')
    fix=fix.replace('CellInfo *l6 = lt.cells[z << 4 | BEL_6LUT];','CellInfo *l6 = lut6;')
    prefix=PREFIX
    if 'static bool cofactor_lut_pair_valid' in place:
        cofactor=braced(place,place.index('static bool cofactor_lut_pair_valid'))
        prefix=prefix.replace('struct Harness {',cofactor+'\nstruct Harness {')
    src=prefix+get_inputs+'\n'+get_init+'\n'
    tile_start=place.index('bool Arch::xc7_logic_tile_valid(')
    automatic=braced(place,place.index('for (int i = 0; i < 8; i++)',tile_start))
    if 'X_LUT_LOGICAL_OUTPUT' not in automatic:raise SystemExit('The shared-input validation patch is required.')
    src+='bool auto_check(CellInfo *l6,CellInfo *l5) { bool logical_pair_checked[8]={}; LogicTileStatus lts;lts.cells[0]=l6;lts.cells[1]=l5;'+automatic+' return true; }\n'
    outmux=braced(place,place.index('for (int h = 0; h < 2; h++)',tile_start))
    src+='bool outmux_check(LogicTileStatus &lts) {'+outmux+' return true; }\n'
    gate_start=place.index('        int in_used = 0;',place.index('bool Arch::isValidBelForCell'))
    gate_end=place.index('\n    }\n    // NEXTPNR_EXCLUDE',gate_start)
    src+='bool candidate_check(CellInfo *cell) {'+place[gate_start:gate_end]+' return true; }\n'
    muxf=braced(pack,pack.index('void XilinxPacker::constrain_muxf_tree('))
    src+=muxf.replace('XilinxPacker::','')+'\n'
    split_start=pack.index('        // O5 is always a five-input function')
    split_end=pack.index('\n        packed_cells.insert(ci->name);',split_start)
    src+='std::vector<std::pair<int,int>> split_parameters(int mode) {\n'
    src+='CellInfo c;CellInfo *ci=&c;ci->name=id("split"); NetInfo *o5=net("o5"),*o6=net("o6");\n'
    src+='NetInfo *i5=mode<0?nullptr:net(mode==0?"$PACKER_GND_NET":mode==1?"$PACKER_VCC_NET":"signal_i5");\n'
    src+='std::vector<std::pair<IdString,IdString>> pairs;std::vector<std::pair<int,int>> halves;\n'
    src+='auto make_half=[&](const char*,NetInfo*,int inputs,int low){halves.emplace_back(inputs,low);};\n'
    src+=pack[split_start:split_end]+'\nif(pairs.size()!=size_t(mode==2?0:1))throw std::runtime_error("LUT6_2 pair eligibility mismatch");return halves;}\n'
    src+='void fixup(CellInfo *lut6,CellInfo *lut5) { for(int once=0;once<1;once++) {\n'+fix+'\n} }\n'
    src+=SUFFIX
    args.out.mkdir(parents=True,exist_ok=True)
    cpp=args.out/'actual_init_test.cc';cpp.write_text(src)
    exe=args.out/'actual_init_test'
    subprocess.run(['g++','-std=c++17','-O2',str(cpp),'-o',str(exe)],check=True)
    result=subprocess.run([str(exe)],check=True,text=True,capture_output=True)
    summary=json.loads(result.stdout)
    summary['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.source.glob('*.cc')}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
