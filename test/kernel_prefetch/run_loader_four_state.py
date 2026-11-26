#!/usr/bin/env python3
"""比较完整内核加载器在随机输入、列号溢出及四态输入下的行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

from run_reference_comparison import ROOT, prepare_reference, split_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="2247144937c2")
    parser.add_argument("--rtl", type=Path)
    parser.add_argument("--count-width", type=int, default=16)
    parser.add_argument("--cycles", type=int, default=20000)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, _, manifest = prepare_reference(args.reference, out)
    candidate = args.rtl.resolve() if args.rtl else ROOT / "rtl/npu/loaders/kernel_loader.sv"
    content = candidate.read_text()
    header = re.search(r"module kernel_loader\s*#\(.*?\)\s*\((.*?)\n\);", content, re.S)[1]
    header = re.sub(r"//[^\n]*|/\*.*?\*/", " ", header, flags=re.S)
    ports = []
    for match in re.finditer(
            r"\b(input|output)\s+(?:wire\s+)?(logic(?:\s+signed)?(?:\s*\[[^\]]+\])*)\s+"
            r"(.+?)(?=,\s*(?:input|output)\b|\Z)", header.strip(), re.S):
        direction, dtype, values = match.groups()
        for value in split_values(values.strip().rstrip(",")):
            variable = re.fullmatch(r"(\w+)(\s*(?:\[[^\]]+\]\s*)*)(?:\s*=.*)?", value, re.S)
            if variable is None:
                raise ValueError("无法读取公开端口：" + value)
            ports.append((direction, dtype, variable[1], variable[2].strip()))
    if len(ports) != manifest["public_ports"]:
        raise ValueError("四态比较需要覆盖全部公开端口")
    parameters = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, DMA_LANES=8, REG_WIDTH=32,
                      COUNT_WIDTH=args.count_width, CACHE_BLOCKS=1)
    lines = ["`timescale 1ns/1ps\nmodule tb_loader_four_state;\n"]
    lines += [f"  localparam int {name} = {value};\n" for name, value in parameters.items()]
    for direction, dtype, name, dimensions in ports:
        if direction == "input":
            lines.append(f"  {dtype} {name} {dimensions};\n")
        else:
            nettype = dtype.replace("logic", "wire", 1)
            lines.append(f"  {nettype} {name} {dimensions}, ref_{name} {dimensions};\n")
    lines += ["  logic [COUNT_WIDTH-1:0] column_group, column_offset;\n",
              "  wire [COUNT_WIDTH-1:0] column_position = column_group + column_offset;\n",
              "  wire column_last = COUNT_WIDTH'(column_offset + COUNT_WIDTH'(1)) >= dut.u_ctrl.current_group_width;\n",
              "  logic [REG_WIDTH-1:0] position_base;\n",
              "  integer checked_cycles = 0, known_positions = 0;\n"]
    for module, instance, prefix in (("kernel_loader", "dut", ""),
                                      ("kernel_ref__kernel_loader", "reference_loader", "ref_")):
        lines.append(f"  {module} #(\n")
        lines.append(",\n".join(f"    .{name}({name})" for name in parameters))
        lines.append(f"\n  ) {instance} (\n")
        lines.append(",\n".join(f"    .{name}({prefix + name if direction == 'output' else name})"
                                 for direction, _, name, _ in ports))
        lines.append("\n  );\n")
    lines.append("  task automatic tick;\n    #2; clk = 1'b1; #2;\n")
    for direction, _, name, dimensions in ports:
        if direction != "output":
            continue
        suffix = ""
        for index, length in enumerate(re.findall(r"\[([^\]]+)\]", dimensions)):
            lines.append(f"    for (int item{index}=0; item{index}<{length}; item{index}++)\n")
            suffix += f"[item{index}]"
        lines.append(f"    if ({name}{suffix} !== ref_{name}{suffix})\n"
                     f'      $fatal(1, "Output mismatch: {name}, cycle=%0d", checked_cycles);\n')
    lines += ["    if (dut.position_sum[0] !== reference_loader.position_sum[0])\n",
              '      $fatal(1, "Column position mismatch, cycle=%0d", checked_cycles);\n',
              "    if (dut.column_equal_o_equal !== reference_loader.column_equal_o_equal)\n",
              '      $fatal(1, "Column equality mismatch, cycle=%0d", checked_cycles);\n',
              "    if (!$isunknown(dut.position_sum[0])) known_positions++;\n",
              "    checked_cycles++; clk = 1'b0; #1;\n  endtask\n  initial begin\n"]
    for direction, _, name, dimensions in ports:
        if direction != "input":
            continue
        if dimensions:
            length = re.fullmatch(r"\[([^\]]+)\]", dimensions)[1]
            lines.append(f"    for (int lane=0; lane<{length}; lane++) {name}[lane] = '0;\n")
        else:
            lines.append(f"    {name} = '0;\n")
    lines += ["    repeat (4) tick();\n",
              f"    for (int sample=0; sample<{args.cycles}; sample++) begin\n"]
    for direction, _, name, dimensions in ports:
        if direction != "input" or name in ("clk", "rst_n"):
            continue
        if dimensions:
            length = re.fullmatch(r"\[([^\]]+)\]", dimensions)[1]
            lines.append(f"      for (int lane=0; lane<{length}; lane++) {name}[lane] = $urandom;\n")
        else:
            lines.append(f"      {name} = $urandom;\n")
    lines += ["      rst_n = sample % 31 != 0;\n",
              "      column_group = COUNT_WIDTH'($urandom);\n",
              "      column_offset = COUNT_WIDTH'($urandom);\n",
              "      position_base = $urandom;\n",
              "      if (sample == 1000) begin\n",
              "        force dut.u_ctrl.group_base_col = column_group;\n",
              "        force reference_loader.u_ctrl.group_base_col = column_group;\n",
              "        force dut.u_ctrl.load_col_in_group = column_offset;\n",
              "        force reference_loader.u_ctrl.load_col_in_group = column_offset;\n",
              # 列位置状态与独立注入的组起点、组内偏移保持相同的模宽关系。
              "        force dut.u_ctrl.column_position_q = column_position;\n",
              "        force dut.u_ctrl.last_col_saved_q = column_last;\n",
              "        force dut.p0_base_q = position_base;\n",
              "        force reference_loader.p0_base_q = position_base;\n",
              "      end\n",
              "      if (sample >= 2000) begin\n",
              "        case (sample % 29)\n",
              "          0: column_group[sample % COUNT_WIDTH] = 1'bx;\n",
              "          1: column_offset[sample % COUNT_WIDTH] = 1'bz;\n",
              "          2: position_base[sample % REG_WIDTH] = 1'bx;\n",
              "          3: position_base[sample % REG_WIDTH] = 1'bz;\n",
              "          4: prefetch_p0[sample % REG_WIDTH] = 1'bx;\n",
              "          5: prefetch_p0[sample % REG_WIDTH] = 1'bz;\n",
              "          6: init_cfg = 1'bx;\n",
              "          7: cache_flush = 1'bz;\n",
              "          8: cfg_command_mode = 1'bx;\n",
              "          9: ext_dma_done = 1'bz;\n",
              "          10: ext_dma_wr_data[sample % DMA_LANES][sample % DATA_WIDTH] = 1'bx;\n",
              "          11: ext_dma_wr_valid[sample % DMA_LANES] = 1'bz;\n",
              "          12: ext_dma_wr_col_base[sample % $clog2(SIZE)] = 1'bx;\n",
              "          13: load_weight_granted = 1'bz;\n",
              "          14: m[sample % REG_WIDTH] = 1'bx;\n",
              "          15: n[sample % REG_WIDTH] = 1'bz;\n",
              "          default: ;\n        endcase\n      end\n      tick();\n    end\n",
              f'    if (known_positions < {args.cycles // 4}) $fatal(1, "Insufficient known positions");\n',
              '    $display("KERNEL_LOADER_FOUR_STATE_PASS cycles=%0d outputs=23 known_positions=%0d", checked_cycles, known_positions);\n',
              "    $finish;\n  end\nendmodule\n"]
    testbench = out / "tb_loader_four_state.sv"
    testbench.write_text("".join(lines))
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolve([candidate], ROOT) + [reference, testbench]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    simulation_sources, translations = [], []
    for index, path in enumerate(sources):
        source = path.read_text()
        # 此组合临时变量每次循环先赋值，静态声明保留相同的计算语义。
        translated, count = re.subn(r"\bautomatic int col;(?=\s+col\s*=)", "int col;", source)
        # 固定位与寄存位共用向量时，组合过程在仿真开始时建立固定位。
        translated, constant_count = re.subn(
            r"assign issued_chunk_carry_q\[0\] = 1'b1;",
            "always_comb issued_chunk_carry_q[0] = 1'b1;", translated)
        if count or constant_count:
            copy = out / f"simulation_{index}.sv"
            copy.write_text(translated)
            simulation_sources.append(copy)
            translations.append(dict(source=str(path), static_column_declarations=count,
                                     constant_carry_assignments=constant_count,
                                     translated_sha256=hashlib.sha256(translated.encode()).hexdigest()))
        else:
            simulation_sources.append(path)
    command = ["iverilog", "-g2012", "-s", "tb_loader_four_state", "-o", str(out / "compare.vvp"),
               *map(str, simulation_sources)]
    with (out / "compile.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(["vvp", str(out / "compare.vvp")], capture_output=True,
                            text=True, check=True, timeout=180)
    (out / "run.log").write_text(result.stdout + result.stderr)
    match = re.search(r"KERNEL_LOADER_FOUR_STATE_PASS cycles=(\d+) outputs=(\d+) known_positions=(\d+)", result.stdout)
    if match is None:
        raise RuntimeError("四态比较未报告成功")
    if hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}:
        raise RuntimeError("测试期间 RTL 源文件发生变化")
    summary = dict(passed=True, parameters=parameters, reference=manifest,
                   cycles=int(match[1]), compared_outputs=int(match[2]), known_positions=int(match[3]),
                   source_sha256=hashes, simulation_translations=translations, compile_command=command)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(match[0])


if __name__ == "__main__":
    main()
