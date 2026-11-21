#!/usr/bin/env python3
"""比较 IA 加载器优化前后的完整时序状态及公开输出。"""
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
CASES = {
    "ctrl3": {"top": "ia_loader_ctrl", "options": ["-GSIZE=3", "-GBUS_WIDTH=32", "-GCACHE_BLOCKS=4"]},
    "ctrl16": {"top": "ia_loader_ctrl", "options": ["-GSIZE=16", "-GBUS_WIDTH=64", "-GCACHE_BLOCKS=32"]},
    "ctrl32": {"top": "ia_loader_ctrl", "options": ["-GSIZE=32", "-GBUS_WIDTH=64", "-GCACHE_BLOCKS=32"]},
    "loader_ordered": {"top": "ia_loader", "options": ["-GSIZE=16", "-GBUS_WIDTH=64", "-GCACHE_BLOCKS=32", "-GEXTERNAL_RAM=1", "-GORDERED_JOB=1"]},
    "loader_generic": {"top": "ia_loader", "options": ["-GSIZE=16", "-GBUS_WIDTH=32", "-GCACHE_BLOCKS=4", "-GEXTERNAL_RAM=1", "-GORDERED_JOB=0"]},
    "loader_local3": {"top": "ia_loader", "options": ["-GSIZE=3", "-GBUS_WIDTH=32", "-GCACHE_BLOCKS=4", "-GEXTERNAL_RAM=0", "-GORDERED_JOB=1"]},
    "loader_ordered29": {"top": "ia_loader", "options": ["-GSIZE=16", "-GBUS_WIDTH=64", "-GCACHE_BLOCKS=32", "-GCOUNT_WIDTH=29", "-GEXTERNAL_RAM=1", "-GORDERED_JOB=1"]},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="aa2ef9a3")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = ["rtl/npu/loaders/ia_loader_ctrl.sv", "rtl/npu/loaders/ia_loader.sv",
             "rtl/npu/loaders/ia_loader_cache_mgr.sv"]
    source_root = args.source_root.resolve()
    current_loader = (source_root / paths[1]).read_text()
    current_ctrl = (source_root / paths[0]).read_text()
    snapshots = {}
    for label in ("reference", "current"):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for name in paths:
            path = folder / Path(name).name
            source = ((args.reference_root / name).read_text() if args.reference_root else
                      read_rtl_source(args.reference_rev + ":" + name, cwd=ROOT, text=True)) if label == "reference" else (source_root / name).read_text()
            if (label == "reference" and name.endswith("/ia_loader_ctrl.sv") and
                    re.search(r"\bcfg_packed_k_tiles\b", current_ctrl) and
                    not re.search(r"\bcfg_packed_k_tiles\b", source)):
                # 默认参数不使用提前计算端口；增加同名闲置输入以统一形式比较端口。
                source = source.replace("    // ---- 来自 top：配置参数（已锁存）----",
                                        "    input logic [REG_WIDTH-1:0] cfg_packed_k_tiles = '0,\n\n"
                                        "    // ---- 来自 top：配置参数（已锁存）----", 1)
            if (label == "reference" and name.endswith("/ia_loader.sv") and
                    not re.search(r"\bprefetch_previous_q0\b", source)):
                # 该等价点描述随预取描述符保存的前一分块坐标。
                source = source.replace("\nendmodule", "\n    (* keep *) wire [REG_WIDTH-1:0] prefetch_previous_q0 =\n"
                                        "        prefetch_descriptor.q0 - REG_WIDTH'(SIZE);\nendmodule", 1)
            if (label == "reference" and name.endswith("/ia_loader.sv") and
                    re.search(r"\blogic\s+\[REG_WIDTH-1:0\]\s+demand_p0_q,\s*demand_q0_q;", current_loader) and
                    not re.search(r"\bdemand_p0_q\b", source)):
                # 组合等价点使用原始描述符，直接证明新保存坐标与原始表达式的关系。
                source = source.replace("\nendmodule", "\n    (* keep *) wire [REG_WIDTH-1:0] demand_p0_q =\n"
                                        "        demand_descriptor.p0;\n"
                                        "    (* keep *) wire [REG_WIDTH-1:0] demand_q0_q =\n"
                                        "        demand_descriptor.q0;\nendmodule", 1)
            if (label == "reference" and name.endswith("/ia_loader.sv") and
                    re.search(r"\bpacked_k_tiles_q\b", current_loader) and
                    not re.search(r"\bpacked_k_tiles_q\b", source)):
                # 用已保存的原配置表达式检查提前计算值，包括忙碌时配置接收。
                source = source.replace("\nendmodule", "\n    wire [REG_WIDTH-1:0] formal_packed_reduction =\n"
                                        "        (global_reduction_q != 0) ? global_reduction_q : cfg_n;\n"
                                        "    (* keep *) wire [REG_WIDTH-1:0] packed_k_tiles_q =\n"
                                        "        (formal_packed_reduction >> LOG2_SIZE) +\n"
                                        "        REG_WIDTH'((formal_packed_reduction & REG_WIDTH'(SIZE - 1)) != 0);\nendmodule", 1)
            path.write_text(source)
            snapshots[label].append(path)
    common = sorted(path for path in (source_root / "rtl/common").rglob("*") if path.suffix in (".v", ".sv"))
    common.append(source_root / "rtl/npu/compute/select_add.sv")
    summary = {
        "reference_rev": args.reference_rev,
        "method": "Yosys complete-state equivalence with simple SAT and temporal induction",
        "source_root": str(source_root),
        "reference_root": str(args.reference_root.resolve()) if args.reference_root else None,
        "source_sha256": {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in paths},
        "common_source_sha256": {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in common},
        "runs": [],
    }
    for label in args.cases:
        case = CASES[label]
        folder = out / label
        folder.mkdir(exist_ok=True)
        top = case["top"]
        commands = []
        for variant in ("reference", "current"):
            sources = snapshots[variant] + common
            commands += ["read_slang --top " + top + " " + " ".join(case["options"]) + " " +
                         " ".join(shlex.quote(str(path)) for path in sources),
                         "prep -top " + top + " -flatten", "memory_map", "async2sync", "opt_clean",
                         "rename " + top + " " + variant, "design -stash " + variant]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 1", "equiv_status -assert"]
        script = folder / "run.ys"
        script.write_text("\n".join(commands) + "\n")
        with (folder / "formal.log").open("w") as stream:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                                     "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        log = (folder / "formal.log").read_text()
        proved = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log)
        passed = result.returncode == 0 and "Equivalence successfully proven" in log
        record = {"case": label, "top": top, "options": case["options"], "passed": passed,
                  "equivalent_bits": int(proved.group(1)) if proved else None}
        summary["runs"].append(record)
        summary["passed"] = all(item["passed"] for item in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not passed:
            print(log[-12000:])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
