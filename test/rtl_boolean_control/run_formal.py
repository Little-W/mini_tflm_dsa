#!/usr/bin/env python3
"""验证公共控制表达式、配置接收和故障输出的全部输入组合。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
TOP = Path("rtl/npu/top/npu_top.sv")
SCHEDULER = Path("rtl/npu/control/ps_window_scheduler.sv")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="653477ede3c51bbe7f27c5bd7fc4f7131689df05")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / TOP).read_text()
    reference = read_rtl_source(f"{args.reference}:{TOP}", cwd=ROOT, text=True)
    admission = load("admission_source", "test/npu_admission/run_formal.py")
    fault = load("fault_source", "test/npu_fault_fanin/extract_fault.py")
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    models = out / "reference_primitives.sv"
    bodies = []
    for primitive in ("LUT6", "LUT6_2"):
        body = re.search(r"^module " + primitive + r"\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
        bodies.append(re.sub(r"\bspecify\b.*?\bendspecify\b", "", body, flags=re.S))
    models.write_text("\n\n".join(bodies) + "\n")
    report = {
        "passed": False,
        "reference_commit": args.reference,
        "inputs_constrained": False,
        "sources": {str(path): digest(ROOT / path) for path in (TOP, SCHEDULER)},
        "runs": [],
    }

    def run(name, commands, parameters):
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=180,
            )
        passed = result.returncode == 0 and "SAT proof finished - no model found: SUCCESS!" in log.read_text()
        report["runs"].append({"case": name, **parameters, "passed": passed, "log_sha256": digest(log)})
        (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        if not passed:
            raise RuntimeError(f"Formal comparison failed: {log}")
        print(name, "PASS", flush=True)

    # 提取两份实际代码中的完整组合区段，内部临时信号不作为接口输出。
    for kind in ("admission", "fault"):
        snapshots = {}
        for label, source in (("reference", reference), ("current", current)):
            if kind == "admission":
                text = admission.admission(source, "control_logic")
                text = text.replace("    output logic sa_ready, cfg_start_event);", """    input logic kernel_loader_o_quiescent, block_dma_arbiter_o_kernel_eligible,
    input logic block_dma_arbiter_i_abort, kernel_loader_o_admission_request,
    output logic sa_ready, cfg_start_event);""")
            else:
                text = fault.module_source(source, "control_logic")
                text = text.replace("output logic task_fault, arbiter_abort, selected_lut",
                                    "output logic task_fault, arbiter_abort")
                text = text.replace("    assign selected_lut =", "    wire selected_lut =")
            snapshots[label] = out / f"{kind}_{label}.sv"
            snapshots[label].write_text(text)
        for fpga in (False, True):
            define = "-DXILINX_FPGA=1 -DSYNTHESIS=1" if fpga else "-DASIC_SYNTHESIS=1"
            commands = []
            for label, path in snapshots.items():
                commands += [
                    f"read_slang {define} --top control_logic {shlex.quote(str(path))} {shlex.quote(str(models))}",
                    "prep -top control_logic -flatten", "check -assert",
                    f"rename control_logic {label}", f"design -stash {label}",
                ]
            commands += [
                "design -copy-from reference -as reference reference",
                "design -copy-from current -as current current",
                "miter -equiv -flatten reference current proof", "hierarchy -top proof",
                "sat -verify -prove trigger 0 -show-inputs -show-outputs",
            ]
            run(f"{kind}_fpga{int(fpga)}", commands, {"fpga": fpga})

    scheduler = out / "scheduler_logic.sv"
    text = re.search(r"^module ps_scheduler_any\b.*?^endmodule", (ROOT / SCHEDULER).read_text(), re.M | re.S)[0]
    scheduler.write_text(text + "\n")
    wrapper = out / "scheduler_proof.sv"
    wrapper.write_text("""module scheduler_proof #(parameter p_width=16, parameter p_use_lut=0)(
    input logic [p_width-1:0] i_value, output logic o_equivalent);
    logic any_set;
    ps_scheduler_any #(.p_width(p_width), .p_use_lut(p_use_lut)) u_any(
        .i_value(i_value), .o_any(any_set));
    assign o_equivalent = any_set == (|i_value);
endmodule
""")
    for width in (1, 6, 7, 16, 33, 64, 128):
        for mode in (0, 1):
            run(f"scheduler_w{width}_p{mode}", [
                f"read_slang --top scheduler_proof -Gp_width={width} -Gp_use_lut={mode} {scheduler} {wrapper}",
                "prep -top scheduler_proof -flatten", "check -assert",
                "sat -verify -prove o_equivalent 1 -show-inputs -show-outputs",
            ], {"width": width, "parameter_value": mode})
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
