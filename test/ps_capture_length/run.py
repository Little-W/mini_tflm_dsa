#!/usr/bin/env python3
"""证明 PS 接收行数比较的数值、进位及四态行为，并生成局部综合输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]
RTL = Path("rtl/npu/ps_compact/ps_frame_store.sv")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text: str) -> str:
    start = text.index("    localparam int p_capture_width")
    stop = text.index("    reg frame_init_q", start)
    declarations = text[start:stop]
    start = text.index("    assign capture_end_i_a")
    stop = text.index("    reg [511:0] encode_commit_packet", start)
    return declarations + text[start:stop]


def model(name: str, width: int, body: str) -> str:
    return f"""module {name}(input logic [{2*width}:0] stimulus, output logic result);
    localparam integer LENGTH_BITS={width};
    logic [LENGTH_BITS-1:0] capture_count, frame_rows_q;
    logic encoder_start;
    assign {{capture_count, frame_rows_q, encoder_start}}=stimulus;
{body}
    endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = read_rtl_text(root / RTL)
    body = extract(text)
    common = root / "rtl/common/add_equal.sv"
    runs = []
    source_dirs = {}
    for width in [1, 2, 6, 10, 16, 31, 32, 33]:
        folder = out / f"width{width}"
        folder.mkdir(exist_ok=True)
        source = folder / "comparison.sv"
        reference = model("reference", width,
            "    assign result = capture_count + (encoder_start ? 1 : 0) == frame_rows_q;")
        current = model("current", width, body + "    assign result=capture_length_match;\n")
        source.write_text(reference + current + f"""
        module proof(input logic [{2*width}:0] stimulus, output logic equivalent);
          logic a,b;
          reference r(stimulus,a); current c(stimulus,b);
          assign equivalent=(a===b);
        endmodule
""")
        script, log = folder / "proof.ys", folder / "proof.log"
        script.write_text("read_slang --top proof -DXILINX_FPGA=1 -DSYNTHESIS=1 " +
            shlex.join([str(common), str(source)]) + "\n"
            "prep -top proof -flatten\ncheck -assert\n"
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        if "SUCCESS!" not in read_rtl_text(log):
            raise RuntimeError(f"Incomplete formal proof: {log}")
        bench = folder / "four_state.sv"
        bench.write_text(f"""module tb;
          logic [{2*width}:0] stimulus;
          logic equivalent;
          integer checks=0, value;
          proof dut(stimulus,equivalent);
          task automatic check;
            #1;
            if (equivalent!==1'b1) $fatal(1,"Capture length differs width={width} input=%b",stimulus);
            checks++;
          endtask
          initial begin
            stimulus='0;check();stimulus='1;check();
            stimulus='x;check();stimulus='z;check();
            for (integer trial=0;trial<5000;trial++) begin
              for (integer bit_index=0;bit_index<{2*width+1};bit_index++) begin
                value=$urandom_range(0,7);
                if (value==0) stimulus[bit_index]=1'bx;
                else if (value==1) stimulus[bit_index]=1'bz;
                else stimulus[bit_index]=1'($urandom);
              end
              check();
            end
            for (integer position=0;position<{width};position++) begin
              stimulus='0;
              stimulus[{2*width}:{width+1}]={width}'(1)<<position;
              stimulus[{width}:1]=stimulus[{2*width}:{width+1}];check();
              stimulus[0]=1'b1;check();
              stimulus[{width}:1]=stimulus[{width}:1]+{width}'(1);check();
            end
            $display("CAPTURE_LENGTH_PASS checks=%0d",checks);$finish;
          end
        endmodule
""")
        binary = folder / "four_state.vvp"
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", "-DXILINX_FPGA=1",
                            "-o", str(binary), str(common), str(source), str(bench)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, check=True)
        (folder / "four_state.log").write_text(result.stdout + result.stderr)
        checks = 5004 + 3*width
        if f"CAPTURE_LENGTH_PASS checks={checks}" not in result.stdout:
            raise RuntimeError("Incomplete four-state comparison")
        runs.append(dict(width=width, passed=True, four_state_comparisons=checks,
                         rtl_model_sha256=digest(source), formal_log_sha256=digest(log)))
        if width == 10:
            for label, expression in [("reference", reference), ("current", current)]:
                directory = out / (label + "_source")
                directory.mkdir(exist_ok=True)
                path = directory / "capture_measure.sv"
                path.write_text(expression + f"""
module capture_measure(input logic clk, input logic [20:0] i_data, output logic o_match);
  logic [20:0] saved;
  logic matched;
  always_ff @(posedge clk) begin saved<=i_data; o_match<=matched; end
  {label} u_compare(.stimulus(saved),.result(matched));
endmodule
""")
                source_dirs[label] = dict(top="capture_measure", sources=[str(common),str(path)],
                    options=["-DXILINX_FPGA=1","-DSYNTHESIS=1"],
                    configuration="10-bit capture count with registered measurement inputs and output")
    (out / "synthesis_cases.json").write_text(json.dumps(source_dirs, indent=2) + "\n")
    if text != read_rtl_text(root / RTL):
        raise RuntimeError("RTL changed during verification")
    summary = dict(passed=True, source_sha256={str(RTL):digest(root/RTL),
        "rtl/common/add_equal.sv":digest(common)}, input_constraints=[], runs=runs)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
