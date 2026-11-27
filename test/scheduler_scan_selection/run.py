#!/usr/bin/env python3
"""验证生产调度器扫描表达式的任意二态和四态输入。"""
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
SOURCE = "rtl/npu/control/ps_window_scheduler.sv"
CANDIDATES = ("scan_open_candidate", "scan_protected_candidate", "scan_after_candidate", "scan_wrap_candidate")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(source: str, label: str, width: int) -> str:
    fields = [("phase", 4), ("protected_valid", 1), ("candidate_after_exists", 1), ("candidate_exists", 1),
              ("opened", width + 1), ("target", width + 1)]
    fields += [(name, width) for name in ("protected_id", "after_first_id", "eligible_first_id")]
    state_names = re.search(r"typedef enum logic \[3:0\]\s*\{([^}]+)\}", source, re.S)[1].split(",")
    declarations = ["localparam " + ", ".join(f"{name.strip()}=4'd{index}" for index, name in enumerate(state_names)) + ";",
                    f"localparam ID_W={width};", "logic candidate_found, candidate_init;",
                    "logic selected_init_q=1'b0;", f"logic [{width-1}:0] selected_id_q='0, candidate_id;",
                    f"logic [{width-1}:0] scanned_id, scanned_reference, " + ", ".join(CANDIDATES) + ";"]
    offset = 0
    for name, bits in fields:
        declarations.append(f"wire [{bits-1}:0] {name}=values[{offset} +: {bits}];")
        offset += bits
    assignments = []
    for name in CANDIDATES:
        match = re.search(r"\bassign\s+" + name + r"\s*=.*?;", source, re.S)
        if match:
            assignments.append(match[0])
    first = source.index("        candidate_found = 1'b0;")
    body = source[first:source.index("        candidate_row =", first)]
    return (f"// 采用生产文件中的扫描分支与候选赋值。\nmodule {label}(\n"
            f"    input wire [{offset-1}:0] values, // 完整选择输入\n"
            f"    output wire [{width}:0] result // 候选存在标记和帧编号\n);\n" +
            "\n".join(declarations + assignments) + "\nalways_comb begin\n" + body +
            "end\nassign result={candidate_found,scanned_id};\nendmodule\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="92f722e6")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE], cwd=ROOT, text=True)
    rows = []

    def run(command, log):
        with log.open("w") as stream:
            subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        return log.read_text()

    for width in (1, 2, 4, 5, 8):
        bits = 9 + 5 * width
        path = out / f"model_w{width}.sv"
        path.write_text(model(reference, "reference_model", width) + model(source, "current_model", width) +
            "// 比较两份实际扫描表达式的完整输出。\nmodule proof(\n"
            f"input wire [{bits-1}:0] values, // 两个表达式共享的输入\n"
            "output wire equal_result // 候选存在标记和编号逐位一致\n);\n"
            f"wire [{width}:0] a,b;reference_model u_a(values,a);current_model u_b(values,b);\n"
            "assign equal_result=(a===b);endmodule\n")
        script, log = out / f"w{width}.ys", out / f"w{width}_formal.log"
        script.write_text("read_slang --top proof " + shlex.quote(str(path)) +
                          "\nprep -top proof -flatten\nsat -verify -prove equal_result 1\n")
        text = run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
        if "SUCCESS!" not in text:
            raise RuntimeError("扫描选择组合证明未完成")
        bench = out / f"tb_w{width}.sv"
        bench.write_text(f'''// 枚举控制字段并混合任意编号、高位和未知输入。
module tb;
reg [{bits-1}:0] values;
wire equal_result; integer rng=32'h173623a9,checks=0;
proof u_dut(values,equal_result);
function automatic integer random_word;
 rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
function automatic logic four(input logic [1:0] value);
 case(value)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
endfunction
task check;
 #1;checks++;if(equal_result!==1'b1)$fatal(1,"Scan differs width={width} values=%h",values);
endtask
initial begin
 for(integer sample=0;sample<65536;sample++)begin
  for(integer bit_index=0;bit_index<{bits};bit_index++)
   values[bit_index]=sample<32768 ? 1'(random_word()) : four(2'(random_word()));
  check();
 end
 for(integer pattern=0;pattern<16384;pattern++)begin
  for(integer bit_index=0;bit_index<{bits};bit_index++)values[bit_index]=1'(random_word());
  for(integer bit_index=0;bit_index<7;bit_index++)values[bit_index]=four(2'(pattern>>(2*bit_index)));
  check();
 end
 values='x;check();values='z;check();
 $display("SCHEDULER_SCAN_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
        binary = out / f"w{width}.vvp"
        run(["iverilog", "-g2012", "-s", "tb", "-o", binary, path, bench], out / f"w{width}_compile.log")
        simulation = out / f"w{width}_four_state.log"
        result = run(["vvp", binary], simulation)
        checks = re.search(r"SCHEDULER_SCAN_FOUR_STATE_PASS checks=(\d+)", result)
        if checks is None:
            raise RuntimeError("扫描选择四态比较未完成")
        rows.append(dict(id_width=width, formal_passed=True, four_state_checks=int(checks[1]),
                         formal_log_sha256=digest(log), simulation_log_sha256=digest(simulation)))
        print(rows[-1], flush=True)
    if source != (ROOT / SOURCE).read_text():
        raise RuntimeError("验证期间生产调度器发生变化")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, input_assumptions=[], reference=args.reference,
        source_sha256={SOURCE: digest(ROOT / SOURCE)}, cases=rows), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
