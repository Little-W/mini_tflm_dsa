#!/usr/bin/env python3
"""证明 FIFO 银行选择与全部公开输出及存储端口逐周期等价。"""
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
from rtl_reference import read_rtl_source


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed_source(source: str) -> str:
    spec = importlib.util.spec_from_file_location(
        "fifo_count_ports", ROOT / "test/fifo_count_storage/run_formal.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    text = helper.expose_memory_ports(source)
    text = text.replace("output wire [BANKS*$clog2(VLEN+1)-1:0] formal_bank_counts",
                        "output wire [BANKS-1:0] formal_bank_nonempty,\n"
                        "    output wire [BANKS*$clog2(VLEN+1)-1:0] formal_bank_counts")
    relation = """  for (genvar bank=0; bank<BANKS; bank++) begin : g_count_relation
    if (p_count_storage) begin : g_memory
      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] =
          bank_ready[bank] ? g_count_memory.u_bank_count.mem[bank] : '0;
      assign formal_bank_nonempty[bank] = NONEMPTY;
    end else begin : g_registers
      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] =
          g_count_registers.bank_count[bank];
      assign formal_bank_nonempty[bank] = 1'b0;
    end
  end
"""
    expression = "bank_ready[bank] && (g_count_memory.u_bank_count.mem[bank] != '0)"
    marker = "  logic co_group_last_result;"
    if text.count(marker) != 1:
        raise ValueError("无法定位 FIFO 银行状态比较的位置")
    return text.replace(marker, relation.replace("NONEMPTY", expression) + marker)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="cedf4ed33661a53c8194eca1d484cdc2279d7549")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--precomputed-watermark", type=int, choices=(0,1), default=1)
    parser.add_argument("--generic", action="store_true")
    parser.add_argument("--profile", help="仅运行指定的 v16_n8_b32_c1 等参数组合")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.source_root / SOURCE
    current = source_path.read_text()
    reference = (args.reference_file.read_text() if args.reference_file else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    helper_marker = "module vec_s8_fifo_row_ram"
    if current[current.index(helper_marker):] != reference[reference.index(helper_marker):]:
        raise ValueError("数据存储实现需要独立检查")
    sources = {}
    for label, text in (("reference", reference), ("current", current)):
        sources[label] = out / f"{label}.sv"
        sources[label].write_text(observed_source(text))
    common = [ROOT / "rtl/common/regfile.v", ROOT / "rtl/common/parallel_prefix_add.sv"]
    hashes = {str(p): digest(p) for p in [source_path, *common]}
    report = dict(reference=args.reference, source_sha256=hashes,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  functional_inputs_constrained=False, initial_reset_cycle=1,
                  subsequent_reset_unconstrained=True, data_ram_inputs_constrained=False,
                  data_storage_implementation_identical=True,
                  precomputed_watermark=args.precomputed_watermark, fpga=not args.generic,
                  compared="全部公开输出、数据存储地址和使能、存储写数据、有效银行计数及银行非空状态",
                  method="保留完整时序逻辑，同时比较公开输出、共同寄存状态和非空关系，执行复位后的时序归纳证明",
                  runs=[])
    profiles = [(16,1,64,1), (16,2,32,1), (16,3,64,1), (16,8,32,1),
                (16,16,64,1), (16,32,32,1), (16,32,64,1), (16,64,64,1), (16,32,64,0), (8,8,32,0)]
    for vlen, banks, bus, cyclic in profiles:
        name = f"v{vlen}_n{banks}_b{bus}_c{cyclic}"
        if args.profile and args.profile != name:
            continue
        folder = out / (name + f"_w{args.precomputed_watermark}")
        folder.mkdir(exist_ok=True)
        commands = []
        for label, path in sources.items():
            commands += [
                f"read_slang --top vec_s8_to_fifo_full -GVLEN={vlen} -GBANKS={banks} "
                f"-GBUS_WIDTH={bus} -Gp_cyclic_storage={cyclic} "
                f"-Gp_precomputed_watermark={args.precomputed_watermark} -D SYNTHESIS=1 " +
                ("-D ASIC_SYNTHESIS " if args.generic else "-D XILINX_FPGA ") +
                shlex.join(map(str, [path, *common])),
                "prep -top vec_s8_to_fifo_full -flatten", "async2sync", "memory_map", "opt -full",
                f"rename vec_s8_to_fifo_full {label}", f"design -stash {label}",
            ]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     # 共同状态作为待证明的输出，全部时序逻辑保持连接。
                     # 行数 RAM 无复位；它的有效内容由 formal_bank_counts 比较。
                     "expose -dff -shared reference/w:* current/w:* "
                     "reference/w:g_count_memory.* %d current/w:g_count_memory.* %d",
                     "miter -equiv -make_outcmp -flatten reference current miter",
                     "hierarchy -top miter", "opt_clean",
                     "sat -seq 2 -tempinduct -maxsteps 5 -set-at 1 in_rst_n 0 "
                     "-prove trigger 0 -verify"]
        script, log = folder / "run.ys", folder / "formal.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=600)
        content = log.read_text()
        if "Induction step proven: SUCCESS!" not in content:
            raise RuntimeError(f"等价检查未完成：{log}")
        match = re.findall(r"\[induction step (\d+)\]", content)
        item = dict(vlen=vlen, banks=banks, bus_width=bus, cyclic=cyclic,
                    induction_steps=int(match[-1]), passed=True, log_sha256=digest(log))
        report["runs"].append(item)
        print(json.dumps(item), flush=True)
    if hashes != {str(p): digest(p) for p in [source_path, *common]}:
        raise RuntimeError("验证期间源码发生变化")
    if not report["runs"]:
        raise ValueError("指定的参数组合不存在")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
