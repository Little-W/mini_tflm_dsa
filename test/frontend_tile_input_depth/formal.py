#!/usr/bin/env python3
"""证明实际前端描述符范围与快速接收条件对任意输入保持一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
RANGE_START = "  if (RW < 32) begin : g_tile_row_range\n"
RANGE_END = "  // 通道偏移最多十七位"
FAST_END = "    incoming_tap=tap0;"
FAST_START = "  // 描述符字段分别比较，快速接收资格在末级合并。\n"
OLD_FAST_START = "  always_comb begin\n    // 组末偏移与描述符一起保存"
RANGE_PORTS = (("tile_p0", "32"), ("tile_rows", "RW"), ("position_count", "32"),
               ("position_high_minus_one_q", "p_row_high_w"))
FAST_PORTS = (("tile_p0", "32"), ("p0", "32"), ("tile_q0", "32"), ("q0", "32"),
              ("next_group_q", "33"), ("tile_rows", "RW"), ("rows_q", "TILE_COUNT_W"),
              ("windowed", "1"), ("row_base_valid", "1"),
              ("coordinate_address_valid", "1"), ("incoming_group_fits", "1"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def extract(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


def ports(values):
    return ",\n".join("input logic [" + width + "-1:0] " + name for name, width in values)


PARAMETERS = """parameter int RW=5, TILE_COUNT_W=5, CACHE_POLICY=3,
parameter bit p_cfg_idle_use_lut=1'b0,
parameter int p_row_low_w=RW<32 ? RW : 31,
parameter int p_row_high_w=32-p_row_low_w"""


def unit(label, kind, body):
    selected = RANGE_PORTS if kind == "range" else FAST_PORTS
    header = "module " + label + "_" + kind + " #(\n" + PARAMETERS + ")(\n" + ports(selected)
    if kind == "range":
        return header + ",\noutput logic observed);\nlogic tile_rows_in_range;\n" + body + \
            "assign observed=tile_rows_in_range;\nendmodule\n"
    if "always_comb begin" in body:
        if label == "reference":
            body += "  end\n"
        else:
            body = body.removesuffix("  always_comb begin\n")
    body = body.replace("c.windowed", "windowed")
    return header + ",\noutput logic [1:0] observed);\n" + \
        "logic incoming_fast,incoming_q_fast;\nlogic [5:0] incoming_fast_i_flags;\nlogic [1:0] incoming_position_equal;\n" + body + \
        "assign observed={incoming_fast,incoming_q_fast};\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="b20921b3")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference + ":" + SOURCE, cwd=ROOT, text=True)
    bodies = {
        "range": {"reference": extract(reference, RANGE_START, RANGE_END),
                  "current": extract(current, RANGE_START, RANGE_END)},
        "fast": {"reference": extract(reference, OLD_FAST_START, FAST_END),
                 "current": extract(current, FAST_START, FAST_END)},
    }
    restored = current
    for kind in bodies:
        restored = restored.replace(bodies[kind]["current"], bodies[kind]["reference"], 1)
    restored = restored.replace("  logic [5:0] incoming_fast_i_flags;\n", "", 1)
    restored = restored.replace("  logic [1:0] incoming_position_equal;\n", "", 1)
    if restored != reference:
        raise RuntimeError("Frontend changes outside the compared source regions")
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    lut = re.search(r"^module LUT6\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    model = out / "xilinx_lut6.v"
    model.write_text(lut + "\n")
    cases = []
    for kind, pair in bodies.items():
        units = {label: unit(label, kind, body) for label, body in pair.items()}
        for label, text in units.items():
            (out / (label + "_" + kind + ".sv")).write_text(text)
        selected = RANGE_PORTS if kind == "range" else FAST_PORTS
        proof = out / (kind + "_proof.sv")
        proof.write_text("\n".join(units.values()) + "module comparison #(\n" + PARAMETERS + ")(\n" +
            ports(selected) + ",\noutput logic equivalent);\nlogic [" +
            ("0" if kind == "range" else "1") + ":0] expected,actual;\n" +
            "\n".join(label + "_" + kind + " #(.RW(RW),.TILE_COUNT_W(TILE_COUNT_W)," +
            ".CACHE_POLICY(CACHE_POLICY),.p_cfg_idle_use_lut(p_cfg_idle_use_lut)) u_" + label +
            " (.*,.observed(" + ("expected" if label == "reference" else "actual") + "));"
            for label in pair) + "\nassign equivalent=expected==actual;\nendmodule\n")
        configurations = [(rw, 5, 3, fpga) for rw in (1, 4, 5, 6, 16, 31, 32) for fpga in (0, 1)] \
            if kind == "range" else [(5, 5, policy, fpga) for policy in range(4) for fpga in (0, 1)]
        if kind == "fast":
            configurations += [(rw, count, 3, 1) for rw, count in ((1, 1), (3, 5), (16, 16), (32, 32))]
        for rw, count_w, policy, fpga in configurations:
            name = f"{kind}_rw{rw}_count{count_w}_policy{policy}_fpga{fpga}"
            script, log = out / (name + ".ys"), out / (name + ".log")
            script.write_text("read_slang --top comparison " +
                f"-GRW={rw} -GTILE_COUNT_W={count_w} -GCACHE_POLICY={policy} -Gp_cfg_idle_use_lut={fpga} " +
                shlex.quote(str(model)) + " " + shlex.quote(str(proof)) +
                "\nprep -top comparison -flatten\ndelete t:$specify2\n" +
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError("Proof incomplete: " + name)
            cases.append(dict(kind=kind, RW=rw, TILE_COUNT_W=count_w, CACHE_POLICY=policy,
                fpga=bool(fpga), passed=True, log_sha256=digest(log.read_bytes())))
            print(name, "passed", flush=True)
    if (ROOT / SOURCE).read_text() != current:
        raise RuntimeError("Frontend source changed during proof")
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_compared_regions=True, actual_source_expressions=True,
        inputs_constrained=False, official_model_sha256=digest(library.read_bytes()),
        lut6_model_sha256=digest(model.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
