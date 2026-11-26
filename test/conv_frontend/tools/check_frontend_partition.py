#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""从参考前端提取原始过程，验证拆分模块的状态和四态选择行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
FRONTEND = Path("rtl/npu/conv/conv_im2col_frontend.sv")
PARTS = {
    "runtime_registers": ("u_runtime_registers", [
        ("  // 保存前端配置、描述符和坐标状态。", "`ifdef NPU_SIM_ASSERT")]),
    "state_control": ("u_state_control", [
        ("  // 当前操作和准备好的地址结果并行形成运行状态。", "  // 配置与运行错误分别形成候选")]),
    "wrap_state": ("u_wrap_state", [
        ("  // 各运行来源先准备回绕值与写入资格", "  // 保存前端配置、描述符和坐标状态。")]),
    "payload_select": ("u_payload_select", [
        ("  // 卷积核列数据按运行阶段预选", "  // 数据来源由运行阶段提前选择"),
        ("  if (!REGISTER_DESCRIPTOR) begin : g_parallel_descriptor_payload", "  // 请求地址、窗口索引和有效位同时寄存")]),
    "request_index": ("u_request_index", [
        ("  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_index", "  // 两个描述符纪元")]),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log: Path, timeout=300):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, timeout=timeout, check=True)


def declarations(reference: str) -> dict[str, str]:
    code = re.sub(r"//[^\n]*|/\*.*?\*/|\(\*.*?\*\)", " ", reference, flags=re.S)
    result = {}
    for match in re.finditer(r"\b(logic|conv_cfg_t|st_t|prepared_tile_t)\s+([^;]+);", code):
        base, declaration = match.groups()
        prefix = re.match(r"((?:signed\s+)?(?:\[[^\]]+\]\s*)*)(.*)", declaration, re.S)
        if prefix is None:
            continue
        dimensions, names = prefix.groups()
        for name in names.split(","):
            name = name.strip()
            if re.fullmatch(r"\w+(?:\s*\[[^\]]+\])?", name):
                key = re.match(r"\w+", name).group()
                result[key] = f"{base} {dimensions}{name};"
    result.update(clk="logic clk;", rst_n="logic rst_n;", cfg_valid="logic cfg_valid;",
                  cfg_ready="logic cfg_ready;", cfg="conv_cfg_t cfg;", cfg_sched_groups="logic [31:0] cfg_sched_groups;",
                  wr_valid="logic wr_valid;", wr_ready="logic wr_ready;", tile_done="logic tile_done;")
    return result


def port_list(source: str):
    header = source[:source.index("\n);")+3]
    ports = []
    for line in header.splitlines():
        match = re.match(r"\s*(input|output)\s+(?:wire\s+)?(.+?)\s+(\w+)\s*,?\s*//", line)
        if match:
            direction, kind, name = match.groups()
            ports.append((direction, kind, name))
    return header, ports


def connections(frontend: str, instance: str) -> dict[str, str]:
    begin = frontend.index(instance+" (")+len(instance)+1
    level, end = 1, begin+1
    while level:
        level += (frontend[end] == "(") - (frontend[end] == ")")
        end += 1
    return dict(re.findall(r"\.(\w+)\(([^()]*)\)", frontend[begin+1:end-1]))


def golden(part: str, source: str, frontend: str, reference: str) -> tuple[str, list]:
    instance, regions = PARTS[part]
    body = ""
    for first, last in regions:
        start = reference.index(first)
        body += reference[start:reference.index(last, start)]
    header, ports = port_list(source)
    name = "conv_im2col_"+part
    header = header.replace("module "+name, "module gold_"+name)
    parameters = set(re.findall(r"\b(?:parameter|localparam)\s+\w+\s+(\w+)", header))
    legacy = {
        "SIZE": ("p_size", "16"), "SLOT_W": ("p_slot_width", "5"),
        "TILE_COUNT_W": ("p_count_width", "5"), "CHUNK_COUNT_W": ("p_chunk_width", "4"),
        "COORD_W": ("p_coord_width", "35"), "CACHE_SETS": ("p_cache_sets", "16"),
        "CACHE_WAYS": ("p_cache_ways", "2"), "REGISTER_DESCRIPTOR": ("p_register_descriptor", "0"),
        "p_cache_read_width": ("p_read_width", "64"), "p_row_high_w": ("p_row_high_width", "27"),
        "p_word_shift": ("p_word_shift", "3"), "p_saved_group_lanes": ("p_saved_group_lanes", "8"),
    }
    header += "\n  import conv_im2col_pkg::*;\n  import conv_im2col_frontend_pkg::*;\n"
    for name, (parameter, default) in legacy.items():
        if name not in parameters:
            header += f"  localparam int {name} = {parameter if parameter in parameters else default};\n"
    header += ("  localparam int p_prepared_count_w=TILE_COUNT_W;\n"
               "  localparam int p_prepared_slot_w=SLOT_W;\n"
               "  localparam int p_prepared_coord_w=COORD_W;\n"
               "  `include \"conv_im2col_prepared_tile.svh\"\n")
    bindings = connections(frontend, instance)
    missing = {name for _, _, name in ports} - bindings.keys()
    if missing:
        raise ValueError(f"Missing frontend connections: {missing}")
    used = set(re.findall(r"\b\w+\b", re.sub(r"//[^\n]*", "", body)))
    used.update(re.findall(r"\b\w+\b", " ".join(bindings.values())))
    declared = declarations(reference)
    existing = {name for _, _, name in ports}
    # 原始过程中的展开坐标由保存的十六位字段产生。
    if part == "runtime_registers":
        used.update(("ox_q", "oy_q", "ky_q", "ky0_q"))
    for name in sorted(used & declared.keys() - existing):
        header += "  "+declared[name]+"\n"
    for direction, _, name in ports:
        binding = bindings[name]
        if binding == name:
            continue
        header += f"  assign {binding if direction == 'input' else name} = {name if direction == 'input' else binding};\n"
    if part == "runtime_registers":
        for name, saved in (("ox", "ox_q"), ("oy", "oy_q"), ("ky", "ky_q"), ("ky0", "ky0_q")):
            header += f"  assign {name}=32'({saved});\n"
    return header+body+"endmodule\n", ports


