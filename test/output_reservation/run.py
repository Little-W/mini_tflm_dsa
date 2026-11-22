#!/usr/bin/env python3
"""验证实际顶层预留寄存器对 FIFO 空间判断的逐周期影响。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source, read_current_source as read_rtl_text

TOP = Path("rtl/npu/top/npu_top.sv")


def assignments(source: str, name: str) -> list[str]:
    values = re.findall(r"\b" + name + r"\s*<=\s*([^;]+);", source)
    if len(values) != 2:
        raise ValueError(f"{name} 应具有复位和配置提交两个赋值")
    return values


def make_harness(source: str, reference: str, precomputed: bool = False) -> str:
    definitions = []
    for name in ("p_s8_reserve_width", "p_s16_reserve_width"):
        definitions.append(re.search(r"localparam int unsigned " + name + r"\s*=.*?;", source, re.S)[0])
    for name in ("output_reserve_uncapped", "output_s16_reserve_uncapped"):
        definitions.append(re.search(r"wire \[31:0\] " + name + r"\s*=.*?;", source, re.S)[0])
    old_s8 = assignments(reference, "output_reserve_banks")
    old_s16 = assignments(reference, "ia_reuse_num_eff")
    new_s8 = assignments(source, "output_reserve_banks")
    new_s16 = assignments(source, "output_s16_reserve_banks")
    definitions_text = "\n    ".join(definitions)
    text = f"""module reservation_formal #(
    parameter integer REG_WIDTH = 32,
    parameter integer OA_FIFO_BANKS = 32,
    parameter integer OA_S16_FIFO_BANKS = 4,
    parameter integer S8_COUNT_WIDTH = (OA_FIFO_BANKS <= 1) ? 1 : $clog2(OA_FIFO_BANKS+1),
    parameter integer S16_COUNT_WIDTH = (OA_S16_FIFO_BANKS <= 1) ? 1 : $clog2(OA_S16_FIFO_BANKS+1)
) (
    input logic clk, core_rst_n, cfg_stage2_fire,
    input logic use_frame_commands_s2, direct_output_cfg,
    input logic [REG_WIDTH-1:0] cfg_ia_reuse_eff_s2,
    input logic [31:0] output_reserve_calc,
    input logic [S8_COUNT_WIDTH-1:0] s8_ready,
    input logic [S16_COUNT_WIDTH-1:0] s16_ready,
    input logic s8_partial, s16_partial,
    output logic o_equal,
    output logic [1:0] actual_full, reference_full
);
    {definitions_text}
    logic [31:0] reference_s8;
    logic [REG_WIDTH-1:0] reference_s16;
    logic [p_s8_reserve_width-1:0] output_reserve_banks;
    logic [p_s16_reserve_width-1:0] output_s16_reserve_banks;
    always_ff @(posedge clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            reference_s8 <= {old_s8[0]};
            reference_s16 <= {old_s16[0]};
            output_reserve_banks <= {new_s8[0]};
            output_s16_reserve_banks <= {new_s16[0]};
        end else if (cfg_stage2_fire) begin
            reference_s8 <= {old_s8[1]};
            reference_s16 <= {old_s16[1]};
            output_reserve_banks <= {new_s8[1]};
            output_s16_reserve_banks <= {new_s16[1]};
        end
    end
    fifo_bank_watermark #(.p_banks(OA_FIFO_BANKS)) u_s8_reference (
        .i_reserve(reference_s8), .i_ready_banks(s8_ready),
        .i_partial_write(s8_partial), .o_full(reference_full[0])
    );
    fifo_bank_watermark #(.p_banks(OA_FIFO_BANKS)) u_s8_actual (
        .i_reserve(32'(output_reserve_banks)), .i_ready_banks(s8_ready),
        .i_partial_write(s8_partial), .o_full(actual_full[0])
    );
    fifo_bank_watermark #(.p_banks(OA_S16_FIFO_BANKS)) u_s16_reference (
        .i_reserve(32'(reference_s16)), .i_ready_banks(s16_ready),
        .i_partial_write(s16_partial), .o_full(reference_full[1])
    );
    fifo_bank_watermark #(.p_banks(OA_S16_FIFO_BANKS)) u_s16_actual (
        .i_reserve(32'(output_s16_reserve_banks)), .i_ready_banks(s16_ready),
        .i_partial_write(s16_partial), .o_full(actual_full[1])
    );
    wire [31:0] expected_s8 = reference_s8 >= 32'(OA_FIFO_BANKS) ? 32'(OA_FIFO_BANKS) : reference_s8;
    wire [31:0] expected_s16 = 32'(reference_s16) >= 32'(OA_S16_FIFO_BANKS) ?
        32'(OA_S16_FIFO_BANKS) : 32'(reference_s16);
    assign o_equal = actual_full == reference_full &&
        32'(output_reserve_banks) == expected_s8 &&
        32'(output_s16_reserve_banks) == expected_s16;
