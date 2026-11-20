#!/usr/bin/env python3
"""独立检查 CARRY4 尾部裁剪的连接操作及 Xilinx Unisim 原语行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def braced(source, start):
    begin = source.index('{', start)
    end = begin + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


CPP_PREFIX = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>
using IdString=std::string;
struct CellInfo;
struct PortRef { CellInfo *cell=nullptr; IdString port; };
struct NetInfo { IdString name; std::vector<PortRef> users; PortRef driver; };
struct PortInfo { NetInfo *net=nullptr; };
struct CellInfo {
    IdString name,type;
    std::map<IdString,PortInfo> ports;
    std::map<IdString,int> attrs;
};
struct Context {
    std::map<IdString,CellInfo*> cells;
    IdString id(const std::string &s) const { return s; }
};
template<class T> const T &sorted(const T &x) { return x; }
NetInfo *get_net_or_empty(CellInfo *cell,IdString port) {
    auto i=cell->ports.find(port); return i==cell->ports.end()?nullptr:i->second.net;
}
void log_info(const char *,...) {}
'''
CPP_TESTS = r'''
struct Design {
    Context ctx;
    std::vector<std::unique_ptr<CellInfo>> cells;
    std::vector<std::unique_ptr<NetInfo>> nets;
    CellInfo *cell(std::string name,std::string type="CARRY4") {
        auto c=std::make_unique<CellInfo>(); c->name=name;c->type=type;
        auto p=c.get();cells.push_back(std::move(c));ctx.cells[name]=p;return p;
    }
    NetInfo *net(std::string name) {
        auto n=std::make_unique<NetInfo>();n->name=name;
        auto p=n.get();nets.push_back(std::move(n));return p;
    }
    void use(NetInfo *n,CellInfo *c,std::string port) {
        c->ports[port].net=n;n->users.push_back({c,port});
    }
    NetInfo *drive(CellInfo *c,std::string port) {
        auto n=net(c->name+"."+port);c->ports[port].net=n;n->driver={c,port};return n;
    }
};
std::string port(const char *prefix,int bit) { return std::string(prefix)+"["+std::to_string(bit)+"]"; }
int highest(int mask) {
    unsigned observed=(mask & 15)|((mask>>4)&15);
    int result=-1;while(observed) { ++result;observed>>=1; }return result;
}
void inputs(Design &d,CellInfo *c,int present=255) {
    for(int i=0;i<8;i++) if(present&(1<<i)) {
        auto p=port(i<4?"S":"DI",i%4);d.use(d.net(c->name+p),c,p);
    }
    d.use(d.net(c->name+"ci"),c,"CI");d.use(d.net(c->name+"init"),c,"CYINIT");
}
void outputs(Design &d,CellInfo *c,int mask,bool empty_ports=true) {
    auto out=d.cell(c->name+"_sink","OBUF");
    for(int i=0;i<8;i++) if(empty_ports || (mask&(1<<i))) {
        auto p=port(i<4?"O":"CO",i%4);auto n=d.drive(c,p);
        if(mask&(1<<i)) d.use(n,out,"I"+std::to_string(i));
    }
}
void check(CellInfo *c,int mask,int present=255,bool unchanged=false) {
    int h=highest(mask);
    for(int i=0;i<8;i++) {
        bool expected=(present&(1<<i)) && (unchanged || i%4<=h);
        assert(bool(get_net_or_empty(c,port(i<4?"S":"DI",i%4)))==expected);
    }
    assert(get_net_or_empty(c,"CI"));assert(get_net_or_empty(c,"CYINIT"));
}
int main() {
    setenv("XC7_CARRY_TRIM_TAIL","1",1);
    int shape_checks=0,skip_checks=0,bridge_checks=0,shared_checks=0;
    for(int mask=0;mask<256;mask++) for(int present=0;present<256;present++) {
        Design d;auto c=d.cell("carry");inputs(d,c,present);outputs(d,c,mask,mask%2);
        run_trim(&d.ctx);check(c,mask,present);shape_checks++;
    }
    for(int mask=0;mask<256;mask++) for(int kind=0;kind<2;kind++) {
        Design d;auto c=d.cell("carry",kind?"LUT1":"CARRY4");
        if(!kind)c->attrs["BEL"]=1;
        inputs(d,c);outputs(d,c,mask);run_trim(&d.ctx);check(c,mask,255,true);skip_checks++;
    }
    for(int output=0;output<8;output++) for(int init=0;init<2;init++) for(int mask=0;mask<256;mask++) {
        Design d;auto a=d.cell("a"),b=d.cell("b");inputs(d,a);inputs(d,b);
        outputs(d,a,mask);outputs(d,b,1);
        auto output_port=port(output<4?"O":"CO",output%4);
        auto n=get_net_or_empty(a,output_port);
        std::string input_port=init?"CYINIT":"CI";
        disconnect_port(&d.ctx,b,input_port);d.use(n,b,input_port);
        auto original_users=n->users.size();run_trim(&d.ctx);
        check(a,mask|(1<<output));check(b,1);
        assert(get_net_or_empty(b,input_port)==n);assert(n->users.size()==original_users);
        bridge_checks++;
    }
    for(int h=0;h<3;h++) for(int shared_di=0;shared_di<2;shared_di++) {
        Design d;auto c=d.cell("carry"),external=d.cell("external","LUT2"),driver=d.cell("driver","LUT1");
        inputs(d,c);outputs(d,c,1<<h);
        auto n=d.drive(driver,"O");
        disconnect_port(&d.ctx,c,"S[0]");d.use(n,c,"S[0]");
        auto tail=port(shared_di?"DI":"S",3);
        disconnect_port(&d.ctx,c,tail);d.use(n,c,tail);d.use(n,external,"I0");
        run_trim(&d.ctx);check(c,1<<h);
        assert(n->driver.cell==driver && n->driver.port=="O");
        assert(n->users.size()==2);assert(get_net_or_empty(c,"S[0]")==n);
        assert(get_net_or_empty(external,"I0")==n);shared_checks++;
    }
    unsetenv("XC7_CARRY_TRIM_TAIL");
    { Design d;auto c=d.cell("carry");inputs(d,c);outputs(d,c,1);run_trim(&d.ctx);check(c,1,255,true);skip_checks++; }
    std::cout << "{\"connection_shapes\":" << shape_checks << ",\"skip_cases\":" << skip_checks
              << ",\"carry_bridges\":" << bridge_checks << ",\"shared_signals\":" << shared_checks
              << ",\"passed\":true}\n";
}
'''
SV = r'''
module carry_tail_boundary(
 input wire [3:0] s, di, alternate_s, alternate_di,
 input wire ci, cyinit,
 input wire [3:0] observed_o, observed_co,
 output wire equal_outputs
);
 wire [3:0] o0,co0,o1,co1,keep;
 wire [3:0] used=observed_o|observed_co;
 for(genvar bit_index=0;bit_index<4;bit_index=bit_index+1) begin
  assign keep[bit_index]=|used[3:bit_index];
 end
 wire [3:0] s_new=(s&keep)|(alternate_s&~keep);
 wire [3:0] di_new=(di&keep)|(alternate_di&~keep);
 CARRY4 a(.S(s),.DI(di),.CI(ci),.CYINIT(cyinit),.O(o0),.CO(co0));
 CARRY4 b(.S(s_new),.DI(di_new),.CI(ci),.CYINIT(cyinit),.O(o1),.CO(co1));
 assign equal_outputs=(((o0^o1)&observed_o)==0)&&(((co0^co1)&observed_co)==0);
endmodule

module carry_tail_bridge(
 input wire [3:0] s0, di0, s1, di1, alternate_s0, alternate_di0, alternate_s1, alternate_di1,
 input wire ci0, cyinit0, other_input,
 input wire [3:0] observed_o0, observed_co0, observed_o1, observed_co1,
 input wire [1:0] bridge_bit,
 input wire bridge_from_co, bridge_to_cyinit,
 output wire equal_outputs
);
 wire [3:0] o0,co0,o1,co1,n_o0,n_co0,n_o1,n_co1,keep0,keep1;
 wire [3:0] bridge_mask=4'b0001<<bridge_bit;
 wire [3:0] used0=observed_o0|observed_co0|bridge_mask;
 wire [3:0] used1=observed_o1|observed_co1;
 for(genvar bit_index=0;bit_index<4;bit_index=bit_index+1) begin
  assign keep0[bit_index]=|used0[3:bit_index];
  assign keep1[bit_index]=|used1[3:bit_index];
 end
 wire bridge_ref=bridge_from_co ? co0[bridge_bit]:o0[bridge_bit];
 wire bridge_new=bridge_from_co ? n_co0[bridge_bit]:n_o0[bridge_bit];
 wire ref_ci=bridge_to_cyinit ? other_input:bridge_ref;
 wire ref_init=bridge_to_cyinit ? bridge_ref:other_input;
 wire new_ci=bridge_to_cyinit ? other_input:bridge_new;
 wire new_init=bridge_to_cyinit ? bridge_new:other_input;
 CARRY4 a0(.S(s0),.DI(di0),.CI(ci0),.CYINIT(cyinit0),.O(o0),.CO(co0));
 CARRY4 a1(.S(s1),.DI(di1),.CI(ref_ci),.CYINIT(ref_init),.O(o1),.CO(co1));
 CARRY4 b0(.S((s0&keep0)|(alternate_s0&~keep0)),.DI((di0&keep0)|(alternate_di0&~keep0)),
           .CI(ci0),.CYINIT(cyinit0),.O(n_o0),.CO(n_co0));
 CARRY4 b1(.S((s1&keep1)|(alternate_s1&~keep1)),.DI((di1&keep1)|(alternate_di1&~keep1)),
           .CI(new_ci),.CYINIT(new_init),.O(n_o1),.CO(n_co1));
 assign equal_outputs=(((o0^n_o0)&observed_o0)==0)&&(((co0^n_co0)&observed_co0)==0)&&
                      (((o1^n_o1)&observed_o1)==0)&&(((co1^n_co1)&observed_co1)==0);
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr',type=Path,required=True)
    parser.add_argument('--vendor-model',type=Path,required=True)
    parser.add_argument('--worker',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    folder=args.out.resolve();folder.mkdir(parents=True,exist_ok=True)
    source_path=args.nextpnr/'xilinx/pack_carry_xc7.cc'
    utility_path=args.nextpnr/'common/design_utils.cc'
    source=source_path.read_text();utility=utility_path.read_text()
    begin=source.index('    const char *trim_tail =')
    end=source.index('    static const std::unordered_set',begin)
    operation=source[begin:end]
    disconnect=braced(utility,utility.index('void disconnect_port('))
    cpp=folder/'actual_tail_check.cc'
    cpp.write_text(CPP_PREFIX+disconnect+'\nvoid run_trim(Context *ctx) {\n'+operation+'}\n'+CPP_TESTS)
    binary=folder/'actual_tail_check'
    subprocess.run(['g++','-std=c++17','-O2','-Wall','-Wextra',str(cpp),'-o',str(binary)],check=True)
    execution=subprocess.check_output([str(binary)],text=True)
    result={'passed':True,'nextpnr_source_sha256':digest(source_path),
            'disconnect_source_sha256':digest(utility_path),'extracted_cpp_sha256':digest(cpp),
            'algorithm_cases':json.loads(execution),'vendor_model_sha256':digest(args.vendor_model),'formal_cases':[]}
    model=folder/'CARRY4.v';model.write_bytes(args.vendor_model.read_bytes())
    design=folder/'tail_boundary_miter.sv';design.write_text(SV)
    for top,defined in [
        ('carry_tail_boundary',['s','di','ci','cyinit','observed_o','observed_co']),
        ('carry_tail_bridge',['s0','di0','s1','di1','ci0','cyinit0','other_input',
            'observed_o0','observed_co0','observed_o1','observed_co1','bridge_bit','bridge_from_co','bridge_to_cyinit'])]:
        script=folder/(top+'.ys')
        script.write_text(f'read_verilog -formal -sv -D XIL_XECLIB {model}\n'+
            f'read_verilog -formal -sv {design}\n'+f'prep -top {top} -flatten\n'+
            'sat -verify -prove equal_outputs 1 -enable_undef '+
            ' '.join('-set-def '+port for port in defined)+'\n')
        log=folder/(top+'.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(args.worker),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        result['formal_cases'].append({'top':top,'passed':True,'alternative_tail_values_may_be_undefined':True})
    (folder/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
