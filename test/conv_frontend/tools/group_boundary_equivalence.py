#!/usr/bin/env python3
"""证明通道范围的分段比较和两位偏移，并生成完整状态证明所用的通用表达式版本。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "rtl/npu/conv/conv_im2col_frontend.sv"


def digest(content):
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state-summary", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = SOURCE.read_text()
    compare_start = current.index("    if (p_group_low_w == 2) begin : g_split_high_compare")
    compare_end = current.index("    assign high_at_end", compare_start)
    compare_block = current[compare_start:compare_end]
    offset_start = current.index("      if (p_group_low_w == 2) begin : g_two_bit_offset")
    offset_end = current.index("      assign low_before_end", offset_start)
    offset_block = current[offset_start:offset_end]
    generic_compare = "    assign high_before_end = ch_q[15:p_group_low_w] < c.group_c[15:p_group_low_w];\n"
    generic_offset = "      assign lane_last_low = {1'b0, ch_q[p_group_low_w-1:0]} + (p_group_low_w+1)'(lane);\n"
    general = current[:offset_start] + generic_offset + current[offset_end:]
    general = general[:compare_start] + generic_compare + general[compare_end:]
    general_path = out / "general_frontend.sv"
    general_path.write_text(general)
    model = out / "group_boundary.sv"
    model.write_text("""module group_boundary_proof (
input logic [15:0] ch_q,group_c,
output logic equivalent
);
localparam integer p_group_low_w=2;
typedef struct packed {logic [15:0] group_c;} cfg_t;
cfg_t c;
logic high_before_end;
logic [3:0] offset_equal;
assign c.group_c=group_c;
""" + compare_block + """
for(genvar lane=0;lane<4;lane++) begin:g_lane
  logic [2:0] lane_last_low;
""" + offset_block + """
  assign offset_equal[lane]=lane_last_low==({1'b0,ch_q[1:0]}+3'(lane));
end
assign equivalent=(high_before_end==(ch_q[15:2]<group_c[15:2])) && (&offset_equal);
endmodule
""")
    script = out / "prove.ys"
    script.write_text("read_slang --top group_boundary_proof " + shlex.quote(str(model)) + "\n"
                      "prep -top group_boundary_proof -flatten\nsat -verify -prove equivalent 1\n")
    log = out / "formal.log"
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("Group boundary proof incomplete")
    state_summary_hash = None
    if args.state_summary:
        summary = json.loads(args.state_summary.read_text())
        if not summary["passed"] or summary["source_sha256"][str(SOURCE.relative_to(ROOT))] != digest(general.encode()):
            raise RuntimeError("Complete-state source does not match the generated general expressions")
        state_summary_hash = digest(args.state_summary.read_bytes())
    report = dict(passed=True, inputs_constrained=False, input_bits=32, compared_bits=13,
                  specialized_lanes=[3, 4], source_sha256=digest(current.encode()),
                  general_source_sha256=digest(general.encode()),
                  unchanged_outside_two_expression_blocks=True,
                  complete_state_summary_sha256=state_summary_hash,
                  model_sha256=digest(model.read_bytes()), log_sha256=digest(log.read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
