#!/usr/bin/env python3
"""验证标量偏置字地址比较以及完整偏置缓冲区的公开结果与存储状态。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ((1, 1, 1), (2, 1, 2), (3, 6, 4), (3, 1, 2), (5, 3, 4),
            (9, 8, 2), (10, 6, 4), (17, 16, 2), (9, 9, 3), (3, 2, 8))
FULL_PROFILES = (
    (16, 32, 64, 28, 32, 1, 1),
    (8, 32, 32, 12, 1, 0, 0),
    (4, 32, 64, 12, 4, 0, 1),
    (8, 16, 32, 16, 8, 1, 0),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="f7f90963")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--full-only", action="store_true")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolve([root / "rtl/npu/loaders/bias_scalar_word_match.sv"], root)
    hashes = {str(path): digest(path) for path in sources}
    report = dict(passed=True, input_constraints=[], source_sha256=hashes, profiles=[], complete_modules=[])

    def execute(command, log, timeout=300):
        with log.open("w") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           timeout=timeout, check=True)
        return log.read_text()

    model = out / "proof.sv"
    model.write_text("""// 比较完整模加、字地址转换与实际比较模块。
module proof #(parameter W=9,A=8,N=2)(
 input wire [W-1:0] base,index,
 input wire [A-1:0] address,
 output wire equivalent
);
wire [W-1:0] scalar_sum=base+index;
wire [A-1:0] word_address=A'(scalar_sum/N);
wire actual;
bias_scalar_word_match #(.p_sum_width(W),.p_address_width(A),.p_words_per_read(N)) u_current(
 .i_base(base),.i_index(index),.i_word_address(address),.o_equal(actual));
assign equivalent=actual==(word_address==address);
endmodule
""")
    bench = out / "four_state.sv"
    bench.write_text("""// 检查字地址比较的任意已知值和逐位四态传播。
module tb;
parameter W=9,A=8,N=2;
localparam BITS=2*W+A;
reg [BITS-1:0] values,known;
wire [W-1:0] base,index;
wire [A-1:0] address;
assign {base,index,address}=values;
wire [W-1:0] scalar_sum=base+index;
wire [A-1:0] word_address=A'(scalar_sum/N);
wire expected=word_address==address;
wire actual;
bias_scalar_word_match #(.p_sum_width(W),.p_address_width(A),.p_words_per_read(N)) u_current(
 .i_base(base),.i_index(index),.i_word_address(address),.o_equal(actual));
integer seed=32'h475f2031,checks=0,choice;
task check;
 begin #1;checks++;
  if(actual!==expected)$fatal(1,"Scalar word differs: W=%0d A=%0d N=%0d values=%h",W,A,N,values);
 end
endtask
initial begin
 for(integer sample=0;sample<20000;sample++)begin
  for(integer bit_index=0;bit_index<BITS;bit_index++)begin
   choice=sample<5000 ? int'($unsigned($random(seed))%2) : int'($unsigned($random(seed))%4);
   case(choice)0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;endcase
  end
  check();
 end
 for(integer sample=0;sample<128;sample++)begin
  for(integer bit_index=0;bit_index<BITS;bit_index++)known[bit_index]=$random(seed);
  for(integer bit_index=0;bit_index<BITS;bit_index++)begin
   values=known;values[bit_index]=1'bx;check();values=known;values[bit_index]=1'bz;check();
  end
 end
 values='x;check();values='z;check();
 $display("SCALAR_WORD_MATCH_PASS checks=%0d",checks);$finish;
end
endmodule
""")
    for width, address_width, words in (() if args.full_only else PROFILES):
        for synthesis in (False, True):
            name = f"w{width}_a{address_width}_n{words}_s{int(synthesis)}"
            definitions = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if synthesis else []
            parameters = [f"-GW={width}", f"-GA={address_width}", f"-GN={words}"]
            script, log = out / (name+".ys"), out / (name+"_formal.log")
            script.write_text("read_slang --top proof "+shlex.join((definitions if synthesis else ["-USYNTHESIS", "-UXILINX_FPGA"])+parameters+list(map(str, [*sources, model])))+
                "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nprep -top proof -flatten\nopt -full\nsat -verify -prove equivalent 1\n")
            execute([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)], log)
            binary, four_log = out / (name+".vvp"), out / (name+"_four_state.log")
            execute(["iverilog", "-g2012", "-s", "tb", f"-Ptb.W={width}", f"-Ptb.A={address_width}", f"-Ptb.N={words}",
                     *definitions, "-o", str(binary), *map(str, sources), str(bench)], out / (name+"_build.log"))
            text = execute(["vvp", str(binary)], four_log)
            match = re.search(r"SCALAR_WORD_MATCH_PASS checks=(\d+)", text)
            assert match
            binary.unlink()
            row = dict(sum_width=width, address_width=address_width, words_per_read=words, synthesis=synthesis,
                       passed=True, four_state_comparisons=int(match[1]), formal_log_sha256=digest(log),
                       four_state_log_sha256=digest(four_log))
            report["profiles"].append(row)
            print(name, "PASS", match[1], flush=True)
    if args.full or args.full_only:
        current = root / "rtl/npu/loaders/bias_loader_buffer.sv"
        reference = out / "reference.sv"
        reference.write_bytes(subprocess.check_output(["git", "show", args.reference+":rtl/npu/loaders/bias_loader_buffer.sv"], cwd=ROOT))
        report["parent_source_sha256"] = digest(current)
        for mode in ("generic", "fpga"):
            definitions = ["-USYNTHESIS", "-UXILINX_FPGA"] if mode == "generic" else ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"]
            for size, data, bus, count, groups, share, registered in FULL_PROFILES:
                name = f"full_s{size}_d{data}_b{bus}_g{groups}_{mode}"
                commands = []
                parameters = dict(SIZE=size, DATA_WIDTH=data, DMA_DATA_WIDTH=8, BUS_WIDTH=bus,
                                  REG_WIDTH=32, COUNT_WIDTH=count, GROUP_BLOCKS_MAX=groups,
                                  p_share_load_index=share, p_register_current_range=registered)
                for label, source in (("reference", reference), ("current", current)):
                    files = resolve([source], root)
                    commands += ["read_slang --top bias_loader_buffer "+shlex.join(
                        [*definitions, *[f"-G{k}={v}" for k, v in parameters.items()], *map(str, files)]),
                        "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                        "prep -top bias_loader_buffer -flatten", "memory_map", "async2sync", "opt_clean",
                        f"rename bias_loader_buffer {label}", f"design -stash {label}"]
                commands += ["design -copy-from reference -as reference reference", "design -copy-from current -as current current",
                    "equiv_make reference current equivalent", "hierarchy -top equivalent", "equiv_simple -seq 1",
                    "opt_clean", "equiv_induct -seq 2", "equiv_status -assert"]
                script, log = out / (name+".ys"), out / (name+"_formal.log")
                script.write_text("\n".join(commands)+"\n")
                text = execute([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)], log, timeout=480)
                match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
                assert match and int(match[2]) == 0
                report["complete_modules"].append(dict(parameters=parameters, compilation_mode=mode, compilation_definitions=definitions, passed=True, equivalent_bits=int(match[1]), formal_log_sha256=digest(log)))
                print(name, "COMPLETE_MODULE_PASS", match[1], flush=True)
        assert report["parent_source_sha256"] == digest(current)
    assert hashes == {str(path): digest(path) for path in sources}
    report["test_sha256"] = digest(Path(__file__))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
