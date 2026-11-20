#!/usr/bin/env python3
"""证明实际通道范围和快速接收表达式对任意输入保持一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
REGIONS = {
    "word": ("  assign incoming_delta =", "  if (CHUNK_COUNT_W + 1 < 32)"),
    "hit": ("  assign incoming_word_hit =", "  assign incoming_request="),
    "group": ("  // 组内范围按描述符列数拆分", "  assign incoming_tap_wrap = incoming_tap_wrap_q;"),
    "fast": ("  // 描述符字段分别比较，快速接收资格在末级合并。", "  always_comb begin\n    incoming_tap=tap0;"),
}
PORTS = (("ch0_q", "16"), ("cols_q", "TILE_COUNT_W"), ("group_c", "16"),
         ("tile_p0", "32"), ("p0", "32"), ("tile_q0", "32"), ("q0", "32"),
         ("next_group_q", "33"), ("tile_rows", "RW"), ("rows_q", "TILE_COUNT_W"),
         ("windowed", "1"), ("row_base_valid", "1"), ("coordinate_address_valid", "1"),
         ("row_base_addr", "32"), ("word_addr", "32"), ("addr", "32"),
         ("tap_wrap_bytes", "32"), ("tap_step_bytes", "32"), ("incoming_tap_wrap", "1"),
         ("finishing_tile", "1"), ("state", "5"), ("word_valid", "1"))
CHANNEL_START = "  // 通道位置先完成流式和解码更新，再选择同周期接收的快速描述符。"
CHANNEL_END = "  // 保存前端配置、描述符和坐标状态。\n"
PARAMETERS = "parameter int RW=5, TILE_COUNT_W=5, CACHE_POLICY=3, parameter bit p_cfg_idle_use_lut=1'b0"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def extract(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


def ports(values):
    return ",\n".join(f"input logic [{width}-1:0] {name}" for name, width in values)


def unit(label, bodies, enum):
    body = "\n".join(bodies.values()).replace("c.group_c", "group_c").replace("c.windowed", "windowed")
    if label == "reference":
        body += "\nassign incoming_q_equal = tile_q0 == q0;\n"
    return f"module {label}_incoming #({PARAMETERS})(\n" + ports(PORTS) + """,
