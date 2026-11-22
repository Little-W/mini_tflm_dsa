#!/usr/bin/env python3
"""证明 FIFO 末拍保存状态与公开输出、存储端口的逐周期等价性。"""
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

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/vec_s8_to_fifo.sv")
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source, read_current_source as read_rtl_text


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed_source(source: str) -> str:
    spec = importlib.util.spec_from_file_location(
        "fifo_pointer_formal", ROOT / "test/fifo_write_pointer/run_formal.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    text = helper.observed_source(source)
    marker = "  wire output_fire ="
    relation = "  (* keep *) wire [COUNT_WIDTH-1:0] formal_last_beat_index = last_beat_idx_cur;\n"
    if text.count(marker) != 1:
        raise ValueError("无法定位 FIFO 末拍状态比较的位置")
    return text.replace(marker, relation + marker)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="415a70a")
    parser.add_argument("--reference-file", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = read_rtl_text(ROOT / SOURCE)
    reference = (read_rtl_text(args.reference_file) if args.reference_file else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    sources = {}
    for label, text in (("reference", reference), ("current", current)):
        sources[label] = out / f"{label}.sv"
        sources[label].write_text(observed_source(text))
    common = [ROOT / "rtl/common/regfile.v", ROOT / "rtl/common/parallel_prefix_add.sv"]
    hashes = {str(p): digest(p) for p in [ROOT / SOURCE, *common]}
    report = dict(reference=args.reference, source_sha256=hashes,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  inputs_constrained=False, data_ram_inputs_constrained=False,
                  compared="全部公开输出、数据存储地址和使能、存储写数据、有效银行计数及末拍保存状态",
                  method="比较末拍寄存值与原始表达式，并逐状态归纳证明完整模块的等价性",
                  runs=[])
    profiles = [(16,1,64,1), (16,2,32,1), (16,3,64,1), (16,8,32,1),
                (16,16,64,1), (16,32,64,1), (16,64,64,1), (16,32,64,0), (8,8,32,0)]
    for vlen, banks, bus, cyclic in profiles:
        folder = out / f"v{vlen}_n{banks}_b{bus}_c{cyclic}"
        folder.mkdir(exist_ok=True)
        commands = []
        for label, path in sources.items():
            commands += [
                f"read_slang --top vec_s8_to_fifo_full -GVLEN={vlen} -GBANKS={banks} "
                f"-GBUS_WIDTH={bus} -Gp_cyclic_storage={cyclic} -D XILINX_FPGA " +
                shlex.join(map(str, [path, *common])),
                "prep -top vec_s8_to_fifo_full -flatten", "async2sync", "memory_map", "opt -full",
                f"rename vec_s8_to_fifo_full {label}", f"design -stash {label}",
            ]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "opt_merge", "equiv_simple -short -seq 1", "opt_clean",
                     "equiv_induct -seq 5", "equiv_simple -seq 1", "equiv_status -assert"]
        script, log = folder / "run.ys", folder / "formal.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=600)
        content = read_rtl_text(log)
        if "Equivalence successfully proven" not in content:
            raise RuntimeError(f"等价检查未完成：{log}")
        match = re.search(r"Of those cells (\d+) are proven and 0 are unproven", content)
        item = dict(vlen=vlen, banks=banks, bus_width=bus, cyclic=cyclic,
                    equivalent_bits=int(match[1]), passed=True, log_sha256=digest(log))
        report["runs"].append(item)
        print(json.dumps(item), flush=True)
    if hashes != {str(p): digest(p) for p in [ROOT / SOURCE, *common]}:
        raise RuntimeError("验证期间源码发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
