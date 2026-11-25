#!/usr/bin/env python3
"""从两版实际 RTL 提取步长计算与寄存结构，证明宽度和四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/loaders/ia_loader_ctrl.sv")
HELPER = Path("rtl/npu/loaders/ia_row_step_register.sv")


def extract(content, name):
    start = content.index("  assign tile_row_step_b_comb =")
    registers = content.index("  always_ff @(posedge clk or negedge rst_n) begin", start)
    end = content.index("  // =====================================================================", registers)
    capture = content[registers:end]
    condition = "state == S_IDLE && init_start"
    if capture.count(condition) != 1:
        raise RuntimeError("步长寄存器接收条件未匹配")
    capture = capture.replace(condition, "enable")
    return f"""module row_step_{name} #(
 parameter integer REG_WIDTH=32,SIZE=16
)(input logic clk,rst_n,enable,
 input logic cfg_tile_packed,cfg_use_16bits,
 input logic [REG_WIDTH-1:0] cfg_ia_reuse_num,cfg_lhs_row_stride_b,packed_k_tiles,
 output logic [REG_WIDTH-1:0] tile_row_step_b,l2_group_row_step_b);
 localparam integer LOG2_SIZE=$clog2(SIZE);
 logic [REG_WIDTH-1:0] tile_row_step_b_comb,l2_group_row_step_b_comb;
""" + content[start:registers] + capture + "endmodule\n"


def from_helper(content, name):
    helper_name = "row_step_" + name + "_register"
    helper = re.sub(r"\bia_row_step_register\b", helper_name, content)
    return f"""module row_step_{name} #(
 parameter integer REG_WIDTH=32,SIZE=16
)(input logic clk,rst_n,enable,
 input logic cfg_tile_packed,cfg_use_16bits,
 input logic [REG_WIDTH-1:0] cfg_ia_reuse_num,cfg_lhs_row_stride_b,packed_k_tiles,
 output wire [REG_WIDTH-1:0] tile_row_step_b,l2_group_row_step_b);
 {helper_name} #(.p_width(REG_WIDTH),.p_size(SIZE)) u_step (
   .clk(clk),.rst_n(rst_n),.i_enable(enable),
   .i_tile_packed(cfg_tile_packed),.i_use_16bits(cfg_use_16bits),
   .i_reuse_num(cfg_ia_reuse_num),.i_row_stride(cfg_lhs_row_stride_b),
   .i_packed_tiles(packed_k_tiles),.o_tile_step(tile_row_step_b),
   .o_group_step(l2_group_row_step_b)
 );
