#!/usr/bin/env python3
"""证明参数观察输出的配置不改变量化运算、控制或存储器访问。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage
sys.path.insert(0, str(ROOT / "test"))
from requant_test_utils import RTL_SOURCES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_wrapper(source, enabled):
    first = source.index("module vec_requant #(")
    last = source.index("\n);", first) + 3
    header = source[first:last].replace("module vec_requant #(", "module parameter_output_top #(", 1)
    header = header.replace(
            "    output logic signed [15:0] out_vec_s16[VLEN],\n"
            "    output logic signed [31:0] quant_multiplier_lane[VLEN],\n"
            "    output logic signed [31:0] quant_shift_lane[VLEN]",
            "    output logic signed [15:0] out_vec_s16[VLEN]")
    parameters = re.findall(r"parameter\s+(?:int|bit)(?:\s+unsigned)?\s+(\w+)\s*=", header)
    values = {name: name for name in parameters}
    if "p_parameter_output" in parameters:
        values["p_parameter_output"] = "1'b1" if enabled else "1'b0"
    return (header + "\nvec_requant #(\n" +
            ",\n".join(f"    .{name}({value})" for name, value in values.items()) +
            "\n) u_quant (.*, .quant_multiplier_lane(), .quant_shift_lane());\nendmodule\n")


def memory_interfaces(module):
    """同名存储共享任意返回数据，完整比较读写数据、地址、时钟及使能。"""
    models = {}
    for name, cell in sorted(list(module["cells"].items())):
        if cell["type"] != "$mem_v2" or not name.endswith(".mem") or int(cell["parameters"]["RD_PORTS"], 2) != 1:
            continue
        canonical_name = name.replace(".g_parameter_output.", ".")
        suffix = hashlib.sha256(canonical_name.encode()).hexdigest()[:20]
        connections = cell["connections"]
        read_bits = connections["RD_DATA"]
        driven_bits = [bit for port in sorted(connections) if port != "RD_DATA"
                       for bit in connections[port]]
        for port, direction, bits in [("memory_read_" + suffix, "input", read_bits),
                                      ("memory_drive_" + suffix, "output", driven_bits)]:
            module["ports"][port] = {"direction": direction, "bits": bits}
            module["netnames"][port] = {"hide_name": 0, "bits": bits, "attributes": {}}
        parameters = dict(cell["parameters"])
        parameters["MEMID"] = parameters["MEMID"].replace(".g_parameter_output.", ".")
        models[canonical_name] = {"parameters": parameters,
                        "ports": {port: len(bits) for port, bits in connections.items()}}
        del module["cells"][name]
    return models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", default=["16:64:2:32", "16:64:16:32", "8:32:1:8", "4:128:4:2"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependencies = [ROOT / name for name in RTL_SOURCES if not name.endswith('/vec_requant.sv')]
    sources = {"reference": ROOT / "rtl/npu/writeback/vec_requant.sv",
               "current": ROOT / "rtl/npu/writeback/vec_requant.sv"}
    snapshot = out / "inputs"
    snapshot.mkdir(exist_ok=True)
    saved_dependencies = []
    for path in dependencies:
        target = snapshot / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        saved_dependencies.append(target)
    dependencies = saved_dependencies
    for label, source in list(sources.items()):
        target = snapshot / (label + "_requant.sv")
        target.write_bytes(source.read_bytes())
        sources[label] = target
    hashes = {str(path): digest(path) for path in [*sources.values(), *dependencies]}
    report = {"passed": False, "source_sha256": hashes, "profiles": [],
              "inputs_constrained": False, "memory_read_data_constrained": False,
              "comparison": "全部运算输出、控制状态及存储器读写端口"}
    for profile in args.profiles:
        vlen, bus, lanes, reuse = map(int, profile.split(":"))
        for enabled in (False,):
            folder = out / (profile.replace(":", "_") + f"_observe{int(enabled)}")
            folder.mkdir(exist_ok=True)
            models = {}
            for label, source in sources.items():
                wrapper = folder / (label + "_wrapper.sv")
                wrapper.write_text(make_wrapper(source.read_text(), label == "reference"))
                raw = folder / (label + "_raw.json")
                script = folder / (label + "_read.ys")
                script.write_text(
                    f"read_slang --top parameter_output_top -D SYNTHESIS=1 -D XILINX_FPGA=1 "
                    f"-GVLEN={vlen} -GBUS_WIDTH={bus} -GMAX_IA_REUSE={reuse} -GENABLE_S16=1 "
                    f"-Gp_compute_lanes={lanes} -Gp_input_rows={vlen*reuse} " +
                    shlex.join(map(str, [*dependencies, source, wrapper])) +
                    "\nprep -top parameter_output_top -flatten\nsetattr -unset keep\nopt_clean -purge\nwrite_json " +
                    shlex.quote(str(raw)) + "\n")
                run_stage(script, folder / (label + "_read.log"), dict(os.environ))
                module = json.loads(raw.read_text())["modules"]["parameter_output_top"]
                models[label] = memory_interfaces(module)
                (folder / (label + ".json")).write_text(json.dumps({"modules": {label: module}}) + "\n")
            if models["reference"] != models["current"]:
                raise RuntimeError("两种参数配置的实际存储器参数或端口数量不同")
            script = folder / "prove.ys"
            script.write_text(
                f"read_json {folder}/reference.json\nread_json {folder}/current.json\nmemory_map\nopt_clean\n"
                "equiv_make reference current proof\nhierarchy -top proof\nasync2sync\nopt_clean\n"
                "equiv_simple -short -seq 1\nopt_clean\nequiv_induct -seq 3\nequiv_status -assert\n")
            log = folder / "prove.log"
            stage = run_stage(script, log, dict(os.environ))
            match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log.read_text())
            if match is None or int(match[2]):
                raise RuntimeError("量化参数配置证明未完成")
            record = {"vlen": vlen, "bus_width": bus, "compute_lanes": lanes, "reuse": reuse,
                      "compared_parameter_output": [True, False], "passed": True, "equivalent_bits": int(match[1]),
                      "memories": len(models["current"]), **stage}
            report["profiles"].append(record)
            (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(record), flush=True)
    if hashes != {str(path): digest(path) for path in [*sources.values(), *dependencies]}:
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
