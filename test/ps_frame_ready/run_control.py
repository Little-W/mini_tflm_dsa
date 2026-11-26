#!/usr/bin/env python3
"""从完整帧存储提取实际组合控制，检查任意状态输入与四态行为。"""
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
SOURCE = "rtl/npu/ps_compact/ps_frame_store.sv"
FIELDS = [
    ("frame_request", 1), ("frame_accept", 1), ("capacity_fault", 1),
    ("command_present", 1), ("command_accepted", 1), ("configuration_ready", 1),
    ("request_pending_q", 1), ("request_fits_q", 1), ("input_ended", 1),
    ("replay_armed", 1), ("replay_active", 1), ("replay_launch_q", 1),
    ("encoder_done", 1), ("commit_next_complete_q", 1), ("ram_read_valid", 1),
    ("decoder_done", 1), ("frame_final_q", 1), ("commit_complete_q", 1),
    ("frame_init_q", 1), ("replay_complete_q", 1), ("frame_single_row_q", 1),
    ("read_remaining_q", 1), ("prefetch_credit_available", 1), ("clear_metadata", 1),
    ("request_q.init", 1), ("request_q.legal", 1), ("request_q.id", 4),
    ("frame_id_q", 4), ("decoded_count", 4), ("decoder_inflight", 4), ("read_index", 10),
]
WIDTH = sum(width for _, width in FIELDS)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(source: str, name: str) -> str:
    start = source.index("    assign prepare_state_eligible")
    prepare = source[start:source.index("    assign frame_pressure", start)]
    start = source.index("    logic prefetch_prepare, prefetch_fire;")
    prefetch = source[start:source.index("    wire [p_cursor_bits-1:0] read_issue_cursor", start)]
    start = source.index("    assign frame_ready=") if "    assign frame_ready=" in source else source.index("    (* keep = \"true\" *) logic complete_data_idle;")
    ready = source[start:source.index("    // 存储返回行直接写入队列", start)]
    start = source.index("    wire cancel_prepared")
    cancel = source[start:source.index(";", start)+1]
    start = source.index("    wire prepare_read_conflict")
    conflict = source[start:source.index(";", start)+1]
    declarations, assignments, offset = [], [], 0
    for field, width in FIELDS:
        if "." not in field:
            declarations.append(f"wire [{width-1}:0] {field};")
        assignments.append(f"assign {field}=values[{offset}+:{width}];")
        offset += width
    return f"""// 以自由输入表达实际帧状态，比较帧接收、完成和预取的组合结果。
module {name}(
    input wire [{WIDTH-1}:0] values, // 请求、帧状态及队列计数。
    output wire [5:0] result // 接收、完成和预取的六个公开或内部资格。
);
typedef struct packed {{logic [3:0] id; logic init, legal;}} request_context_t;
request_context_t request_q;
logic complete_now, complete_eligible, prepare_eligible, prepare_state_eligible, prepare_start;
wire frame_ready;
""" + "\n".join(declarations+assignments) + "\nwire last_commit_now = encoder_done && !capacity_fault && commit_next_complete_q;\n" + cancel + "\n" + prepare + conflict + "\n" + prefetch + ready + """
assign result={frame_ready,complete_eligible,complete_now,prepare_start,prefetch_prepare,prefetch_fire};
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="05c9b052")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    actual = root / SOURCE
    reference = subprocess.check_output(["git", "show", args.reference+":"+SOURCE], cwd=ROOT, text=True)
    model = out / "control.sv"
    model.write_text(extract(reference, "reference_control")+extract(actual.read_text(), "current_control")+f"""
// 比较两版实际表达式的全部控制输出。
module proof(input wire [{WIDTH-1}:0] values, output wire equivalent);
wire [5:0] expected, actual;
reference_control u_reference(values,expected);
current_control u_current(values,actual);
assign equivalent=expected==actual;
endmodule
""")
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolve([model], root)
    hashes = {str(path): digest(path) for path in [actual, *sources]}
    bench = out / "four_state.sv"
    bench.write_text(f"""// 检查请求、容量状态和任意内部帧状态的四态传播。
module tb;
reg [{WIDTH-1}:0] values, known_values;
wire [5:0] expected, actual;
integer sample, bit_index, choice, checks=0;
reg [31:0] state=32'h28c95e61;
reference_control u_reference(values,expected);
current_control u_current(values,actual);
task check;
 begin
  #1;checks=checks+1;
  if(actual!==expected)$fatal(1,"Frame control differs: values=%h expected=%h actual=%h",values,expected,actual);
 end
endtask
initial begin
 for(sample=0;sample<65536;sample=sample+1)begin
  for(bit_index=0;bit_index<{WIDTH};bit_index=bit_index+1)begin
   state=state^(state<<13);state=state^(state>>17);state=state^(state<<5);
   choice=bit_index<3 ? ((sample>>(2*bit_index))&3) : sample<32768 ? int'(state[0]) : int'(state[1:0]);
   case(choice)
    0:values[bit_index]=1'b0;
    1:values[bit_index]=1'b1;
    2:values[bit_index]=1'bx;
    3:values[bit_index]=1'bz;
   endcase
  end
  check();
 end
 for(sample=0;sample<256;sample=sample+1)begin
  for(bit_index=0;bit_index<{WIDTH};bit_index=bit_index+1)begin
   state=state^(state<<13);state=state^(state>>17);state=state^(state<<5);
   known_values[bit_index]=state[0];
  end
  for(bit_index=0;bit_index<{WIDTH};bit_index=bit_index+1)begin
   values=known_values;values[bit_index]=1'bx;check();
   values=known_values;values[bit_index]=1'bz;check();
  end
 end
 values='x;check();values='z;check();
 $display("PS_FRAME_READY_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
""")
    runs = []

    def execute(command: list[str], log: Path) -> None:
        with log.open("w") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           timeout=300, check=True)

    for synthesis in (False, True):
        name = "synthesis" if synthesis else "generic"
        defines = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if synthesis else []
        script, log = out / (name+".ys"), out / (name+"_formal.log")
        script.write_text("read_slang --top proof "+shlex.join((defines if synthesis else ["-USYNTHESIS", "-UXILINX_FPGA"])+list(map(str, sources)))+
                          "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
                          "prep -top proof -flatten\nopt -full\nsat -verify -prove equivalent 1\n")
        execute([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)], log)
        binary, simulation = out / (name+".vvp"), out / (name+"_four_state.log")
        execute(["iverilog", "-g2012", "-s", "tb", *defines, "-o", str(binary),
                 *map(str, sources), str(bench)], out / (name+"_compile.log"))
        execute(["vvp", str(binary)], simulation)
        match = re.search(r"PS_FRAME_READY_FOUR_STATE_PASS checks=(\d+)", simulation.read_text())
        assert match
        binary.unlink()
        runs.append(dict(synthesis=synthesis, passed=True, formal_log_sha256=digest(log),
                         four_state_comparisons=int(match[1]), four_state_log_sha256=digest(simulation)))
        print(name, "PASS", match[1], flush=True)
    assert hashes == {str(path): digest(path) for path in [actual, *sources]}
    report = dict(passed=True, reference=args.reference, reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  source_sha256=hashes, input_constraints=[], controls_compared=6, runs=runs,
                  test_sha256=digest(Path(__file__)))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
