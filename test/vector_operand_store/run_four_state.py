#!/usr/bin/env python3
"""逐周期比较操作数存储的全部输出，覆盖并发写入和四态选择。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_engine_operand_store.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="5adaa4c9")
    parser.add_argument("--tile", type=int, default=16)
    parser.add_argument("--bus-width", type=int, default=64)
    parser.add_argument("--pes", type=int, default=8)
    parser.add_argument("--window-lanes", type=int, default=8)
    parser.add_argument("--shared-storage", type=int, choices=(0, 1), default=1)
    parser.add_argument("--shared-quant", type=int, choices=(0, 1), default=0)
    parser.add_argument("--cycles", type=int, default=20000)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    original = subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"], cwd=ROOT, text=True)
    reference = out / "operand_reference.sv"
    reference.write_text(re.sub(r"\bmodule\s+vector_engine_operand_store\b",
                                "module operand_reference", original, count=1))
    pattern = r"module vector_engine_operand_store\s*#\((.*?)\)\s*\((.*?)\n\);"
    parameters, header = re.search(pattern, current, re.S).groups()
    old_header = re.search(pattern, original, re.S)[2]
    clean = lambda text: re.sub(r"\s+", "", re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.S))
    if clean(header) != clean(old_header):
        raise ValueError("参考模块与待测模块的公开接口不同")
    header = re.sub(r"//[^\n]*|/\*.*?\*/", " ", header, flags=re.S)
    names = re.findall(r"\bparameter\s+(?:int|bit)\s+(?:unsigned\s+)?(\w+)", parameters)
    ports = []
    for match in re.finditer(
            r"\b(input|output)\s+(?:wire\s+)?((?:logic|\w+::\w+)(?:\s+signed)?"
            r"(?:\s*\[[^\]]+\])*)\s+(\w+)\s*((?:\[[^\]]+\]\s*)*)\s*(?:,|$)",
            header.strip(), re.S):
        direction, dtype, name, dimensions = match.groups()
        ports.append((direction, dtype, name, dimensions.strip()))
    if len(ports) != len(re.findall(r"\b(?:input|output)\b", header)):
        raise ValueError("需要比较全部公开端口")
    output_count = sum(direction == "output" for direction, _, _, _ in ports)
    lines = ["`timescale 1ns/1ps\nmodule tb #(\n", parameters, ") ();\n"]
    for direction, dtype, name, dimensions in ports:
        if direction == "input":
            if dtype in ("vector_engine_control_pkg::state_t", "vector_engine_control_pkg::load_t"):
                dtype = f"logic [$bits({dtype})-1:0]"
            lines.append(f"  {dtype} {name} {dimensions};\n")
        else:
            dtype = dtype.replace("logic", "wire", 1)
            lines.append(f"  {dtype} {name} {dimensions}, ref_{name} {dimensions};\n")
    lines.append("  integer checks = 0, known_inputs = 0, known_weights = 0;\n")
    for module, instance, prefix in (("vector_engine_operand_store", "dut", ""),
                                      ("operand_reference", "reference_store", "ref_")):
        lines.append(f"  {module} #(\n")
        lines.append(",\n".join(f"    .{name}({name})" for name in names))
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
                     f'      $fatal(1, "Output mismatch: {name}, cycle=%0d", checks);\n')
    lines += ["    for (int lane=0; lane<p_pe_count; lane++) begin\n",
              "      if (!$isunknown(o_input_lane[lane]) && o_input_lane[lane] != 0) known_inputs++;\n",
              "      if (!$isunknown(o_weight_lane[lane]) && o_weight_lane[lane] != 0) known_weights++;\n",
              "    end\n    checks++; clk = 1'b0; #1;\n  endtask\n  initial begin\n"]
    for direction, _, name, dimensions in ports:
        if direction != "input":
            continue
        if dimensions:
            length = re.fullmatch(r"\[([^\]]+)\]", dimensions)[1]
            lines.append(f"    for (int lane=0; lane<{length}; lane++) {name}[lane] = '0;\n")
        else:
            lines.append(f"    {name} = '0;\n")
    lines += ["    repeat (3) tick();\n",
              f"    for (int sample=0; sample<{args.cycles}; sample++) begin\n"]
    for direction, _, name, dimensions in ports:
        if direction != "input" or name in ("clk", "rst_n", "i_c"):
            continue
        if dimensions:
            length = re.fullmatch(r"\[([^\]]+)\]", dimensions)[1]
            lines.append(f"      for (int lane=0; lane<{length}; lane++) {name}[lane] = {{$urandom, $urandom}};\n")
        else:
            lines.append(f"      {name} = {{$urandom, $urandom}};\n")
    lines += ["      rst_n = sample % 257 != 0;\n",
              "      i_c = '0; i_c.vector_s16 = sample[0];\n",
              "      i_state = sample % 3 == 0 ? vector_engine_control_pkg::LOAD_WAIT : vector_engine_control_pkg::EXECUTE;\n",
              "      if (sample % 31 == 0) i_state = vector_engine_control_pkg::TILE_INIT;\n",
              "      i_load_kind = sample % 7;\n",
              "      i_active = p_active_count_w'(p_tile);\n",
              "      i_rd_col_base = p_input_index_w'((sample / 7) % p_tile);\n",
              "      i_win_rsp_col = 32'((sample / 3) % p_tile);\n",
              "      i_input_response_base = p_input_index_w'((sample / 11) % 2 * p_tile);\n",
              "      i_tap = '0; i_weight_prefetch_q = '0;\n",
              "      if (!p_shared_storage_enable && sample % 2 == 0) i_load_tap = '0;\n",
              "      case (sample % 4)\n",
              "        0: i_compute_index = '0;\n",
              "        1: i_compute_index = p_tile_index_w'(p_pe_count);\n",
              "        2: i_compute_index = p_tile_index_w'(2*p_pe_count);\n",
              "        default: ;\n      endcase\n",
              "      if (sample >= 2000) begin\n",
              "        case (sample % 23)\n",
              "          0: i_win_rsp_col[sample % 32] = 1'bx;\n",
              "          1: i_input_response_base[sample % p_input_index_w] = 1'bz;\n",
              "          2: i_compute_index[sample % p_tile_index_w] = 1'bx;\n",
              "          3: i_c.vector_s16 = 1'bx;\n",
              "          4: i_c.vector_s16 = 1'bz;\n",
              "          5: i_state[sample % $bits(i_state)] = 1'bx;\n",
              "          6: i_load_kind[sample % $bits(i_load_kind)] = 1'bz;\n",
              "          7: i_global_pool = 1'bx;\n",
              "          8: i_weight_read_data[sample % 128] = 1'bx;\n",
              "          9: i_weight_read_data[sample % 128] = 1'bz;\n",
              "          10: i_weight_read_valid = 1'bx;\n",
              "          11: i_rd_data[sample % p_bus_bytes][sample % 16] = 1'bz;\n",
              "          12: i_win_rsp_data[sample % p_window_lanes][sample % 16] = 1'bx;\n",
              "          13: i_win_rsp_mask[sample % p_window_lanes] = 1'bz;\n",
              "          14: i_tap[sample % p_tap_count_w] = 1'bx;\n",
              "          15: i_rd_col_base[sample % p_input_index_w] = 1'bz;\n",
              "          default: ;\n        endcase\n      end\n      tick();\n    end\n",
              '    if (known_inputs < 500 || known_weights < 500) $fatal(1, "Insufficient known operands");\n',
              f'    $display("OPERAND_FOUR_STATE_PASS checks=%0d outputs={output_count} known_inputs=%0d known_weights=%0d", checks, known_inputs, known_weights);\n',
              "    $finish;\n  end\nendmodule\n"]
    testbench = out / "tb.sv"
    testbench.write_text("".join(lines))
    packages = [ROOT / "rtl/npu/conv" / name for name in
                ("conv_im2col_pkg.sv", "vector_engine_pkg.sv", "vector_engine_control_pkg.sv")]
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolve(packages + [ROOT / SOURCE], ROOT) + [reference, testbench]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    simulation_sources, translations = [], []
    bank_storage = args.tile == 16 and args.pes == 8 and args.bus_width == 64 and args.window_lanes == 8
    for index, path in enumerate(sources):
        content = path.read_text()
        # 常量项和寄存项共用数组时，以组合过程在仿真开始时建立常量项。
        converted, count = re.subn(r"assign input_buf\[entry\]\s*=\s*16'sd0;",
                                   "always_comb input_buf[entry] = 16'sd0;", content) if not bank_storage else (content, 0)
        if count:
            copy = out / f"simulation_source_{index}.sv"
            copy.write_text(converted)
            simulation_sources.append(copy)
            translations.append(dict(source=str(path), constant_array_elements=count,
                                     sha256=hashlib.sha256(converted.encode()).hexdigest()))
        else:
            simulation_sources.append(path)
    config = dict(p_tile=args.tile, p_bus_width=args.bus_width, p_pe_count=args.pes,
                  p_window_lanes=args.window_lanes, p_shared_storage_enable=args.shared_storage,
                  p_shared_quant_enable=args.shared_quant)
    command = ["iverilog", "-g2012", "-s", "tb", "-o", str(out / "simulation.vvp"),
               *(f"-Ptb.{name}={value}" for name, value in config.items()), *map(str, simulation_sources)]
    with (out / "compile.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(["vvp", str(out / "simulation.vvp")], capture_output=True,
                            text=True, timeout=240)
    (out / "run.log").write_text(result.stdout + result.stderr)
    match = re.search(r"OPERAND_FOUR_STATE_PASS checks=(\d+) outputs=(\d+) known_inputs=(\d+) known_weights=(\d+)", result.stdout)
    if result.returncode or match is None:
        raise RuntimeError(result.stdout + result.stderr)
    if hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}:
        raise RuntimeError("测试期间 RTL 源文件发生变化")
    summary = dict(passed=True, revision=revision, parameters=config, source_sha256=hashes,
                   cycles=int(match[1]), compared_outputs=int(match[2]), known_inputs=int(match[3]),
                   known_weights=int(match[4]), simulation_translations=translations, compile_command=command)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(match[0])


if __name__ == "__main__":
    main()
