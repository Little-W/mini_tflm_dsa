#!/usr/bin/env python3
"""Check local data ports, remote carry operands, and output sharing."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from review_lut_packing import PREFIX, braced


MAIN = r'''
};
int main() {
    Harness h;
    int checked=0,failed=0;
    auto test=[&](const char*name,bool value,bool expected) {
        checked++;
        if(value!=expected) {failed++;std::cerr<<name<<": observed="<<value<<" expected="<<expected<<"\n";}
    };
    CellInfo lower=h.make_cell("lower",{0}),upper=h.make_cell("upper",{1}),ff1,ff2,cy,remote,outside;
    cy.type=id_CARRY4;remote.type=id_CARRY4;
    NetInfo *o5=lower.lutInfo.output_sigs[0],*q5=h.net("q5"),*sum=h.net("sum");
    ff2.ports[id_Q]={id_Q,PORT_OUT,q5};q5->users={{&outside,{}}};
    LogicTileStatus lts;lts.cells[BEL_5LUT]=&lower;lts.cells[BEL_FF2]=&ff2;
    lower.lutInfo.only_drives_carry=true;
    o5->users={{&remote,h.id("DI0")}};
    test("remote_carry_and_5ff_q",h.outmux_check(lts),false);
    lts.cells[BEL_CARRY4]=&cy;o5->users={{&cy,h.id("DI2")}};
    test("other_position_di_and_5ff_q",h.outmux_check(lts),false);
    o5->users={{&cy,h.id("DI0")}};cy.ports[h.id("DI0")]={h.id("DI0"),PORT_IN,o5};
    test("same_position_di_and_5ff_q",h.outmux_check(lts),true);
    cy.attrs[h.id("X_CARRY_DI0_VIA_X")]=std::string("1");
    test("direct_x_di_and_5ff_q",h.outmux_check(lts),false);
    cy.attrs.erase(h.id("X_CARRY_DI0_VIA_X"));
    o5->users={{&cy,h.id("CYINIT")}};
    test("carry_init_and_5ff_q",h.outmux_check(lts),false);
    lower.lutInfo.only_drives_carry=false;lts.cells[BEL_CARRY4]=nullptr;lts.cells[BEL_FF]=&ff1;
    ff1.ffInfo.d=o5;o5->users={{&ff1,id_D}};
    test("ff_d_and_5ff_q",h.outmux_check(lts),true);
    o5->users.push_back({&ff1,h.id("CE")});test("ff_d_ce_same_net_and_5ff_q",h.outmux_check(lts),false);
    o5->users.pop_back();o5->users.push_back({&ff1,h.id("CK")});test("ff_d_clock_same_net_and_5ff_q",h.outmux_check(lts),false);
    o5->users={{&upper,id_A1}};lts.cells[BEL_6LUT]=&upper;
    test("lut_input_feedback_and_5ff_q",h.outmux_check(lts),false);
    lts.cells[BEL_FF2]=nullptr;lts.cells[BEL_CARRY4]=&cy;
    o5->users={{&outside,{}}};cy.carryInfo.out_sigs[0]=sum;sum->users={{&upper,id_A1}};
    test("carry_to_lut_feedback_and_o5",h.outmux_check(lts),false);
    sum->users={{&cy,h.id("DI0")}};test("carry_feedback_and_o5",h.outmux_check(lts),false);
    ff1.ffInfo.d=sum;sum->users={{&ff1,id_D}};
    test("local_carry_ff_d_and_o5",h.outmux_check(lts),true);
    sum->users.push_back({&ff1,h.id("CE")});test("carry_ff_d_ce_same_net_and_o5",h.outmux_check(lts),false);
    lts.cells[BEL_FF2]=&ff2;q5->users.clear();ff2.ffInfo.d=sum;sum->users={{&ff2,id_D}};
    test("carry_to_5ff_d_and_o5",h.outmux_check(lts),false);
    lts.cells[BEL_FF2]=nullptr;cy.carryInfo.out_sigs[0]=nullptr;
    auto co=h.net("co0");cy.carryInfo.cout_sigs[0]=co;co->users={{&remote,id_CIN}};
    test("co0_to_carry_cin_and_o5",h.outmux_check(lts),false);
    cy.carryInfo.cout_sigs[0]=nullptr;
    lts.cells[BEL_5LUT]=nullptr;lts.cells[(3<<4)|BEL_5LUT]=&lower;
    cy.carryInfo.cout_sigs[3]=co;
    test("co3_chain_and_o5",h.outmux_check(lts),true);
    co->users.push_back({&outside,{}});
    test("co3_chain_fabric_fanout_and_o5",h.outmux_check(lts),false);
    CellInfo second_carry;second_carry.type=id_CARRY4;
    co->users={{&remote,id_CIN},{&second_carry,id_CIN}};
    test("co3_multiple_carry_cin_users",h.outmux_check(lts),false);
    std::cout<<"{\"outmux_edge_cases\":"<<checked<<",\"failed_cases\":"<<failed<<",\"passed\":"<<(failed?"false":"true")<<"}\n";
    return failed?1:0;
}
'''


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    arch=(a.source/'arch_place.cc').read_text()
    outmux=braced(arch,arch.index('for (int h = 0; h < 2; h++)',arch.index('bool Arch::xc7_logic_tile_valid(')))
    src=PREFIX+'bool outmux_check(LogicTileStatus &lts){'+outmux+'return true;}\n'+MAIN
    cpp=a.out/'actual_outmux_edges.cc';cpp.write_text(src);exe=a.out/'actual_outmux_edges'
    subprocess.run(['g++','-std=c++17','-O2',str(cpp),'-o',str(exe)],check=True)
    result=subprocess.run([str(exe)],capture_output=True,text=True)
    summary=json.loads(result.stdout);summary['source_sha256']=hashlib.sha256(arch.encode()).hexdigest()
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (a.out/'run.log').write_text(result.stdout+result.stderr)
    print(json.dumps(summary,indent=2))
    if result.returncode:raise SystemExit(result.stderr)


if __name__=='__main__':main()
