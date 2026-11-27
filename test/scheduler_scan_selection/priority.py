#!/usr/bin/env python3
"""证明分组优先编码对全部输入和帧数量保持一致，并检查四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/control/ps_scheduler_priority.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="92f722e6")
    parser.add_argument("--profiles", nargs="+", default=["1:1", "2:1", "3:2", "4:2", "6:3", "7:3",
        "16:4", "17:5", "31:5", "64:6", "129:8", "16:1", "16:8"], help="帧数与编号宽度，以冒号分隔")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / SOURCE, ROOT / "rtl/common/zero_reduce.sv"]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    reference = out / "reference.sv"
    reference.write_text(subprocess.check_output(["git", "show", args.reference + ":" + SOURCE], cwd=ROOT,
        text=True).replace("module ps_scheduler_priority", "module reference_priority", 1))
    rows = []

    def run(command, log):
        with log.open("w") as stream:
            subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        return log.read_text()

    for profile in args.profiles:
        frames, width = map(int, profile.split(":"))
        samples = 4096 if frames > 64 else 65536
        label = f"f{frames}_w{width}"
        model = out / (label + ".sv")
        model.write_text(f'''// 对相同的完整候选集合比较两份实际优先编码模块。
module proof(
 input wire [{frames-1}:0] value, // 各帧的候选资格
 output wire equal_result // 两个模块的输出逐位一致
);
 wire [{width-1}:0] a,b;
 reference_priority #(.p_frames({frames}),.p_id_width({width})) u_a(value,a);
 ps_scheduler_priority #(.p_frames({frames}),.p_id_width({width})) u_b(value,b);
 assign equal_result=(a===b);
endmodule
''')
        script, log = out / (label + ".ys"), out / (label + "_formal.log")
        sources = [reference, *paths, model]
        script.write_text("read_slang --top proof " + shlex.join(map(str, sources)) +
                          "\nprep -top proof -flatten\nsat -verify -prove equal_result 1\n")
        if "SUCCESS!" not in run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log):
            raise RuntimeError("优先编码形式证明未完成")
        bench = out / (label + "_tb.sv")
        bench.write_text(f'''// 检查二态候选集合、每个输入的未知值以及混合四态输入。
module tb;
reg [{frames-1}:0] value,known;
wire equal_result;integer rng=32'h1763aa91,checks=0;
proof u_dut(value,equal_result);
function automatic integer random_word;
 rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
function automatic logic four(input logic [1:0] v);
 case(v)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
endfunction
task check;
 #1;checks++;if(equal_result!==1'b1)$fatal(1,"Priority differs frames={frames} width={width} value=%h",value);
endtask
initial begin
 for(integer sample=0;sample<{samples};sample++)begin
  for(integer b=0;b<{frames};b++)value[b]=sample<{samples//2} ? 1'(random_word()) : four(2'(random_word()));
  check();
 end
 for(integer sample=0;sample<32;sample++)begin
  for(integer b=0;b<{frames};b++)known[b]=1'(random_word());
  for(integer b=0;b<{frames};b++)begin value=known;value[b]=1'bx;check();value[b]=1'bz;check();end
 end
 value='0;check();value='1;check();value='x;check();value='z;check();
 $display("SCHEDULER_PRIORITY_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
        binary = out / (label + ".vvp")
        run(["iverilog", "-g2012", "-s", "tb", "-o", binary, *sources, bench], out / (label + "_compile.log"))
        simulation = out / (label + "_four_state.log")
        result = run(["vvp", binary], simulation)
        checks = re.search(r"SCHEDULER_PRIORITY_FOUR_STATE_PASS checks=(\d+)", result)
        if checks is None:
            raise RuntimeError("优先编码四态比较未完成")
        rows.append(dict(frames=frames, id_width=width, formal_passed=True, four_state_checks=int(checks[1]),
                         formal_log_sha256=digest(log), simulation_log_sha256=digest(simulation)))
        print(rows[-1], flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in paths}:
        raise RuntimeError("验证期间优先编码源文件发生变化")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, reference=args.reference,
        input_assumptions=[], source_sha256=hashes, cases=rows), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
