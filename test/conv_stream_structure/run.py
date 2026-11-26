#!/usr/bin/env python3
"""验证流式模块拆分后的完整接口、辅助函数和四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
STREAM = Path("rtl/npu/conv/conv_im2col_stream.sv")
PROFILES = (
    {"p_size": 16, "p_slot_w": 5, "p_lanes": 8, "p_line_bytes": 128,
     "p_bus_width": 64, "p_register_descriptor": 0, "p_register_row_address": 0},
    {"p_size": 16, "p_slot_w": 5, "p_lanes": 8, "p_line_bytes": 128,
     "p_bus_width": 64, "p_register_descriptor": 1, "p_register_row_address": 1},
    {"p_size": 8, "p_slot_w": 3, "p_lanes": 3, "p_line_bytes": 16,
     "p_bus_width": 32, "p_register_descriptor": 0, "p_register_row_address": 1},
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def invoke(command, log, timeout=600):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, timeout=timeout, check=True)


def header_end(text):
    module = re.search(r"\bmodule\s+\w+\s*", text)
    start = module.end()
    if text[start] == "#":
        start = text.index("(", start) + 1
        depth = 1
        while depth:
            depth += (text[start] == "(") - (text[start] == ")")
            start += 1
    return text.index("(", start), text.index(");", start)


def four_state_module(text, name):
    begin, end = header_end(text)
    prefix = text[text.index("module "):begin].replace("module " + name, "module check_" + name, 1)
    lines = [prefix + "(output logic done);", " integer checks=0;"]
    inputs, outputs, actual, expected = [], [], [], []
    for line in text[begin+1:end].splitlines():
        declaration = re.sub(r"\(\*.*?\*\)", "", line.split("//", 1)[0]).strip().rstrip(",")
        if not declaration:
            continue
        match = re.fullmatch(r"(input|output)\s+(.+?)\s+(\w+)", declaration)
        if match is None:
            raise RuntimeError(f"无法读取端口声明：{name}: {declaration}")
        direction, kind, port = match.groups()
        kind = re.sub(r"\bwire\s+", "", kind)
        if direction == "input":
            lines += [f" {kind} {port};", f" logic [$bits({port})-1:0] stimulus_{port};",
                      f" assign {port}=stimulus_{port};"]
            inputs.append(port)
            actual.append(f".{port}({port})")
            expected.append(f".{port}({port})")
        else:
            lines += [f" {kind} actual_{port}, expected_{port};"]
            outputs.append(port)
            actual.append(f".{port}(actual_{port})")
            expected.append(f".{port}(expected_{port})")
    parameter_names = re.findall(r"\bparameter(?:\s+\w+)*\s+(\w+)\s*=", prefix)
    parameter_map = " #(" + ",".join(f".{param}({param})" for param in parameter_names) + ")" \
        if parameter_names else ""
    lines += [f" {name}{parameter_map} u_actual(" + ",".join(actual) + ");",
              f" reference_{name}{parameter_map} u_expected(" + ",".join(expected) + ");",
              " task automatic check;", "  #1;"]
    for port in outputs:
        lines.append(f'  if(actual_{port} !== expected_{port}) $fatal(1,"{name} {port} sample=%0d",checks);')
    lines += ["  checks++;", " endtask", " initial begin", "  done=0;",
              "  for(integer sample=0;sample<4096;sample++)begin"]
    for port in inputs:
        lines.append(f"   for(integer bit_index=0;bit_index<$bits({port});bit_index++) "
                     f"stimulus_{port}[bit_index]=$urandom_range(0,1);")
    lines.append("   check();")
    for state in ("x", "z"):
        for port in inputs:
            lines.append(f"   stimulus_{port}[sample%$bits({port})]=1'b{state};")
        lines.append("   check();")
    lines += ["  end", "  done=1;", " end", "endmodule"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out, reference = args.out.resolve(), args.reference_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = (reference / STREAM).read_text()
    names = re.findall(r"(?m)^module\s+(\w+)\b", original)[1:]
    assert len(names) == 20
    sources = {}
    hashes = {}
    for side, tree in (("gold", reference), ("gate", ROOT)):
        helper = runpy.run_path(str(tree / "scripts/rtl/source_files.py"))
        sources[side] = helper["with_dependencies"]([tree / STREAM], tree)
        hashes[side] = {str(path): digest(path) for path in helper["input_files"](sources[side], tree)}
    bodies = []
    for name in names:
        old = re.search(r"(?ms)^module\s+" + name + r"\b.*?^endmodule", original)[0]
        new = (ROOT / STREAM.parent / (name + ".sv")).read_text()
        normalize = lambda value: re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", value))
        old_body = old[header_end(old)[1]+2:old.index("endmodule")]
        new_body = new[header_end(new)[1]+2:new.index("endmodule")]
        if normalize(old_body) != normalize(new_body):
            raise RuntimeError(f"辅助模块的逻辑或函数发生变化：{name}")
        bodies.append({"module": name, "logic_unchanged": True,
                       "logic_sha256": hashlib.sha256(normalize(new_body).encode()).hexdigest()})
    results = []
    for index, parameters in enumerate(PROFILES):
        script, log = out / f"profile{index}.ys", out / f"profile{index}.log"
        commands = []
        for side, tree in (("gold", reference), ("gate", ROOT)):
            options = ["--top", "conv_im2col_stream", "-DSYNTHESIS=1", "-I"+str(tree / "include")]
            options += [f"-G{name}={value}" for name, value in parameters.items()]
            commands += ["read_slang " + shlex.join(options + list(map(str, sources[side]))),
                         "prep -top conv_im2col_stream -flatten", "memory_map", "async2sync", "opt",
                         "rename conv_im2col_stream " + side, "design -stash " + side]
        commands += ["design -copy-from gold gold", "design -copy-from gate gate",
                     "equiv_make gold gate equivalent", "hierarchy -top equivalent",
                     "opt_merge", "equiv_simple -short -seq 1", "opt_clean",
                     "equiv_induct -seq 3", "equiv_status -assert"]
        script.write_text("\n".join(commands)+"\n")
        invoke([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
        content = log.read_text()
        points = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", content)
        if "Equivalence successfully proven!" not in content or points is None or int(points[2]):
            raise RuntimeError(f"完整流式模块等价未完成：{log}")
        results.append({"parameters": parameters, "passed": True, "proven_points": int(points[1]),
                        "log_sha256": digest(log)})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    helpers = []
    for name in names:
        block = re.search(r"(?ms)^module\s+" + name + r"\b.*?^endmodule", original)[0]
        helpers.append(block)
    reference_text = "\n".join(helpers)
    for name in sorted(names, key=len, reverse=True):
        reference_text = re.sub(r"\b"+name+r"\b", "reference_"+name, reference_text)
    reference_file = out / "reference_helpers.sv"
    reference_file.write_text(reference_text + "\n")
    bench = out / "four_state.sv"
    modules = [four_state_module((ROOT / STREAM.parent / (name + ".sv")).read_text(), name)
               for name in names]
    top = ["module tb;", f" wire [{len(names)-1}:0] done;"]
    top += [f" check_{name} u_case_{index}(.done(done[{index}]));" for index, name in enumerate(names)]
    top += [" initial begin", "  wait(&done);",
            f'  $display("STREAM_STRUCTURE_PASS helpers={len(names)} checks={len(names)*4096*3}");',
            "  $finish;", " end", "endmodule"]
    bench.write_text("\n\n".join(modules) + "\n" + "\n".join(top) + "\n")
    helper = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))
    helper_sources = helper["with_dependencies"]([ROOT / STREAM.parent / (name + ".sv") for name in names], ROOT)
    binary = out / "four_state.vvp"
    invoke(["iverilog", "-g2012", "-I"+str(ROOT / "include"), "-s", "tb", "-o", binary,
            *helper_sources, reference_file, bench], out / "four_state.compile.log")
    invoke(["vvp", binary], out / "four_state.log")
    if "STREAM_STRUCTURE_PASS" not in (out / "four_state.log").read_text():
        raise RuntimeError("辅助模块四态比较未完成")
    for mapping in hashes.values():
        if any(digest(path) != value for path, value in mapping.items()):
            raise RuntimeError("验证期间输入源码发生变化")
    report = {"passed": True, "profiles": results, "helpers": bodies,
              "four_state_checks": len(names)*4096*3, "source_sha256": hashes,
              "all_public_inputs_unconstrained": True, "all_public_outputs_compared": True,
              "source_unchanged": True}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"passed": True, "helpers": len(names), "four_state_checks": report["four_state_checks"]}), flush=True)


if __name__ == "__main__":
    main()
