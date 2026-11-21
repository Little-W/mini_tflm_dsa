#!/usr/bin/env python3
"""比较 AXI-Lite 寄存器读回逻辑，并验证公开接口的逐周期等价性。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RTL = "rtl/axi_top/npu_axil_reg_if.sv"
PACKAGE = "rtl/npu/conv/conv_im2col_pkg.sv"
DEFAULT_REFERENCE = "4dee27ff"
PARAMETERS = {
    "AXI_DATA_BITS": 64,
    "CONV_IS_CAPABLE": 1,
    "VECTOR_ENGINE_CAPABLE": 1,
    "VECTOR_PE_COUNT": 16,
    "MATRIX_S16_BANKS": 4,
    "PS_CAPS": 0x01100037,
    "PS_POOL_BYTES": 49152,
    "IA_CACHE_BYTES": 2048,
    "SHARED_TOTAL_BYTES": 57344,
    "SHARED_BANK_BYTES": 8192,
    "SHARED_IA_BANK_MASK": 6,
}
OPTIONS = [f"-G{name}={value}" for name, value in PARAMETERS.items()]
RESOURCE_KEYS = (
    "lut_cells", "flip_flops", "ramb36", "ramb18", "dsp",
    "longest_combinational_path_cells", "longest_register_path_cells",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(command: list[str], log: Path, timeout: int) -> None:
    with log.open("w", encoding="utf-8") as stream:
        stream.write("COMMAND: " + json.dumps(command, ensure_ascii=False) + "\n")
        stream.flush()
        result = subprocess.run(
            command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
    if result.returncode:
        raise RuntimeError(f"命令未通过，返回值 {result.returncode}；日志：{log}")


def formal_worker(manifest_path: Path) -> None:
    """对两份完整模块执行等价检查，逐项证明公开端口及匹配内部信号。"""
    from pyosys import libyosys as yosys

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = Path(manifest["source_root"])
    options = " ".join(shlex.quote(value) for value in manifest["options"])
    design = yosys.Design()
    for label in ("reference", "current"):
        package = source_root / label / "conv_im2col_pkg.sv"
        source = source_root / label / "npu_axil_reg_if.sv"
        yosys.run_pass(
            f"read_slang --top npu_axil_reg_if {options} "
            f"{shlex.quote(str(package))} {shlex.quote(str(source))}", design,
        )
        yosys.run_pass("proc; memory; async2sync; opt_clean", design)
        yosys.run_pass(f"design -stash {label}", design)
    yosys.run_pass("design -copy-from reference -as reference npu_axil_reg_if", design)
    yosys.run_pass("design -copy-from current -as current npu_axil_reg_if", design)
    yosys.run_pass("equiv_make reference current equiv", design)
    yosys.run_pass("hierarchy -top equiv", design)
    yosys.run_pass("equiv_simple -seq 2", design)
    yosys.run_pass("equiv_induct -seq 4", design)
    yosys.run_pass("equiv_status -assert", design)
    print("AXIL_READ_MUX_EQUIVALENCE_PASS", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default=DEFAULT_REFERENCE, help="用于比较的 Git 提交，默认 4dee27ff")
    parser.add_argument("--out", type=Path, default=ROOT / "build/axil_read_mux")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--transaction-out", type=Path, help="原有 23 配置事务测试的输出目录")
    parser.add_argument("--skip-transactions", action="store_true", help="执行形式等价、四态检查与模块面积比较")
    parser.add_argument("--formal-worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.formal_worker is not None:
        formal_worker(args.formal_worker.resolve())
        return 0

    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = {"passed": False, "run_time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}
    write_json(output / "summary.json", summary)
    reference = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{args.baseline_ref}^{{commit}}"],
        cwd=ROOT, text=True,
    ).strip()

    # 每次从指定提交读取参考文件，并保存当前文件的独立副本。
    source_root = output / "sources"
    (source_root / "rtl/common").mkdir(parents=True, exist_ok=True)
    source_hashes = {}
    for label in ("reference", "current"):
        folder = source_root / label
        folder.mkdir(exist_ok=True)
        source_hashes[label] = {}
        for source_name in (PACKAGE, RTL):
            data = subprocess.check_output(["git", "show", f"{reference}:{source_name}"], cwd=ROOT) \
                if label == "reference" else (ROOT / source_name).read_bytes()
            destination = folder / Path(source_name).name
            destination.write_bytes(data)
            source_hashes[label][source_name] = sha256(destination)

    manifest = {
        "reference_commit": reference,
        "source_root": str(source_root),
        "source_sha256": source_hashes,
        "parameters": PARAMETERS,
        "options": OPTIONS,
    }
    write_json(output / "manifest.json", manifest)
    run_command(
        [sys.executable, str(Path(__file__).resolve()), "--formal-worker", str(output / "manifest.json")],
        output / "equivalence.log", 300,
    )
    formal_log = (output / "equivalence.log").read_text(encoding="utf-8")
    proven = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", formal_log)
    if "AXIL_READ_MUX_EQUIVALENCE_PASS" not in formal_log or proven is None or int(proven[2]) != 0:
        raise RuntimeError("等价检查未返回完整的通过结果")

    # 四态检查直接读取当前选择逻辑，覆盖全部地址以及未知值和高阻值。
    run_command(
        [sys.executable, str(HERE / "run_four_state.py"), "--baseline-ref", reference,
         "--source", str(source_root / "current/npu_axil_reg_if.sv"),
         "--iverilog", args.iverilog, "--vvp", args.vvp, "--out", str(output / "four_state")],
        output / "four_state.log", 120,
    )
    four_state = json.loads((output / "four_state/summary.json").read_text(encoding="utf-8"))
    if not four_state.get("passed") or four_state["source_sha256"] != source_hashes["current"][RTL]:
        raise RuntimeError("四态检查结果与当前源码不匹配")

    # 两份源码使用同一组参数和同一综合流程，生成独立的资源统计。
    cases = {
        label: {
            "top": "npu_axil_reg_if",
            "options": OPTIONS,
            "sources": [f"{label}/conv_im2col_pkg.sv", f"{label}/npu_axil_reg_if.sv"],
            "configuration": "32 位 AXI-Lite 寄存器接口，64 位 NPU 总线，七个 8 KiB 共享存储块",
        }
        for label in ("reference", "current")
    }
    write_json(output / "cases.json", cases)
    synthesis_entry = ROOT / "scripts/fpga/open_fpga_synth.py"
    run_command(
        [sys.executable, str(synthesis_entry), "--source-root", str(source_root),
         "--case-config", str(output / "cases.json"), "--cases", "reference", "current",
         "--out", str(output / "synthesis")],
        output / "synthesis.log", 600,
    )
    synthesis = json.loads((output / "synthesis/summary.json").read_text(encoding="utf-8"))
    resources = {label: {key: synthesis["cases"][label][key] for key in RESOURCE_KEYS}
                 for label in ("reference", "current")}
    resources_within_reference = all(
        resources["current"][key] <= resources["reference"][key]
        for key in ("lut_cells", "longest_combinational_path_cells", "longest_register_path_cells")
    )

    transactions = {"executed": False}
    if not args.skip_transactions:
        transaction_output = args.transaction_out.resolve() if args.transaction_out else output / "transactions"
        run_command(
            [sys.executable, str(ROOT / "test/capacity/run_shared_bank_registers.py"),
             "--verilator", args.verilator, "--out", str(transaction_output)],
            output / "transactions.log", 1200,
        )
        result = json.loads((transaction_output / "summary.json").read_text(encoding="utf-8"))
        if not result.get("passed") or result["source_sha256"][RTL] != source_hashes["current"][RTL]:
            raise RuntimeError("事务测试结果与当前源码不匹配")
        transactions = {"executed": True, **{key: result[key] for key in (
            "passed", "profiles", "register_reads", "register_writes", "rejected_writes",
            "checks", "undefined_behavior_sanitizer", "sources_unchanged",
        )}}

    sources_unchanged = source_hashes["current"] == {name: sha256(ROOT / name) for name in (PACKAGE, RTL)}
    summary.update({
        "passed": sources_unchanged and resources_within_reference,
        "reference_commit": reference,
        "source_sha256": source_hashes,
        "runner_sha256": sha256(Path(__file__).resolve()),
        "parameters": PARAMETERS,
        "sources_unchanged": sources_unchanged,
        "equivalence": {"passed": True, "proven_points": int(proven[1]), "unproven_points": 0,
                        "method": "read_slang; proc; memory; async2sync; equiv_make; equiv_simple -seq 2; equiv_induct -seq 4; equiv_status -assert",
                        "log_sha256": sha256(output / "equivalence.log")},
        "synthesis": {"tool": synthesis["tool"], "method": synthesis["method"],
                      "resources": resources, "resources_within_reference": resources_within_reference},
        "four_state": {key: four_state[key] for key in (
            "passed", "profiles", "address_states", "data_states", "decoded_addresses",
            "unchanged_word_assignments", "bank_masks", "bank_samples", "sources_unchanged",
            "runner_sha256", "source_sha256", "reference_sha256",
        )},
        "transactions": transactions,
    })
    write_json(output / "summary.json", summary)
    print(json.dumps({"passed": summary["passed"], "reference_luts": resources["reference"]["lut_cells"],
                      "current_luts": resources["current"]["lut_cells"],
                      "equivalence_points": int(proven[1]), "transactions": transactions}, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
