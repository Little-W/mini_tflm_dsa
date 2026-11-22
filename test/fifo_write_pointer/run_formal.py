#!/usr/bin/env python3
"""证明 FIFO 独热写指针与全部公开输出、存储端口的逐周期等价性。"""
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


def pointer_stage(source: str) -> str:
    return re.search(r"  always_ff @\(posedge clk\) begin\n"
                     r"    if \(!rst_n\) write_bank_mask_q.*?\n  end", source, re.S)[0]


def pointer_model(source: str, reference: str) -> str:
    source = source[:source.index("module vec_s8_to_fifo_linear")]
    reference = reference[:reference.index("module vec_s8_to_fifo_linear")]
    selection = source[source.index("  logic [BANKS-1:0] next_write_bank_mask;"):
                       source.index("`ifdef NPU_SIM_ASSERT", source.index("  logic [BANKS-1:0] next_write_bank_mask;"))]
    function = re.search(r"  function automatic \[BANK_WIDTH-1:0\] next_bank.*?endfunction", source, re.S)[0]
    reset, advance = re.findall(r"\bwrite_bank\s*<=\s*([^;]+);", source)
    ref_reset, ref_advance = re.findall(r"\bwrite_bank\s*<=\s*([^;]+);", reference)
    ref_advance = ref_advance.replace("write_bank", "reference_bank")
    return f"""module pointer_formal #(parameter integer BANKS=32,
    parameter integer BANK_WIDTH=(BANKS<=1)?1:$clog2(BANKS))(
    input logic clk,rst_n,finish_write_bank,
    input logic [BANKS-1:0] bank_ready,
    output logic o_equal
);
    logic [BANK_WIDTH-1:0] write_bank,reference_bank;
    logic [BANKS-1:0] write_bank_mask_q;
{function}
{selection}
{pointer_stage(source)}
    always_ff @(posedge clk) begin
        if (!rst_n) write_bank <= {reset};
        else if (finish_write_bank && !write_bank_blocked) write_bank <= {advance};
        if (!rst_n) reference_bank <= {ref_reset};
        else if (finish_write_bank && !bank_ready[reference_bank]) reference_bank <= {ref_advance};
    end
    logic sampled = 1'b0;
    always_ff @(posedge clk) sampled <= 1'b1;
    assign o_equal = !sampled || (write_bank < BANKS && write_bank == reference_bank &&
        write_bank_mask_q == (BANKS'(1) << write_bank) &&
        write_bank_blocked == bank_ready[reference_bank] &&
        next_write_bank_blocked == bank_ready[next_bank(reference_bank)]);
endmodule
"""


def observed_source(source: str) -> str:
    spec = importlib.util.spec_from_file_location(
        "fifo_count_formal", ROOT / "test/fifo_count_storage/run_formal.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    text = helper.expose_memory_ports(source)
    relation = """  for (genvar bank = 0; bank < BANKS; bank++) begin : g_formal_count
    if (p_count_storage) begin : g_memory
      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] =
          bank_ready[bank] ? g_count_memory.u_bank_count.mem[bank] : '0;
    end else begin : g_registers
      assign formal_bank_counts[bank*COUNT_WIDTH+:COUNT_WIDTH] = g_count_registers.bank_count[bank];
    end
  end
"""
    # 独立归纳证明已建立派生状态与二进制指针的关系；组合替换供完整模块比较。
    if "logic [BANKS-1:0] write_bank_mask_q;" in text:
        text = text.replace(pointer_stage(text),
                            "  assign write_bank_mask_q = BANKS'(1) << write_bank;\n")
    mask = "write_bank_mask_q" if "logic [BANKS-1:0] write_bank_mask_q;" in text else "(BANKS'(1) << write_bank)"
    relation += "  (* keep *) wire [BANKS-1:0] formal_write_mask = " + mask + ";\n"
    marker = "  logic co_group_last_result;"
    if text.count(marker) != 1:
        raise ValueError("无法定位 FIFO 状态关系的插入位置")
    return text.replace(marker, relation + marker)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="415a70a")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = read_rtl_text(ROOT / SOURCE)
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    pointer = out / "pointer.sv"
    pointer.write_text(pointer_model(current, reference))
    sources = {}
    for label, text in (("reference", reference), ("current", current)):
        sources[label] = out / f"{label}.sv"
        sources[label].write_text(observed_source(text))
    common = [ROOT / "rtl/common/regfile.v", ROOT / "rtl/common/parallel_prefix_add.sv"]
    hashes = {str(p): digest(p) for p in [ROOT / SOURCE, *common]}
    report = dict(reference=args.reference, source_sha256=hashes,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  inputs_constrained=False, data_ram_inputs_constrained=False,
                  compared="全部公开输出、数据存储地址和使能、存储写数据、有效银行计数及写指针关系",
                  method="先归纳证明实际指针更新与独热状态关系，再将该关系代入完整模块作时序等价检查",
                  pointer_runs=[], runs=[])
    profiles = [(16,1,64,1), (16,2,32,1), (16,3,64,1), (16,8,32,1),
                (16,16,64,1), (16,32,64,1), (16,64,64,1), (16,32,64,0), (8,8,32,0)]
    for vlen, banks, bus, cyclic in profiles:
        folder = out / f"v{vlen}_n{banks}_b{bus}_c{cyclic}"
        folder.mkdir(exist_ok=True)
        pointer_script, pointer_log = folder / "pointer.ys", folder / "pointer.log"
        pointer_script.write_text(f"read_slang --top pointer_formal -GBANKS={banks} {shlex.quote(str(pointer))}\n"
                                  "prep -top pointer_formal -flatten\nopt_clean\n"
                                  "sat -seq 2 -tempinduct -maxsteps 5 -set-at 1 rst_n 0 "
                                  "-prove o_equal 1 -verify\n")
        with pointer_log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(pointer_script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        if "Induction step proven: SUCCESS!" not in read_rtl_text(pointer_log):
            raise RuntimeError(f"指针状态关系证明未完成：{pointer_log}")
        report["pointer_runs"].append(dict(banks=banks, passed=True, log_sha256=digest(pointer_log)))
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
