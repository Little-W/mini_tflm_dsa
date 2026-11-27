#!/usr/bin/env python3
"""证明每帧容量预计算与完整帧存储的状态、公开输出逐周期等价。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/ps_compact/ps_frame_store.sv")
REFERENCE = "9e3e5d6a6f47befe6c86aceacad7999923206458"
CASES = runpy.run_path(str(ROOT / "test/ps_frame_ready/run_full.py"))["CASES"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe_capacity(source: str) -> str:
    """把容量表示作为附加输出共同证明，不添加输入或状态假设。"""
    final_port = "    output reg  replay_valid /* 当前返回的部分和回放行有效 */"
    if source.count(final_port) != 1:
        raise ValueError("帧存储端口结构不匹配")
    source = source.replace(final_port, final_port + ",\n"
        "    output logic [FRAME_COUNT-1:0][63:0] capacity_relation, // 各帧可用容量状态\n"
        "    output logic [FRAME_COUNT-1:0] capacity_positive_bounded // 非负容量处于存储池有效行宽\n")
    if "pool_capacity_rows_q" in source:
        value = "(p_capacity_rows_width+1)'({1'b0,pool_capacity_rows_q} - " \
            "(p_capacity_rows_width+1)'((RAW_LINEAR_BITS-2)'(frame) * " \
            "(RAW_LINEAR_BITS-2)'(directory_stride_q)))"
    else:
        value = "frame_available_rows_q[frame]"
    bound = "1'b1" if "pool_capacity_rows_q" in source else (
        "frame_available_rows_q[frame][p_capacity_rows_width] || "
        "((frame_available_rows_q[frame][p_capacity_rows_width-1:0] >> (p_pool_words_width-2)) == '0)")
    observer = f"""
    // 配置表示与各帧保存的容量均保持完整模宽，关系和公开输出一同验证。
    for (genvar frame=0;frame<FRAME_COUNT;frame++) begin : g_capacity_relation
        assign capacity_relation[frame] = 64'({value});
        assign capacity_positive_bounded[frame] = {bound};
    end
"""
    return source.replace("\nendmodule", observer + "\nendmodule", 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--rtl", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    parser.add_argument("--modes", nargs="+", choices=("generic", "fpga"), default=["generic", "fpga"])
    parser.add_argument("--skip-four-state", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.rtl.resolve()
    source = source_path.read_text()
    original = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"],
                                       cwd=ROOT, text=True)
    resolver = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    originals = resolver([source_path], ROOT)
    def source_hashes():
        return {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path):
                digest(path) for path in originals}
    hashes = source_hashes()
    reference, current = out / "reference.sv", out / "current.sv"
    reference.write_text(observe_capacity(original))
    current.write_text(observe_capacity(source))
    report = {
        "passed": False, "reference": args.reference, "input_constraints": None,
        "all_public_outputs_compared_each_cycle": True,
        "capacity_relation_proven_with_outputs": True,
        "nonnegative_capacity_bound_proven_with_outputs": True,
        "source_sha256": hashes,
        "reference_sha256": hashlib.sha256(original.encode()).hexdigest(), "runs": [],
    }
    for mode in args.modes:
        flags = ["-USYNTHESIS", "-UXILINX_FPGA"] if mode == "generic" else ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"]
        for name in args.cases:
            top, _, parameters = CASES[name]
            folder = out / f"{mode}_{name}"
            folder.mkdir(exist_ok=True)
            commands = []
            for label, path in (("reference", reference), ("current", current)):
                sources = resolver([path], ROOT)
                commands += [shlex.join(["read_slang", "--top", top, *flags,
                    *[f"-G{key}={value}" for key, value in parameters.items()], *map(str, sources)]),
                    f"prep -top {top} -flatten", "memory_map", "async2sync", "opt_clean",
                    f"rename {top} {label}", f"design -stash {label}"]
            commands += ["design -copy-from reference -as reference reference",
                "design -copy-from current -as current current", "equiv_make reference current equivalent",
                "hierarchy -top equivalent", "equiv_simple -short -seq 1", "opt_clean",
                "equiv_induct -seq 2", "equiv_status -assert"]
            script, log = folder / "proof.ys", folder / "proof.log"
            script.write_text("\n".join(commands) + "\n")
            with log.open("w") as stream:
                result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], cwd=ROOT, stdout=stream,
                    stderr=subprocess.STDOUT, timeout=900)
            text = log.read_text()
            match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
            if result.returncode or match is None or int(match[2]) or "Equivalence successfully proven" not in text:
                raise RuntimeError(f"帧存储完整等价检查未完成：{log}")
            row = {"mode": mode, "case": name, "parameters": parameters,
                   "equivalent_bits": int(match[1]), "passed": True,
                   "script_sha256": digest(script), "log_sha256": digest(log)}
            report["runs"].append(row)
            print(json.dumps(row), flush=True)
            (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not args.skip_four_state:
        folder = out / "four_state"
        folder.mkdir(exist_ok=True)
        comparison = runpy.run_path(str(ROOT / "test/ps_request_ready/run_four_state.py"))
        current_model, reference_model, bench = (folder / name for name in ("current.sv", "reference.sv", "tb.sv"))
        current_model.write_text(comparison["model"](source, "current"))
        reference_model.write_text(comparison["model"](original, "reference"))
        bench.write_text(comparison["bench"](source, 8192))
        simulation_sources = resolver([current_model, reference_model, bench], ROOT)
        records = []
        for mode in ("generic", "fpga"):
            flags = [] if mode == "generic" else ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"]
            binary = folder / (mode + ".vvp")
            with (folder / (mode + "_compile.log")).open("w") as stream:
                subprocess.run(["iverilog", "-g2012", "-s", "tb", *flags, "-o", str(binary),
                    *map(str, simulation_sources)], cwd=ROOT, stdout=stream,
                    stderr=subprocess.STDOUT, check=True, timeout=360)
            result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, check=True, timeout=360)
            simulation_log = folder / (mode + "_run.log")
            simulation_log.write_text(result.stdout + result.stderr)
            if "PS_REQUEST_FOUR_STATE_ALL_PASS" not in result.stdout or \
                    result.stdout.count("PS_REQUEST_FOUR_STATE_PROFILE_PASS") != len(CASES):
                raise RuntimeError("四态比较未完成")
            records.append({"mode": mode, "passed": True, "profiles": list(CASES),
                            "cycles_per_profile": 8192, "log_sha256": digest(simulation_log)})
            print(result.stdout, flush=True)
        report["four_state"] = {"passed": True, "runs": records,
                                "all_public_outputs_compared_each_cycle": True}
    if hashes != source_hashes():
        raise RuntimeError("检查期间 RTL 文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
