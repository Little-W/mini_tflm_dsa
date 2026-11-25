#!/usr/bin/env python3
"""证明核步进标签比较的完整地址模运算和四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def comparison(source: str, shift: int) -> str:
    first = source.index("  assign next_word_i_target = ")
    last = source.index("  // 双核位置步长", first)
    body = source[first:last]
    return f"""module comparison(input logic [31:0] i_tap_group_base,i_tap_step_bytes,
i_tap_wrap_bytes,i_addr,input logic o_tap_wrap,output logic equivalent);
localparam int p_word_shift={shift};
logic [31-p_word_shift:0] next_word_i_target;
logic [1:0] next_word_match;
logic o_next_word_o_equal;
wire [31:0] o_next_tap_addr=i_tap_group_base+(o_tap_wrap?i_tap_wrap_bytes:i_tap_step_bytes);
wire reference_equal=o_next_tap_addr[31:p_word_shift]==i_addr[31:p_word_shift];
""" + body + """
`ifdef SYNTHESIS
assign equivalent=o_next_word_o_equal==reference_equal;
`else
assign equivalent=o_next_word_o_equal===reference_equal;
`endif
endmodule
"""


BENCH = """module tb;
logic [128:0] stimulus,known_stimulus;
wire [31:0] i_tap_group_base=stimulus[31:0];
wire [31:0] i_tap_step_bytes=stimulus[63:32];
wire [31:0] i_tap_wrap_bytes=stimulus[95:64];
wire [31:0] i_addr=stimulus[127:96];
wire o_tap_wrap=stimulus[128];
wire equivalent;
integer checks=0;
comparison dut(.*);
task automatic check;
  #1;
  if(equivalent!==1'b1)$fatal(1,"Next-word tag mismatch stimulus=%h",stimulus);
  checks++;
endtask
initial begin
  stimulus='0;check();stimulus='1;check();
  for(int trial=0;trial<16;trial++)begin
    stimulus={1'($urandom()),$urandom,$urandom,$urandom,$urandom};
    if(trial[0])stimulus[127:96]=stimulus[31:0]+(stimulus[128]?stimulus[95:64]:stimulus[63:32]);
    known_stimulus=stimulus;check();
    for(int bit_index=0;bit_index<129;bit_index++)begin
      stimulus=known_stimulus;stimulus[bit_index]=1'bx;check();
      stimulus=known_stimulus;stimulus[bit_index]=1'bz;check();
    end
    stimulus='x;check();stimulus='z;check();
  end
  $display("NEXT_WORD_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
"""


def run(command: list[str], log: Path, timeout: int) -> None:
    with log.open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    geometry = root / "rtl/npu/conv/conv_im2col_geometry.sv"
    helper = root / "rtl/common/add_equal.sv"
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (geometry, helper)}
    local_helper = out / helper.name
    local_helper.write_text(helper.read_text().replace(
        "parameter int unsigned", "parameter integer").replace(
        "localparam int unsigned", "localparam integer"))
    bench = out / "bench.sv"
    bench.write_text(BENCH)
    runs = []
    for shift in range(2, 9):
        model = out / f"shift{shift}.sv"
        model.write_text(comparison(geometry.read_text(), shift))
        proof = out / f"shift{shift}.ys"
        proof.write_text("read_slang --top comparison -D SYNTHESIS=1 " +
                         shlex.join(map(str, (helper, model))) + "\n" +
                         "prep -top comparison -flatten\ncheck -assert\n" +
                         "sat -set-def-inputs -prove equivalent 1 -verify\n")
        run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(proof)],
            proof.with_suffix(".log"), 180)
        binary = out / f"shift{shift}.vvp"
        run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", str(binary),
             str(local_helper), str(model), str(bench)], out / f"shift{shift}.build.log", 60)
        log = out / f"shift{shift}.run.log"
        run([shutil.which("vvp") or "vvp", str(binary)], log, 120)
        output = log.read_text().strip()
        if "NEXT_WORD_FOUR_STATE_PASS" not in output:
            raise AssertionError(output)
        runs.append({"word_shift": shift, "formal_passed": True, "four_state_passed": True,
                     "simulation": output, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"NEXT_WORD_MATCH_PASS shift={shift}", flush=True)
    unchanged = hashes == {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in (geometry, helper)}
    if not unchanged:
        raise RuntimeError("Next-word match sources changed during validation")
    report = {"passed": True, "sources_unchanged": True, "source_sha256": hashes,
              "address_width": 32, "input_assumptions": [], "added_state_bits": 0, "runs": runs}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