output logic [6:0] observed);
logic [31:0] incoming_delta;
logic [2:0] incoming_word_low_sum,incoming_step_low_sum,incoming_wrap_low_sum;
logic incoming_q_equal;
logic [29:0] incoming_word_i_a,incoming_word_i_b,incoming_word_i_target,incoming_live_word_i_target;
logic incoming_word_i_carry_in,incoming_word_o_equal,incoming_live_word_o_equal,incoming_word_hit;
logic incoming_group_fits,incoming_fast,incoming_q_fast;
logic [5:0] incoming_fast_i_flags;
logic [1:0] incoming_position_equal;
logic [31:0] ch0;
assign ch0=32'(ch0_q);
""" + enum + "\n" + body + "\nassign observed={incoming_q_equal,incoming_group_fits,incoming_fast,incoming_q_fast,incoming_word_o_equal,incoming_live_word_o_equal,incoming_word_hit};\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="7ef39f0101ebf39184d11dbdc80a4042faee75c2")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE], cwd=ROOT, text=True)
    bodies = {label: {kind: extract(text, *bounds) for kind, bounds in REGIONS.items()}
              for label, text in (("reference", reference), ("current", current))}
    restored = current
    for kind in REGIONS:
        restored = restored.replace(bodies["current"][kind], bodies["reference"][kind], 1)
    restored = restored.replace("  logic [2:0] next_word_low_sum;\n  logic [2:0] incoming_step_low_sum, incoming_wrap_low_sum;",
        "  logic [2:0] next_word_low_sum, incoming_word_low_sum;", 1)
    restored = restored.replace("  logic incoming_q_equal;\n", "", 1)
    restored = restored.replace("    if (!incoming_q_equal) begin", "    if (tile_q0!=q0) begin", 1)
    channel = extract(restored, CHANNEL_START, CHANNEL_END) + CHANNEL_END
    restored = restored.replace(channel, "", 1)
    channel_assign = r"\bch_q\s*<=.*?;"
    if len(re.findall(channel_assign, channel)) != 2 or re.search(channel_assign, restored):
        raise RuntimeError("The channel process must own reset and normal updates")
    restored = restored.replace("  logic channel_descriptor_valid, channel_accept_fire, tile_ready_context;\n", "", 1)
    restored = restored.replace("  logic [15:0] channel_update, channel_value;\n", "", 1)
    restored = restored.replace("  logic [5:0] channel_accept_i_flags;\n", "", 1)
    start, end = "  assign finishing_tile=", "  assign busy ="
    restored = restored.replace(extract(restored, start, end), extract(reference, start, end), 1)
    normalize = lambda text: re.sub(r"\s+", "", re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S))
    if normalize(restored) != normalize(re.sub(channel_assign, "", reference)):
        raise RuntimeError("Unexpected frontend change outside the compared expressions")
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    lut = re.search(r"^module LUT6\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    model = out / "xilinx_lut6.v"
    model.write_text(lut + "\n")
    enum = re.search(r"typedef enum logic \[4:0\].*?} st_t;", current, re.S)[0]
    units = {label: unit(label, body, enum) for label, body in bodies.items()}
    for label, text in units.items():
        (out / (label + "_incoming.sv")).write_text(text)
    proof = out / "proof.sv"
    proof.write_text("\n".join(units.values()) + f"module comparison #({PARAMETERS})(\n" + ports(PORTS) +
        ",\noutput logic equivalent);\nlogic [6:0] expected,actual;\n" + "\n".join(
        f"{label}_incoming #(.RW(RW),.TILE_COUNT_W(TILE_COUNT_W),.CACHE_POLICY(CACHE_POLICY),"
        f".p_cfg_idle_use_lut(p_cfg_idle_use_lut)) u_{label}(.*,.observed({value}));"
        for label, value in (("reference", "expected"), ("current", "actual"))) +
        "\nassign equivalent=expected==actual;\nendmodule\n")
    configurations = [(5, count, 3, fpga) for count in (1, 2, 3, 4, 5, 6, 8, 15, 16, 32) for fpga in (0, 1)]
    configurations += [(5, 5, policy, fpga) for policy in (0, 1, 2) for fpga in (0, 1)]
    configurations += [(rw, 5, 3, 1) for rw in (1, 16, 32)]
    cases = []
    for rw, count_w, policy, fpga in configurations:
        name = f"rw{rw}_count{count_w}_policy{policy}_fpga{fpga}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("read_slang --top comparison " +
            f"-GRW={rw} -GTILE_COUNT_W={count_w} -GCACHE_POLICY={policy} -Gp_cfg_idle_use_lut={fpga} " +
            " ".join(shlex.quote(str(path)) for path in (model, ROOT / "rtl/common/add_equal.sv", proof)) +
            "\nprep -top comparison -flatten\ndelete t:$specify2\n"
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("Incomplete proof: " + name)
        cases.append(dict(RW=rw, TILE_COUNT_W=count_w, CACHE_POLICY=policy, fpga=bool(fpga),
            passed=True, log_sha256=digest(log.read_bytes())))
        print(name, "passed", flush=True)
    if (ROOT / SOURCE).read_text() != current:
        raise RuntimeError("Frontend source changed during proof")
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_compared_regions_and_channel_process=True, channel_control_proof_required=True, actual_source_expressions=True,
        inputs_constrained=False, group_range_upstream_included=True,
        common_source_sha256={"rtl/common/add_equal.sv": digest((ROOT / "rtl/common/add_equal.sv").read_bytes())},
        official_model_sha256=digest(library.read_bytes()), lut6_model_sha256=digest(model.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