def bench(part: str, source: str, ports, samples: int, registered: int) -> str:
    sequential = any(name == "clk" for _, _, name in ports)
    inputs = [(kind, name) for direction, kind, name in ports if direction == "input" and name not in ("clk", "rst_n")]
    outputs = [(kind, name) for direction, kind, name in ports if direction == "output"]
    variables = "\n".join(f"{kind} {name};" for _, kind, name in ports)
    variables += "\n"+"\n".join(f"{kind} expected_{name};" for kind, name in outputs)
    variables = variables.replace("conv_im2col_frontend_pkg::st_t", "logic [26:0]")
    parameters = (f".p_register_descriptor({registered})"
                  if re.search(r"\bparameter\s+bit\s+p_register_descriptor\b", source) else "")
    actual_connection = ",".join("."+name for _, _, name in ports)
    expected_connection = ",".join(f".{name}({('expected_' if direction == 'output' else '')+name})" for direction, _, name in ports)
    all_input = "{"+",".join(name for _, name in inputs)+"}"
    all_output = "{"+",".join(name for _, name in outputs)+"}"
    all_expected = "{"+",".join("expected_"+name for _, name in outputs)+"}"
    controls = [name for kind, name in inputs if kind == "logic"]
    parameter_declarations = ""
    header = source[:source.index("\n);")+3]
    for kind, name, value in re.findall(r"\bparameter\s+(int|bit)\s+(\w+)\s*=\s*([^\n]+)", header):
        parameter_declarations += f"localparam {kind} {name}={value.rstrip().rstrip(',')};\n"
    parameter_override = f"#({parameters}) " if parameters else ""
    text = ("module tb;\n"+parameter_declarations+variables+"\n"
            f"localparam int WIDTH=$bits({all_input});\nlogic [((WIDTH+31)/32)*32-1:0] pattern;\n"
            f"conv_im2col_{part} {parameter_override}actual({actual_connection});\n"
            f"gold_conv_im2col_{part} {parameter_override}expected({expected_connection});\ninitial begin\n")
    if sequential:
        text += "clk=0;rst_n=0;#1;clk=1;#1;clk=0;rst_n=1;\n"
    text += (f"for(integer sample=0;sample<{samples};sample++)begin\n"
             "for(integer word=0;word<(WIDTH+31)/32;word++)pattern[32*word+:32]=$urandom;\n"
             "if(sample%11==0)pattern[sample%WIDTH]=1'bx;\n"
             "if(sample%13==0)pattern[(sample*17)%WIDTH]=1'bz;\n"
             f"{all_input}=pattern;\n")
    if any(name == "i_state" for _, name in inputs):
        text += ("if(sample%4!=0)i_state=27'b1<<(sample%27);\n"
                 "if(sample%17==0)i_state[sample%27]=1'bx;\n"
                 "if(sample%31==0)i_state[sample%27]=1'bz;\n")
    for kind, name in inputs:
        if "select" in name and name not in controls:
            text += f"if(sample%19==0){name}[sample%$bits({name})]=1'bx;\n"
            text += f"if(sample%23==0){name}[sample%$bits({name})]=1'bz;\n"
    for index, name in enumerate(controls):
        text += f"if(sample%{2*len(controls)+1}=={2*index}){name}=1'bx;\n"
        text += f"if(sample%{2*len(controls)+1}=={2*index+1}){name}=1'bz;\n"
    if sequential:
        text += "#1;clk=1;#1;\n"
    else:
        text += "#1;\n"
    text += f"if({all_output}!=={all_expected})$fatal(1,\"Partition {part} differs sample=%0d\",sample);\n"
    if sequential:
        text += "clk=0;\n"
    return text+f"end\n$display(\"FRONTEND_PARTITION_FOUR_STATE_PASS part={part} samples={samples}\");$finish;end\nendmodule\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-source-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=2048)
    parser.add_argument("--register-descriptor", type=int, choices=(0, 1), default=0)
    parser.add_argument("--synthesis", action="store_true")
    args = parser.parse_args()
    root, reference_root, out = args.source_root.resolve(), args.reference_source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    frontend, reference = (root/FRONTEND).read_text(), (reference_root/FRONTEND).read_text()
    reader = runpy.run_path(str(root/"scripts/rtl/source_files.py"))["with_dependencies"]
    results, hashes = {}, {str(path): digest(path) for path in (root/FRONTEND, reference_root/FRONTEND)}
    for part in PARTS:
        folder = out/part
        folder.mkdir(exist_ok=True)
        source = root/f"rtl/npu/conv/conv_im2col_{part}.sv"
        sources = reader([root/"rtl/npu/conv/conv_im2col_pkg.sv",
                          root/"rtl/npu/conv/conv_im2col_frontend_pkg.sv", source], root)
        hashes.update({str(path): digest(path) for path in sources})
        model, ports = golden(part, source.read_text(), frontend, reference)
        generated = folder/"gold.sv"
        generated.write_text(model)
        include = " -I "+str(root/"include")
        names = " ".join(map(str, sources))
        top = "conv_im2col_"+part
        options = (f" -Gp_register_descriptor={args.register_descriptor}"
                   if re.search(r"\bparameter\s+bit\s+p_register_descriptor\b", source.read_text()) else "")
        script = folder/"proof.ys"
        script.write_text(f"read_slang --best-effort-hierarchy -D SYNTHESIS=1 --top gold_{top}{options}{include} {names} {generated}\n"
                          "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
                          f"prep -top gold_{top} -flatten\nasync2sync\nopt_clean\nrename gold_{top} gold\ndesign -stash gold\n"
                          f"read_slang --best-effort-hierarchy -D SYNTHESIS=1 --top {top}{options}{include} {names}\n"
                          "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
                          f"prep -top {top} -flatten\nasync2sync\nopt_clean\nrename {top} candidate\n"
                          "design -copy-from gold -as gold gold\nequiv_make gold candidate equiv\nhierarchy -top equiv\n"
                          "equiv_simple -seq 2\nequiv_induct -seq 2\nequiv_status -assert\n")
        run([sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker", script], folder/"proof.log")
        tb = folder/"tb.sv"
        tb.write_text(bench(part, source.read_text(), ports, args.samples, args.register_descriptor))
        simulation_sources = []
        for index, path in enumerate([*sources, generated]):
            target = folder/f"simulation_{index}.sv"
            simulation = path.read_text().replace("always_comb", "always @*")
            # 固定的两个坐标轴逐项展开，使四态仿真器使用常量 packed 数组下标。
            simulation = re.sub(r"for \(int axis = 0; axis < 2; axis\+\+\) begin(.*?)end",
                                lambda match: "\n".join(re.sub(r"\baxis\b", str(axis), match.group(1))
                                                        for axis in range(2)), simulation, flags=re.S)
            target.write_text(simulation)
            simulation_sources.append(target)
        binary = folder/"comparison.vvp"
        run(["iverilog", "-g2012", "-s", "tb", "-I", root/"include", "-o", binary,
             *(["-DSYNTHESIS=1"] if args.synthesis else []),
             *simulation_sources, tb], folder/"build.log")
        run(["vvp", binary], folder/"run.log", timeout=600)
        if "FRONTEND_PARTITION_FOUR_STATE_PASS" not in (folder/"run.log").read_text():
            raise RuntimeError("Four-state comparison did not complete")
        results[part] = {"formal_equivalent": True, "four_state_samples": args.samples,
                         "reference_projection_sha256": digest(generated), "proof_script_sha256": digest(script)}
        print("FRONTEND_PARTITION_PASS", part, flush=True)
    if any(digest(Path(path)) != value for path, value in hashes.items()):
        raise RuntimeError("RTL source changed during comparison")
    (out/"summary.json").write_text(json.dumps({"passed": True, "parts": results,
                                               "register_descriptor": args.register_descriptor,
                                               "synthesis": args.synthesis,
                                               "source_sha256": hashes}, indent=2)+"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