endmodule
"""
    if precomputed:
        # 保存阈值的赋值直接取自顶层，证明覆盖任意配置提交和计数编码。
        for precision, width in (("s8", "p_s8_reserve_width"), ("s16", "p_s16_reserve_width")):
            name = f"output_{precision}_ready_threshold"
            reset, capture = assignments(source, name)
            text = text.replace("    always_ff @(posedge clk or negedge core_rst_n) begin",
                                f"    logic [{width}-1:0] {name};\n"
                                "    always_ff @(posedge clk or negedge core_rst_n) begin")
            text = text.replace("        if (!core_rst_n) begin",
                                f"        if (!core_rst_n) begin\n            {name} <= {reset};")
            text = text.replace("        end else if (cfg_stage2_fire) begin",
                                f"        end else if (cfg_stage2_fire) begin\n            {name} <= {capture};")
            count_width = "S8_COUNT_WIDTH" if precision == "s8" else "S16_COUNT_WIDTH"
            banks = "OA_FIFO_BANKS" if precision == "s8" else "OA_S16_FIFO_BANKS"
            old = f"fifo_bank_watermark #(.p_banks({banks})) u_{precision}_actual ("
            new = (f"fifo_bank_watermark #(.p_banks({banks}), .p_precomputed_threshold(1'b1)) "
                   f"u_{precision}_actual (\n        .i_ready_threshold({count_width}'({name})),")
            if text.count(old) != 1:
                raise ValueError("无法定位实际 FIFO 容量实例")
            text = text.replace(old, new)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="415a70a")
    parser.add_argument("--precomputed-threshold", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = read_rtl_text(ROOT / TOP)
    reference = read_rtl_source(f"{args.reference}:{TOP}", cwd=ROOT, text=True)
    harness = out / "formal.sv"
    harness.write_text(make_harness(source, reference, args.precomputed_threshold))
    sources = [harness, ROOT / "rtl/npu/writeback/vec_s8_to_fifo.sv",
               ROOT / "rtl/common/parallel_prefix_add.sv", ROOT / "rtl/common/regfile.v"]
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    import runpy
    dependency_reader = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))
    sources = dependency_reader["with_dependencies"](sources, ROOT)
    before = {str(p): digest(p) for p in sources}
    report = dict(reference=args.reference, source_sha256=digest(ROOT / TOP),
                  precomputed_threshold=args.precomputed_threshold,
                  fifo_source_sha256=digest(ROOT / "rtl/npu/writeback/vec_s8_to_fifo.sv"),
                  proof_scope="实际配置表达式和有效预留寄存器；全部计数与部分写入编码",
                  reset="首个采样周期复位；其余配置、复位、计数和握手输入任意", runs=[])
    profiles = [(4,1,1), (8,2,2), (16,3,1), (32,4,4), (32,5,3),
                (32,16,4), (32,31,5), (32,32,4), (32,64,8),
                (40,96,16), (64,128,32), (64,256,64), (32,512,4)]
    for width, s8, s16 in profiles:
        folder = out / f"w{width}_s8_{s8}_s16_{s16}"
        folder.mkdir(exist_ok=True)
        script, log = folder / "run.ys", folder / "formal.log"
        script.write_text("read_slang --top reservation_formal " +
                          f"-GREG_WIDTH={width} -GOA_FIFO_BANKS={s8} -GOA_S16_FIFO_BANKS={s16} " +
                          shlex.join(map(str, sources)) +
                          "\nprep -top reservation_formal -flatten\nasync2sync\nopt_clean\n" +
                          "sat -seq 2 -tempinduct -maxsteps 4 -set-at 1 core_rst_n 0 " +
                          "-prove o_equal 1 -verify\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if "Induction step proven: SUCCESS!" not in read_rtl_text(log):
            raise RuntimeError(f"预留数量归纳证明未完成：{log}")
        item = dict(register_width=width, s8_banks=s8, s16_banks=s16,
                    passed=True, log_sha256=digest(log))
        report["runs"].append(item)
        print(json.dumps(item), flush=True)
    if source != read_rtl_text(ROOT / TOP) or before != {str(p): digest(p) for p in sources}:
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
