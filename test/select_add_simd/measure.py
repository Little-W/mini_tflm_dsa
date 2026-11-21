#!/usr/bin/env python3
"""测量实际 S8 恢复调用，并证明默认映射后的完整结果。"""
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
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def port_paths(module):
    # 边界标记只用于路径分析，其寄存器不计入组合级数。
    for name, port in module["ports"].items():
        pin = "Q" if port["direction"] == "input" else "D"
        module["cells"]["$boundary$" + name] = {
            "type": "FDRE", "connections": {pin: port["bits"]},
            "port_directions": {pin: "output" if pin == "Q" else "input"},
            "attributes": {"fpga_register_origin": name},
        }
    return connected_paths(module, limit=8, group_limit=8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=HERE / "reference_select_add.sv")
    parser.add_argument("--candidate", type=Path, default=ROOT / "rtl/npu/compute/select_add.sv")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_root = out / "source"
    sources = {"reference": args.reference.resolve(), "candidate": args.candidate.resolve()}
    hashes = {label: digest(path) for label, path in sources.items()}
    copies = {}
    cases = {}
    for label, path in sources.items():
        folder = source_root / label
        folder.mkdir(parents=True, exist_ok=True)
        copies[label] = folder / "select_add.sv"
        shutil.copyfile(path, copies[label])
        cases[label] = {
            "top": "restore_bank", "options": ["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1"],
            "sources": [str(copies[label].relative_to(source_root)), "restore_bank.sv"],
            "configuration": "16 signed 8-bit samples, one signed 9-bit offset, independent signed 16-bit outputs",
        }
    wrapper = source_root / "restore_bank.sv"
    shutil.copyfile(HERE / "restore_bank.sv", wrapper)
    case_path = out / "cases.json"
    case_path.write_text(json.dumps(cases, indent=2) + "\n")
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
               "--source-root", str(source_root), "--case-config", str(case_path),
               "--cases", *cases, "--out", str(out / "synthesis")]
    if args.lock_file:
        command += ["--lock-file", str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)

    rows, paths = {}, {}
    for label in cases:
        folder = out / "synthesis" / label
        metrics = json.loads((folder / "metrics.json").read_text())
        module = json.loads((folder / "mapped.json").read_text())["modules"]["restore_bank"]
        dsp_settings = []
        for name, cell in module["cells"].items():
            if cell["type"] == "DSP48E1":
                settings = cell["parameters"]
                registers = {key: int(value, 2) for key, value in settings.items() if key.endswith("REG")}
                if any(registers.values()):
                    raise RuntimeError("恢复数据通路增加了内部寄存器")
                dsp_settings.append({"cell": name, "mode": settings["USE_SIMD"], "registers": registers})
        paths[label] = port_paths(module)
        rows[label] = {"resources": metrics["resources"],
                       "input_to_output_cells": paths[label]["longest_register_path_cells"],
                       "dsp_settings": dsp_settings}
    (out / "boundary_paths.json").write_text(json.dumps(paths, indent=2) + "\n")

    # 读取综合器自己的器件功能模型，检查每一位恢复结果。
    miter = out / "mapped_compare.sv"
    miter.write_text("""module mapped_compare(input [127:0] bytes,input [8:0] offset,output equivalent);
wire [255:0] expected,actual;
reference_restore u_reference(.bytes(bytes),.offset(offset),.values(expected));
mapped_restore u_mapped(.bytes(bytes),.offset(offset),.values(actual));
assign equivalent=expected==actual;
endmodule
""")
    script, log = out / "mapped_proof.ys", out / "mapped_proof.log"
    script.write_text(
        "read_slang --top restore_bank -D SYNTHESIS=1 " + shlex.join(map(str, [copies["reference"], wrapper])) +
        "\nrename restore_bank reference_restore\nread_json " +
        shlex.quote(str(out / "synthesis/candidate/mapped.json")) +
        "\nrename restore_bank mapped_restore\ndelete =A:blackbox\n"
        "read_verilog -overwrite +/xilinx/cells_sim.v\nread_verilog " + shlex.quote(str(miter)) +
        "\nprep -top mapped_compare -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("映射后的完整二值结果检查未完成")
    if hashes != {label: digest(path) for label, path in sources.items()}:
        raise RuntimeError("测量期间源文件发生变化")
    summary = json.loads((out / "synthesis/summary.json").read_text())
    result = {
        "passed": True, "source_sha256": hashes, "wrapper_sha256": digest(wrapper),
        "method": "synth_xilinx -top restore_bank -family xc7 -noiopad -noclkbuf -flatten",
        "mapping_options": "default", "tool": summary["tool"], "family": summary["family"],
        "part": summary["part"], "clock_period_ns": summary["clock_period_ns"], "cases": rows,
        "mapped_binary_equivalence": {"passed": True, "input_bits": 137, "output_bits": 256,
                                      "proof_log_sha256": digest(log)},
        "timing_scope": "Combinational input-to-output cell count; device delay and routing require implementation timing analysis.",
    }
    (out / "measurement.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({label: {"logic_lut_cells": row["resources"]["logic_lut_cells"],
                             "carry4": row["resources"]["carry4"], "dsp48e1": row["resources"]["dsp48e1"],
                             "input_to_output_cells": row["input_to_output_cells"]} for label, row in rows.items()}, indent=2))


if __name__ == "__main__":
    main()
