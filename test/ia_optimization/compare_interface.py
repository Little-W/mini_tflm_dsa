#!/usr/bin/env python3
"""在相同输入下逐周期比较完整 IA 输出，并检查数值和分组调度。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
sys.path.insert(0, str(ROOT / "test/ia_timing"))
from rtl_reference import read_rtl_source_group
from run_interface import port_declarations


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7ddc0d8d")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--cases", nargs="+", choices=("prefetch_generic", "prefetch_ordered", "grouped32"),
                        default=["prefetch_generic", "prefetch_ordered", "grouped32"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which(args.verilator)
    if compiler is None:
        raise RuntimeError("Cannot locate Verilator")
    vendor_root = subprocess.check_output([compiler, "--getenv", "VERILATOR_ROOT"], text=True).strip()
    source_path = ROOT / "rtl/npu/loaders/ia_loader.sv"
    source = source_path.read_text()
    header_end = source.index(") (")
    header, body = source[:header_end], source[header_end:]
    # 数值驱动保持自身总线宽度；两版同时启用生产控制寄存和共享写数据级。
    overrides = dict(COUNT_WIDTH=29, p_dma_source_layout=1,
                     p_shared_write_stage=1, p_register_dma_request=1)
    for name, value in overrides.items():
        header, count = re.subn(r"(\bparameter\s+(?:int\s+unsigned|int|bit)\s+" + name +
                                r"\s*=\s*)[^,\n]+", lambda match: match[1] + str(value), header)
        if count != 1:
            raise RuntimeError("Cannot set interface comparison parameter " + name)
    current = header + body
    ports = port_declarations(current)
    parameter_names = re.findall(r"\bparameter\s+(?:int\s+unsigned|int|bit)\s+(\w+)\s*=", header)
    suffix = ["", "    // 两个完整模块共享输入，公开输出在所有周期参与比较。"]
    suffix += [f"    {kind} reference_{name} {array};"
               for direction, kind, name, array in ports if direction == "output"]
    suffix += ["    ia_loader_reference #(",
               ",\n".join(f"        .{name}({name})" for name in parameter_names),
               "    ) u_reference (",
               ",\n".join(f"        .{name}({'reference_' if direction == 'output' else ''}{name})"
                           for direction, _, name, _ in ports), "    );",
               "    always_ff @(posedge clk) begin", "        if (rst_n) begin"]
    outputs = [name for direction, _, name, _ in ports if direction == "output"]
    suffix += [f'            assert ({name} == reference_{name}) else $fatal(1, "IA output differs: {name}");'
               for name in outputs]
    suffix += ["        end", "    end", ""]
    checked = out / "ia_loader_checked.sv"
    checked.write_text(current.replace("\nendmodule", "\n".join(suffix) + "\nendmodule", 1))
    reference_files = []
    for name in ("ia_loader", "ia_loader_ctrl", "ia_loader_cache_mgr"):
        relative = f"rtl/npu/loaders/{name}.sv"
        original = read_rtl_source_group(f"{args.reference}:{relative}", cwd=ROOT, text=True)
        for module in ("ia_loader", "ia_loader_ctrl", "ia_loader_cache_mgr",
                       "ia_ordered_coordinate_equal", "ia_ordered_coordinate_same",
                       "ia_row_step_register"):
            original = re.sub(r"\b" + module + r"\b", module + "_reference", original)
        path = out / (name + "_reference.sv")
        path.write_text(original)
        reference_files.append(path)
    wrapper = out / "verilator_compare"
    wrapper.write_text("#!" + sys.executable + "\nimport os,sys\n" +
        "args=[" + repr(str(checked)) + " if value==" + repr(str(source_path)) +
        " else value for value in sys.argv[1:]]\n" +
        "if '--getenv' not in args and '--version' not in args:\n" +
        "    for i,value in enumerate(args):\n" +
        "        if value=='-CFLAGS': args[i+1]=args[i+1].replace('-std=c++17','-std=c++20')+' -Wno-bool-operation'\n" +
        "        if value=='-MAKEFLAGS': args[i+1]+=' VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E'\n" +
        "    args += ['-CFLAGS'," + repr("-isystem " + str(Path(vendor_root) / "include") +
        " -Wno-sign-compare -Wno-unused-variable -Wno-unused-parameter -Wno-unused-but-set-variable") + "]+" +
        repr(list(map(str, reference_files))) + "\n" +
        "os.execv(" + repr(compiler) + ",[" + repr(compiler) + "]+args)\n")
    wrapper.chmod(0o755)
    sources = sorted((ROOT / "rtl/npu/loaders").glob("ia_*.sv"))
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    summary = dict(passed=False, reference_commit=subprocess.check_output(
        ["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=hashes, default_parameter_overrides=overrides,
        compared_outputs=outputs, generated_sha256={path.name: digest(path) for path in
        [checked, wrapper, *reference_files]}, runs=[])
    for label in args.cases:
        folder = out / label
        command = [sys.executable, str(ROOT / "test/ia_compact" /
                   ("run.py" if label == "grouped32" else "run_prefetch.py")),
                   "--out", str(folder), "--verilator", str(wrapper)]
        if label == "prefetch_ordered":
            command.append("--ordered-job")
        elif label == "grouped32":
            command += ["--only", "loader", "--loader-cache-blocks", "32"]
        with (out / (label + ".log")).open("w") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = json.loads((folder / "summary.json").read_text())
        if label == "grouped32":
            result = result["tests"]["loader"]
        record = {key: result.get(key) for key in ("passed", "cycles", "cases", "commands", "value_checks")}
        record.update(case=label, summary=str(folder / "summary.json"))
        summary["runs"].append(record)
        summary["passed"] = all(row["passed"] for row in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not record["passed"]:
            raise RuntimeError("IA interface comparison did not complete")
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError("RTL changed during interface comparison")


if __name__ == "__main__":
    main()
