#!/usr/bin/env python3
"""比较缓存请求资格的全部输入，并检查实际组合模块的参数和连接。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
STREAM = Path("rtl/npu/conv/conv_im2col_stream.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assignment(source, name):
    found = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if found is None:
        raise ValueError(f"缺少赋值：{name}")
    return found.group()


def control_module(source, module_name):
    found = re.search(r"\bmodule\s+" + re.escape(module_name) + r"\b.*?\bendmodule\b", source, re.S)
    if found is None:
        raise ValueError(f"缺少组合模块：{module_name}")
    return found.group()


def control_instance(source, module_name, instance_name):
    found = re.search(r"\b" + re.escape(module_name) + r"\s*(?:#\((.*?)\)\s*)?" +
                      re.escape(instance_name) + r"\s*\((.*?)\);", source, re.S)
    if found is None:
        raise ValueError(f"缺少组合实例：{instance_name}")
    return found


def inline_control(source, module_name, instance_name):
    """从实际模块和命名连接生成相同组合表达式，供局部四态模型使用。"""
    if module_name == "conv_im2col_request_control" and "module conv_im2col_descriptor_request" in source:
        source = inline_control(source, "conv_im2col_descriptor_request", "u_descriptor_request")
    module = control_module(source, module_name)
    instance = control_instance(source, module_name, instance_name)
    connections = dict(re.findall(r"\.(\w+)\s*\((.*?)\)\s*(?=,|$)",
                                  (instance[1] or "") + "," + instance[2], re.S))
    header, body = module.split(");", 1)
    ports = set(re.findall(r"\b[io]_\w+\b", header))
    parameters = set(re.findall(r"parameter\s+(?:int|bit)(?:\s+unsigned)?\s+(p_\w+)", header))
    if set(connections) != ports | parameters:
        raise ValueError(f"组合模块连接不完整：{module_name}")
    body = body[:body.rindex("endmodule")]
    body = re.sub(r"\b(?:" + "|".join(map(re.escape, connections)) + r")\b",
                  lambda match: connections[match[0]].strip() if match[0].startswith("o_") else
                  "(" + connections[match[0]].strip() + ")", body)
    return source[:instance.start()] + body + source[instance.end():]


def model(current, reference):
    helper = control_module(current, "conv_im2col_request_control")
    if "module conv_im2col_descriptor_request" in current:
        helper += "\n" + control_module(current, "conv_im2col_descriptor_request")
    instance = control_instance(current, "conv_im2col_request_control", "u_request_control").group()
    reference_logic = "\n".join(assignment(reference, name) for name in (
        "incoming_request", "o_cache_req_valid"))
    replacements = {
        "o_current_word_hit": "i_current_word_hit",
        "o_incoming_word_hit": "i_incoming_word_hit",
        "stream_request_eligible": "i_stream_request_eligible",
        "row_request_eligible": "i_row_request_eligible",
        "stream_tap_selected": "i_tap_selected",
    }
    for old, new in replacements.items():
        instance = re.sub(r"\b" + old + r"\b", new, instance)
        reference_logic = re.sub(r"\b" + old + r"\b", new, reference_logic)
    for expression in (instance, reference_logic):
        if "i_state[$clog2(FETCH)]" not in expression:
            raise ValueError("缺少 FETCH 状态输入")
    instance = instance.replace("i_state[$clog2(FETCH)]", "i_fetch")
    reference_logic = reference_logic.replace("i_state[$clog2(FETCH)]", "i_fetch")
    reference_logic = reference_logic.replace("o_cache_req_valid", "expected_request")
    return helper + '''
module proof #(
 parameter int p_size=16, p_rw=$clog2(p_size+1),
 parameter bit p_register_descriptor=0
)(
 input logic i_tile_valid,i_tile_ready,i_incoming_fast,i_incoming_padding,i_incoming_word_hit,
 input logic[p_rw-1:0]i_tile_rows,i_tile_cols,
 input logic i_tile_q_before_end,i_tile_rows_in_range,i_fetch,i_current_word_hit,
 input logic i_wr_valid,i_wr_ready,i_stream_request_eligible,i_row_request_eligible,i_tap_selected,
 output logic o_cache_req_valid,expected_request,equivalent
);
 logic incoming_request,o_stream_next_request,o_next_row_request;
 assign o_stream_next_request=i_wr_valid&&i_wr_ready&&i_stream_request_eligible;
 assign o_next_row_request=i_wr_valid&&i_wr_ready&&i_row_request_eligible;
''' + instance + "\n" + reference_logic + '''
 assign equivalent=o_cache_req_valid===expected_request;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / STREAM
    current = source.read_text()
    reference = read_reference_file(root, args.reference_ref, str(STREAM), text=True)
    generated = out / "request_qualification.sv"
    generated.write_text(model(current, reference).replace("always_comb", "always @*"))
    hashes = {str(path): digest(path) for path in (source, generated, Path(__file__).resolve())}
    rows = []
    for size in (4, 8, 16, 32):
        for registered in (0, 1):
            name = f"size{size}_descriptor{registered}"
            script, log = out / (name + ".ys"), out / (name + ".formal.log")
            script.write_text(f"read_slang --top proof -Gp_size={size} -Gp_register_descriptor={registered} " +
                shlex.quote(str(generated)) + "\nprep -top proof -flatten\ncheck -assert\n"
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log.open("w") as handle:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                               stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=120)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError(str(log))
            bench = out / (name + ".sv")
            bench.write_text('''module tb;
 localparam int p_size=''' + str(size) + ''',p_rw=$clog2(p_size+1);
 logic i_tile_valid,i_tile_ready,i_incoming_fast,i_incoming_padding,i_incoming_word_hit;
 logic[p_rw-1:0]i_tile_rows,i_tile_cols;
 logic i_tile_q_before_end,i_tile_rows_in_range,i_fetch,i_current_word_hit;
 logic i_wr_valid,i_wr_ready,i_stream_request_eligible,i_row_request_eligible,i_tap_selected;
 logic o_cache_req_valid,expected_request,equivalent;
 logic[31:0]pattern;
 proof #(.p_size(p_size),.p_register_descriptor(''' + str(registered) + '''))dut(.*);
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
   pattern=$urandom;
   if(sample%3==0)pattern[(sample/3)%32]=1'bx;
   if(sample%5==0)pattern[(sample/5)%32]=1'bz;
   {i_tile_valid,i_tile_ready,i_incoming_fast,i_incoming_padding,i_incoming_word_hit,
    i_tile_q_before_end,i_tile_rows_in_range,i_fetch,i_current_word_hit,
    i_wr_valid,i_wr_ready,i_stream_request_eligible,i_row_request_eligible,i_tap_selected,
    i_tile_rows,i_tile_cols}=pattern;
   #1;
   if(equivalent!==1'b1)$fatal(1,"Request mismatch sample=%0d actual=%b expected=%b pattern=%h",
       sample,o_cache_req_valid,expected_request,pattern);
  end
  $display("REQUEST_QUALIFICATION_FOUR_STATE_PASS checks=65536");$finish;
 end
endmodule
''')
            binary, build, simulation = out / (name + ".vvp"), out / (name + ".build.log"), out / (name + ".run.log")
            with build.open("w") as handle:
                subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary), str(generated), str(bench)],
                               stdout=handle, stderr=subprocess.STDOUT, check=True)
            with simulation.open("w") as handle:
                subprocess.run([args.vvp, str(binary)], stdout=handle, stderr=subprocess.STDOUT,
                               check=True, timeout=60)
            if "REQUEST_QUALIFICATION_FOUR_STATE_PASS checks=65536" not in simulation.read_text():
                raise RuntimeError(str(simulation))
            rows.append(dict(size=size, register_descriptor=registered, formal_passed=True,
                             four_state_checks=65536, formal_log_sha256=digest(log),
                             simulation_log_sha256=digest(simulation)))
            print("REQUEST_QUALIFICATION_PASS", name, flush=True)
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError("验证期间源码发生变化")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, source_sha256=hashes,
        reference_ref=args.reference_ref, reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        sources_unchanged=True, cases=rows, inputs_constrained=False), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
