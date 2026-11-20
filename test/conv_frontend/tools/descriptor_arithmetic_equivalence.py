#!/usr/bin/env python3
"""证明描述符范围、通道地址及短像素移位在全部输入编码下等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[3]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"


def section(source, start, end):
    first = source.index(start)
    return source[first:source.index(end, first)]


def module(source, reference, name):
    power = re.search(r"  function automatic logic \[4:0\] power_shift\(.*?  endfunction",
                      source, re.S).group(0)
    if reference:
        compare = "assign tile_q_before_end = tile_q0 < reduction_len;\n"
        address = "assign channel_addr = group_base_addr + (32'(ch_q) << c.input_s16);\n"
        shift = section(source, "      window_index_shift_q<=cfg_pixel_bytes", "      retire_shift_q<=")
    else:
        compare = section(source, "  // 描述符的四段范围比较", "  if (RW < 32)")
        address = section(source, "  // 通道偏移最多十七位", "  // Configuration-time products")
        shift = section(source, "      // 短像素只检查缓存行范围", "      retire_shift_q<=")
    shift = shift.replace("window_index_shift_q", "window_index_shift_nxt").replace("<=", "=")
    return f'''module {name} #(parameter int LINE_BYTES=16) (
  input conv_im2col_pkg::conv_cfg_t c,
  input logic [31:0] tile_q0, reduction_len, group_base_addr, cfg_pixel_bytes,
  input logic [15:0] ch_q,
  output logic [37:0] observations
);
logic tile_q_before_end;
logic [3:0] tile_q_byte_before, tile_q_byte_equal;
logic [16:0] channel_byte_offset;
logic [17:0] channel_addr_low;
logic [14:0] channel_addr_high_next;
logic [31:0] channel_addr;
logic unused_channel_addr_carry;
logic [4:0] window_index_shift_nxt;
{power}
{compare}
{address}
always_comb begin
{shift}
end
assign observations = {{tile_q_before_end, channel_addr, window_index_shift_nxt}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-ref", default="d9abf98")
    parser.add_argument("--current-source", type=Path, default=ROOT / SOURCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = read_rtl_source(args.reference_ref + ":" + SOURCE, cwd=ROOT, text=True)
    current = args.current_source.read_text()
    harness = out / "arithmetic_miter.sv"
    harness.write_text(module(old, True, "arithmetic_reference") +
                       module(current, False, "arithmetic_current") + '''
module arithmetic_miter #(parameter int LINE_BYTES=16) (
  input conv_im2col_pkg::conv_cfg_t c,
  input logic [31:0] tile_q0, reduction_len, group_base_addr, cfg_pixel_bytes,
  input logic [15:0] ch_q,
  output logic equivalent
);
logic [37:0] reference_observations, current_observations;
arithmetic_reference #(.LINE_BYTES(LINE_BYTES)) u_reference (.observations(reference_observations), .*);
arithmetic_current #(.LINE_BYTES(LINE_BYTES)) u_current (.observations(current_observations), .*);
assign equivalent = reference_observations == current_observations;
endmodule
''')
    report = {"reference_ref": args.reference_ref, "inputs_constrained": False,
              "reference_sha256": hashlib.sha256(old.encode()).hexdigest(),
              "source_sha256": hashlib.sha256(current.encode()).hexdigest(),
              "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
              "outputs": ["tile_q_before_end", "channel_addr", "window_index_shift_nxt"],
              "runs": []}
    for line_bytes in (1, 2, 8, 12, 16, 32, 64, 128, 256):
        script = out / f"line{line_bytes}.ys"
        script.write_text("read_slang --top arithmetic_miter -GLINE_BYTES=" + str(line_bytes) + " " +
                          shlex.quote(str(ROOT / "rtl/npu/conv/conv_im2col_pkg.sv")) + " " +
                          shlex.quote(str(harness)) + "\nprep -top arithmetic_miter -flatten\n" +
                          "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        log_path = out / f"line{line_bytes}.log"
        with log_path.open("w") as log:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                     "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        passed = result.returncode == 0 and "SAT proof finished - no model found: SUCCESS!" in log_path.read_text()
        record = {"LINE_BYTES": line_bytes, "passed": passed, "observed_bits": 38,
                  "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest()}
        report["runs"].append(record)
        report["passed"] = all(run["passed"] for run in report["runs"])
        (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not passed:
            print(log_path.read_text()[-4000:])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
