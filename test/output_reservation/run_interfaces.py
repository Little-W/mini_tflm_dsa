#!/usr/bin/env python3
"""证明预计算阈值参数在三种 FIFO 实现中保持全部输出和状态周期。"""
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
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = [ROOT / "rtl/npu/writeback/vec_s8_to_fifo.sv",
             ROOT / "rtl/npu/writeback/vec_s16_to_fifo.sv",
             ROOT / "rtl/common/regfile.v", ROOT / "rtl/common/parallel_prefix_add.sv"]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in files}
    spec = importlib.util.spec_from_file_location(
        "fifo_memory_ports", ROOT / "test/fifo_count_storage/run_formal.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    s8 = read_rtl_text(files[0])
    s16 = read_rtl_text(files[1])
    profiles = [("vec_s8_to_fifo_full", 16, 32, 64, 1),
                ("vec_s8_to_fifo_full", 16, 3, 32, 1),
                ("vec_s8_to_fifo_full", 8, 4, 32, 0),
                ("vec_s8_to_fifo_linear", 16, 8, 64, 0),
                ("vec_s16_to_fifo", 16, 4, 64, 0)]
    report = {"source_sha256": hashes, "inputs_constrained": False,
              "comparison": "全部公开输出和共同状态；完整 FIFO 存储端口与数据", "runs": []}
    for top, lanes, banks, bus, cyclic in profiles:
        folder = out / f"{top}_v{lanes}_n{banks}_b{bus}_c{cyclic}"
        folder.mkdir(exist_ok=True)
        text = helper.expose_memory_ports(s8) if top == "vec_s8_to_fifo_full" else s8
        if top == "vec_s16_to_fifo":
            text += "\n" + s16
        module = re.search(r"module " + top + r"\b.*?endmodule", text, re.S)[0]
        declaration = re.search(r"    input  wire (?:logic )?\[31:0\]\s+i_ready_bank_threshold,\n", module)
        if not declaration:
            raise ValueError("无法定位 FIFO 阈值端口")
        transformed = module.replace(declaration[0], "")
        delimiter = transformed.index("\n);") + len("\n);")
        transformed = transformed[:delimiter] + """
    // 阈值关系已在顶层实际配置寄存器上单独进行无界证明。
    wire [31:0] i_ready_bank_threshold = reserve_banks == 32'd0 ? 32'(BANKS-1) :
        reserve_banks >= 32'(BANKS) ? 32'd0 : 32'(BANKS)-reserve_banks;
""" + transformed[delimiter:]
        text = text.replace(module, transformed)
        source = folder / "fifo.sv"
        source.write_text(text)
        options = f"-GVLEN={lanes} -GBANKS={banks} -GBUS_WIDTH={bus}"
        if top == "vec_s8_to_fifo_full":
            options += f" -Gp_cyclic_storage={cyclic}"
        commands = []
        for label, enabled in (("reference", 0), ("current", 1)):
            commands += [
                f"read_slang --top {top} {options} -Gp_precomputed_watermark={enabled} " +
                shlex.join(map(str, [source, *files[2:]])),
                f"prep -top {top} -flatten", "async2sync", "memory_map", "opt -full",
                f"rename {top} {label}", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "opt_merge", "equiv_simple -short -seq 1", "opt_clean",
                     "equiv_induct -seq 3", "equiv_status -assert"]
        script = folder / "run.ys"
        script.write_text("\n".join(commands) + "\n")
        log = folder / "formal.log"
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=300)
        result = read_rtl_text(log)
        match = re.search(r"Of those cells (\d+) are proven and 0 are unproven", result)
        if not match or "Equivalence successfully proven" not in result:
            raise RuntimeError("FIFO 完整状态证明未完成")
        row = {"top": top, "vlen": lanes, "banks": banks, "bus_width": bus,
               "cyclic_storage": cyclic, "equivalent_bits": int(match[1]),
               "passed": True, "log_sha256": digest(log)}
        report["runs"].append(row)
        print(json.dumps(row), flush=True)
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in files}:
        raise RuntimeError("证明期间 RTL 源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
