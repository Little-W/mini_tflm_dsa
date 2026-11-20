#!/usr/bin/env python3
"""Run the actual placement move and rollback with local OUTMUX users."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from review_lut_packing import PREFIX, braced


CONTEXT = r'''
struct Context {
    LogicTileStatus tiles[2];
    CellInfo *bound[3]={};
    std::function<bool(BelId)> validity;
    std::vector<int> validity_calls;
    IdString id(const std::string &s) const { return IdString(s); }
    const char *nameOf(CellInfo *c) const { return c->name.s.c_str(); }
    CellInfo *getBoundBelCell(BelId b) { return bound[b]; }
    int getBelLocation(BelId b) { return b; }
    void bindBel(BelId b,CellInfo*c,int strength) {
        assert(b==1||b==2);assert(!bound[b]);bound[b]=c;
        c->bel=b;c->belStrength=strength;tiles[b-1].cells[BEL_FF]=c;
    }
    void unbindBel(BelId b) {
        assert(bound[b]);bound[b]->bel=0;bound[b]=nullptr;tiles[b-1].cells[BEL_FF]=nullptr;
    }
    bool isBelLocationValid(BelId b) { validity_calls.push_back(b);return validity(b); }
    unsigned rng() { return 0; }
};
'''

PLACER = r'''
int get_constraints_distance(Context *,CellInfo *) { return 0; }
struct MoveChange {
    double timing_delta=0;int wirelen_delta=0;
    void reset(void *) { timing_delta=0;wirelen_delta=0; }
};
struct Placer {
    Context *ctx;
    bool require_legal=true;
    struct { double netShareWeight=0,constraintWeight=0; } cfg;
    MoveChange moveChange;
    double lambda=0,last_timing_cost=1,last_wirelen_cost=1,temp=1,total_net_share=1;
    int n_move=0,n_accept=0,commits=0;
    std::map<CellInfo*,int> share_changes;
    bool is_constrained(CellInfo*c) { return c->constr_parent||!c->constr_children.empty(); }
    int update_nets_by_tile(CellInfo*c,int old_position,int new_position) {
        share_changes[c]+=new_position-old_position;return 0;
    }
    void add_move_cell(MoveChange&,CellInfo*,BelId) {}
    void compute_cost_changes(MoveChange&c) { c.wirelen_delta=-1; }
    void commit_cost_changes(MoveChange&) { commits++; }
'''

MAIN = r'''
};
static void need(bool value,const char*what) { if(!value)throw std::runtime_error(what); }
int main() {
 try {
    int count=0;
    for(int use_share=0;use_share<2;use_share++)for(int shape=0;shape<3;shape++) {
        Harness h;auto &ctx=*h.ctx;
        CellInfo lower=h.make_cell("source_lower",{0}),carry,moving,other,outside;
        carry.type=id_CARRY4;moving.name=h.id("moving");other.name=h.id("other");
        auto sum=h.net("source_carry_sum");sum->users={{&moving,id_D}};moving.ffInfo.d=sum;
        carry.carryInfo.out_sigs[0]=sum;
        ctx.tiles[0].cells[BEL_CARRY4]=&carry;
        if(shape<2) {
            lower.lutInfo.output_sigs[0]->users={{&outside,{}}};
            ctx.tiles[0].cells[BEL_5LUT]=&lower;
        }
        ctx.bindBel(1,&moving,STRENGTH_WEAK);
        if(shape==1)ctx.bindBel(2,&other,STRENGTH_WEAK);
        ctx.validity=[&](BelId b){return h.outmux_check(ctx.tiles[b-1]);};
        need(ctx.validity(1)&&ctx.validity(2),"initial locations must be valid");
        Placer placer;placer.ctx=&ctx;placer.cfg.netShareWeight=use_share;
        bool accepted=placer.try_swap_position(&moving,2);
        need(std::find(ctx.validity_calls.begin(),ctx.validity_calls.end(),1)!=ctx.validity_calls.end(),"source location was not checked");
        if(shape<2) {
            need(!accepted,"move created competing source OUTMUX users");
            need(ctx.bound[1]==&moving&&ctx.bound[2]==(shape==1?&other:nullptr),"rollback did not restore bindings");
            need(placer.commits==0&&placer.n_move==0,"invalid move committed cost changes");
            for(auto pair:placer.share_changes)need(pair.second==0,"rollback did not restore net sharing accounting");
        } else {
            need(accepted&&ctx.bound[1]==nullptr&&ctx.bound[2]==&moving,"legal move rejected");
            need(placer.commits==1&&placer.n_move==1,"legal move cost changes missing");
        }
        need(ctx.validity(1)&&ctx.validity(2),"final locations must be valid");count++;
    }
    std::cout<<"{\"move_cases\":"<<count<<",\"empty_destination_rollback\":true,\"exchange_rollback\":true,\"sharing_accounting_restored\":true,\"legal_move_accepted\":true,\"passed\":true}\n";
 } catch(const std::exception&e) {std::cerr<<e.what()<<"\n";return 1;}
}
'''


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--nextpnr',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    placer=(a.nextpnr/'common/placer1.cc').read_text()
    arch=(a.nextpnr/'xilinx/arch_place.cc').read_text()
    prefix=PREFIX.replace('struct Context;','#include <functional>\n#include <cmath>\nusing BelId=int;\nenum{STRENGTH_WEAK=1};\nstruct Context;')
    prefix=prefix.replace('    int belStrength=0;','    BelId bel=0;\n    int belStrength=0;')
    old_context=braced(prefix,prefix.index('struct Context {'))+';'
    prefix=prefix.replace(old_context,CONTEXT)
    outmux=braced(arch,arch.index('for (int h = 0; h < 2; h++)',arch.index('bool Arch::xc7_logic_tile_valid(')))
    move=braced(placer,placer.index('bool try_swap_position(CellInfo *cell, BelId newBel)'))
    src=prefix+'bool outmux_check(LogicTileStatus &lts){'+outmux+' return true;}\n};\n'+PLACER+move+MAIN
    cpp=a.out/'actual_placer_move.cc';cpp.write_text(src);exe=a.out/'actual_placer_move'
    subprocess.run(['g++','-std=c++17','-O2',str(cpp),'-o',str(exe)],check=True)
    result=subprocess.run([str(exe)],text=True,capture_output=True)
    (a.out/'run.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise SystemExit(result.stderr)
    summary=json.loads(result.stdout)
    summary['placer_source_sha256']=hashlib.sha256(placer.encode()).hexdigest()
    summary['arch_source_sha256']=hashlib.sha256(arch.encode()).hexdigest()
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