endmodule
""" + helper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="3ff66f2b")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = ROOT, args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    helper = (ROOT / HELPER).read_text() if (ROOT / HELPER).is_file() else None
    cases = {}
    for name, content in (("reference", reference), ("current", current)):
        path = out / f"{name}.sv"
        if "  assign tile_row_step_b_comb =" in content:
            path.write_text(extract(content, name))
        else:
            selected = helper if name == "current" else subprocess.check_output(
                ["git", "show", f"{revision}:{HELPER}"], cwd=ROOT, text=True)
            path.write_text(from_helper(selected, name))
        cases[name] = dict(top=f"row_step_{name}", sources=[str(path)],
                          options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1", "-GREG_WIDTH=32", "-GSIZE=16"],
                          parameters=dict(REG_WIDTH=32, SIZE=16),
                          configuration="Actual row-step expressions with identical capture and reset")
    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (out / "source_sha256.json").write_text(json.dumps(dict(reference_commit=revision,
        source=str(SOURCE), reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        current_sha256=hashlib.sha256(current.encode()).hexdigest(),
        helper_sha256=hashlib.sha256(helper.encode()).hexdigest() if helper else None), indent=2) + "\n")
    records=[]
    for width,size in [(2,2),(3,2),(4,2),(5,2),(6,4),(7,8),(8,16),(16,16),(32,16),(64,16)]:
        folder=out/f'w{width}_s{size}';folder.mkdir(parents=True,exist_ok=True)
        commands=[]
        for label in ['reference','current']:
            commands += [f'read_slang --top row_step_{label} -GREG_WIDTH={width} -GSIZE={size} {out}/{label}.sv',
                         'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                         f'prep -top row_step_{label} -flatten','async2sync','opt_clean',
                         f'rename row_step_{label} {label}',f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1','opt_clean','equiv_induct -seq 2','equiv_status -assert']
        ys=folder/'proof.ys';ys.write_text('\n'.join(commands)+'\n')
        with (folder/'proof.log').open('w') as log:
            subprocess.run([sys.executable,str(root/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=240)
        content=(folder/'proof.log').read_text();count=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',content);assert count and int(count[2])==0
        bench=f'''module tb;
    localparam integer REG_WIDTH={width},SIZE={size};
    logic clk=0,rst_n=0,enable=0,cfg_tile_packed=0,cfg_use_16bits=0;
    logic [REG_WIDTH-1:0] cfg_ia_reuse_num=0,cfg_lhs_row_stride_b=0,packed_k_tiles=0;
    wire [REG_WIDTH-1:0] tile_row_step_b,l2_group_row_step_b,reference_tile,reference_group;
    row_step_current #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) dut(.*);
    row_step_reference #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) reference_dut(.tile_row_step_b(reference_tile),.l2_group_row_step_b(reference_group),.*);
    integer cycles=0;
    task tick;
     #1;clk=1;#1;
     if (tile_row_step_b !== reference_tile || l2_group_row_step_b !== reference_group)
      $fatal(1,"Row step mismatch w=%0d cycle=%0d",REG_WIDTH,cycles);
     cycles++;clk=0;#1;
    endtask
    initial begin
     repeat(4)tick();
     for(integer sample=0;sample<10000;sample++)begin
      rst_n=sample%31!=0;enable=$urandom;cfg_tile_packed=$urandom;cfg_use_16bits=$urandom;
      cfg_lhs_row_stride_b=REG_WIDTH'({{$urandom,$urandom}});packed_k_tiles=REG_WIDTH'({{$urandom,$urandom}});
      case(sample%12)
       0:cfg_ia_reuse_num=0;1:cfg_ia_reuse_num=1;2:cfg_ia_reuse_num=2;
       3:cfg_ia_reuse_num=4;4:cfg_ia_reuse_num=8;5:cfg_ia_reuse_num=16;
       6:cfg_ia_reuse_num=25;7:cfg_ia_reuse_num=32;8:cfg_ia_reuse_num=64;
       9:cfg_ia_reuse_num=128;10:cfg_ia_reuse_num='1;default:cfg_ia_reuse_num=REG_WIDTH'({{$urandom,$urandom}});
      endcase
      if(sample>=2000)begin
       case(sample%19)
        0:cfg_lhs_row_stride_b[sample%REG_WIDTH]=1'bx;
        1:cfg_lhs_row_stride_b[sample%REG_WIDTH]=1'bz;
        2:packed_k_tiles[sample%REG_WIDTH]=1'bx;
        3:packed_k_tiles[sample%REG_WIDTH]=1'bz;
        4:cfg_ia_reuse_num[sample%REG_WIDTH]=1'bx;
        5:cfg_ia_reuse_num[sample%REG_WIDTH]=1'bz;
        6:cfg_tile_packed=1'bx;7:cfg_tile_packed=1'bz;
        8:cfg_use_16bits=1'bx;9:cfg_use_16bits=1'bz;
        10:enable=1'bx;11:enable=1'bz;
        12:rst_n=1'bx;13:rst_n=1'bz;default:;
       endcase
      end
      tick();
     end
     $display("ROW_STEP_PASS cycles=%0d",cycles);$finish;
    end
    endmodule
    '''
        tb=folder/'tb.sv';tb.write_text(bench)
        with (folder/'compile.log').open('w') as log:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(folder/'sim.vvp'),str(out/'reference.sv'),str(out/'current.sv'),str(tb)],stdout=log,stderr=subprocess.STDOUT,check=True)
        run=subprocess.run(['vvp',str(folder/'sim.vvp')],text=True,capture_output=True,check=True,timeout=60)
        (folder/'run.log').write_text(run.stdout+run.stderr);assert 'ROW_STEP_PASS cycles=10004' in run.stdout
        record={'REG_WIDTH':width,'SIZE':size,'formal_bits':int(count[1]),'four_state_cycles':10004,'passed':True};records.append(record);print(json.dumps(record),flush=True)
    (out/'summary.json').write_text(json.dumps({'passed':True,'profiles':records,'sources_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [out/'reference.sv',out/'current.sv']}},indent=2)+'\n')
    if (ROOT / SOURCE).read_text() != current:
        raise RuntimeError("验证期间 RTL 源文件发生变化")
    if helper and (ROOT / HELPER).read_text() != helper:
        raise RuntimeError("验证期间步长模块源文件发生变化")


if __name__ == "__main__":
    main()
