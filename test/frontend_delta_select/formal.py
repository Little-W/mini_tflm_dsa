#!/usr/bin/env python3
"""对实际前端的完整接收步长、低位进位和两个字地址等式进行无约束证明。"""
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
REFERENCE = "9846295cbfb14945f0b55a54f4abf99ee7c854c0"
START = "  // 描述符字段分别比较，快速接收资格在末级合并。"
END = "  // 坐标资格与单行条件提前合并，晚到的组范围保持单级接收选择。"
PORTS = (("tile_p0", 32), ("p0", 32), ("tile_q0", 32), ("q0", 32),
         ("next_group_q", 33), ("incoming_tap_wrap", 1),
         ("tap_step_bytes", 32), ("tap_wrap_bytes", 32),
         ("row_base_addr", 32), ("word_addr", 32), ("addr", 32))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def region(text, start=START, end=END):
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def sources(reference):
    current = (ROOT / SOURCE).read_text()
    previous = read_rtl_source(reference + ":" + SOURCE, cwd=ROOT, text=True)
    old_delta = re.search(r"  assign incoming_delta\s*=.*?;\n", previous, re.S)[0]
    old_carry = re.search(r"  assign incoming_word_i_carry_in\s*=.*?;\n", previous, re.S)[0]
    restored = current.replace(region(current), region(previous), 1)
    if restored != previous.replace(old_delta, "", 1).replace(old_carry, "", 1):
        raise RuntimeError("前端存在比较区域之外的修改")
    return previous, current, old_delta


def unit(text, label, old_delta=""):
    ports = ",\n".join(f"input logic [{width}-1:0] {name}" for name, width in PORTS)
    words = region(text, "  // 两种步长的低位进位并行计算，晚到的描述符比较只选择进位结果。",
                   "  if (CHUNK_COUNT_W + 1 < 32)")
    return f"module {label} #(parameter bit p_cfg_idle_use_lut=1'b0)(\n" + ports + """,
output logic [38:0] observed);
logic [31:0] incoming_delta;
logic incoming_q_equal, incoming_q_fast;
logic [1:0] incoming_position_equal;
logic [2:0] incoming_step_low_sum,incoming_wrap_low_sum;
logic [29:0] incoming_word_i_a,incoming_word_i_b,incoming_word_i_target,incoming_live_word_i_target;
logic incoming_word_i_carry_in,incoming_word_o_equal,incoming_live_word_o_equal;
""" + region(text) + old_delta + words + """
assign observed={incoming_position_equal,incoming_q_fast,incoming_q_equal,
                 incoming_word_o_equal,incoming_live_word_o_equal,incoming_word_i_carry_in,incoming_delta};
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, current, old_delta = sources(args.reference)
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    model = re.sub(r"\bspecify\b.*?\bendspecify\b", "", model, flags=re.S)
    model_path = out / "official_lut6.v"
    model_path.write_text(model + "\n")
    cases = []
    units = {}
    for label, text, delta in (("reference", reference, old_delta), ("current", current, "")):
        path = out / (label + ".sv")
        path.write_text(unit(text, label, delta))
        units[label] = path
    for fpga in (False, True):
        name = "fpga" if fpga else "generic"
        commands = []
        for label, path in units.items():
            files = [path, ROOT / "rtl/common/add_equal.sv"] + ([model_path] if fpga else [])
            commands += ["read_slang --top " + label + f" -Gp_cfg_idle_use_lut={int(fpga)} " +
                         " ".join(shlex.quote(str(p)) for p in files),
                         "prep -top " + label + " -flatten", "opt -full", "design -stash " + label]
        commands += ["design -copy-from reference reference", "design -copy-from current current",
                     "miter -equiv -flatten reference current comparison", "hierarchy -top comparison",
                     "opt -full", "sat -verify -prove trigger 0 -show-inputs -show-outputs"]
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("形式证明未完成: " + name)
        cases.append(dict(name=name, passed=True, input_bits=sum(width for _, width in PORTS),
                          output_bits=39, delta_bits=32, carry_bits=1, word_equal_bits=2, inputs_constrained=False,
                          script_sha256=sha(script.read_bytes()), log_sha256=sha(log.read_bytes())))
        print(name + ": passed", flush=True)
    init = int(re.search(r"LUT6 #\(\.INIT\(64'h([0-9a-f_]+)\)\) u_delta", current)[1].replace("_", ""), 16)
    carry_init = int(re.search(r"LUT6 #\(\.INIT\(64'h([0-9a-f_]+)\)\) u_carry", current)[1].replace("_", ""), 16)
    assert init == carry_init
    for bits in range(64):
        wrap_bit, step_bit, wrap, equal_low, equal_high, unused = [(bits >> index) & 1 for index in range(6)]
        expected = int(not (equal_low and equal_high)) & (wrap_bit if wrap else step_bit)
        assert ((init >> bits) & 1) == expected
        assert ((carry_init >> bits) & 1) == expected
    assert current == (ROOT / SOURCE).read_text()
    report = dict(passed=True, reference_commit=args.reference, source_sha256=sha(current.encode()),
                  reference_sha256=sha(reference.encode()), actual_source_expressions=True,
                  unchanged_outside_compare_and_delta=True, inputs_constrained=False,
                  delta_bits=32, carry_bits=1, word_equal_bits=2, lut_truth_table_cases=128, cases=cases,
                  common_source_sha256={"rtl/common/add_equal.sv": sha((ROOT / "rtl/common/add_equal.sv").read_bytes())},
                  official_library_sha256=sha(library.read_bytes()), official_lut6_sha256=sha(model_path.read_bytes()),
                  model_sha256={label: sha(path.read_bytes()) for label, path in units.items()},
                  script_sha256=sha(Path(__file__).read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
