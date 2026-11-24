#!/usr/bin/env python3
"""验证模加匹配、活动列数和历史行末比较的完整输入关系。"""
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
ADD = Path("rtl/common/add_equal.sv")
DESCRIPTOR = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
GEOMETRY = Path("rtl/npu/conv/conv_im2col_geometry.sv")
CHECKS = 8192


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def section(source, first, last):
    begin = source.index(first)
    return source[begin:source.index(last, begin)]


def module(source, name):
    found = re.search(r"\bmodule\s+" + re.escape(name) + r"\b.*?\bendmodule", source, re.S)
    if found is None:
        raise ValueError("Missing production module: " + name)
    return '(* keep_hierarchy = "yes" *)\n' + found.group()


def declarations(inputs, direction=""):
    return [direction + "logic " + (f"[{width-1}:0] " if width > 1 else "") + name
            for name, width in inputs.items()]


def proof_text(inputs, width, body):
    return "module proof(\n" + ",\n".join(declarations(inputs, "input ") +
        ["output logic equivalent", f"output logic [{width-1}:0] actual_value,expected_value"]) + ");\n" + \
        body + "\nassign equivalent=actual_value===expected_value;\nendmodule\n"


def add_model(width, preserve):
    inputs = {"i_a": width, "i_b": width, "i_target": width, "i_carry_in": 1}
    body = f'''add_equal #(.p_width({width}),.p_preserve_bits({preserve})) actual (
 .i_a(i_a),.i_b(i_b),.i_target(i_target),.i_carry_in(i_carry_in),.o_equal(actual_value));
reference_add_equal #(.p_width({width}),.p_preserve_bits({preserve})) expected (
 .i_a(i_a),.i_b(i_b),.i_target(i_target),.i_carry_in(i_carry_in),.o_equal(expected_value));
'''
    return inputs, 1, proof_text(inputs, 1, body), "if(sample%4==0)i_target=i_a+i_b+i_carry_in;"


def active_function(source, name, reference):
    body = section(source, "  if (p_tile_count_w < 32) begin : g_prepared_active_columns",
                   "  assign prepared_group_i_a")
    if reference:
        body = re.sub(r"\badd_equal\b", "reference_add_equal", body)
    return f'''module {name} #(parameter int p_tile_count_w=5)(
 input logic [31:0] i_reduction_len,descriptor_reduction,
 input logic [p_tile_count_w-1:0] descriptor_columns,
 output logic [p_tile_count_w-1:0] prepared_active_columns,
 output logic [16:0] allowed);
{body}
for(genvar lane=0;lane<=16;lane++)begin:g_lane
 assign allowed[lane]=p_tile_count_w'(lane)<prepared_active_columns;
end
endmodule
'''


def active_model(width, current, reference):
    inputs = {"i_reduction_len": 32, "descriptor_reduction": 32, "descriptor_columns": width}
    body = f'''active_current #(.p_tile_count_w({width})) actual (
 .i_reduction_len(i_reduction_len),.descriptor_reduction(descriptor_reduction),
 .descriptor_columns(descriptor_columns),.prepared_active_columns(actual_value[{width-1}:0]),
 .allowed(actual_value[{width+16}:{width}]));
active_reference #(.p_tile_count_w({width})) expected (
 .i_reduction_len(i_reduction_len),.descriptor_reduction(descriptor_reduction),
 .descriptor_columns(descriptor_columns),.prepared_active_columns(expected_value[{width-1}:0]),
 .allowed(expected_value[{width+16}:{width}]));
'''
    model = active_function(current, "active_current", False) + \
        active_function(reference, "active_reference", True) + proof_text(inputs, width+17, body)
    directed = f'''if(sample%4==0)i_reduction_len=descriptor_reduction+32'({width}'(sample));
if(sample%4==1)i_reduction_len=descriptor_reduction-32'({width}'(sample));
if(sample%8==2)descriptor_columns='0;
'''
    return inputs, width+17, model, directed


def history_function(source, name, reference):
    body = section(source, "  assign p_sum_wrap_i_a =", "  always_comb begin\n    history_result.valid =")
    expression = re.search(r"history_result\.wrap\s*=\s*(.*?);", source, re.S)
    if expression is None:
        raise ValueError("Missing history row-end expression")
    if reference:
        body = re.sub(r"\badd_equal\b", "reference_add_equal", body)
    return f'''module {name}(
 input logic [15:0] i_last_x,history_delta,p_wrap_target_q,o_last_output_col_q,output_width,
 output logic o_wrap);
 typedef struct packed {{logic [15:0] output_w;}} configuration_t;
 configuration_t i_c;
 logic [32:0] p_history_delta_q;
 logic [15:0] p_sum_wrap_i_a,p_sum_wrap_i_b,p_sum_wrap_i_target;
 logic [15:0] p_sum_last_i_a,p_sum_last_i_b,p_sum_last_i_target;
 logic unused_p_sum_wrap_carry,p_sum_wrap_i_carry_in,p_sum_last_i_carry_in;
 logic p_sum_wrap_o_equal,p_sum_last_o_equal;
 assign i_c.output_w=output_width;
 assign p_history_delta_q={{17'd0,history_delta}};
{body}
 assign o_wrap={expression[1]};
endmodule
'''


def history_model(current, reference):
    inputs = {name: 16 for name in
              ("i_last_x", "history_delta", "p_wrap_target_q", "o_last_output_col_q", "output_width")}
    body = "history_current actual(.o_wrap(actual_value),.*);\nhistory_reference expected(.o_wrap(expected_value),.*);"
    model = history_function(current, "history_current", False) + \
        history_function(reference, "history_reference", True) + proof_text(inputs, 1, body)
    return inputs, 1, model, '''if(sample%4==0)p_wrap_target_q=i_last_x+history_delta;
if(sample%4==1)o_last_output_col_q=i_last_x+history_delta;
'''


def bench(inputs, width, directed):
    bits = sum(inputs.values())
    padded = (bits+31)//32*32
    return "module tb;\n" + ";\n".join(declarations(inputs)) + f''';
logic equivalent;
logic [{width-1}:0] actual_value,expected_value;
logic [{padded-1}:0] pattern;
logic [{bits-1}:0] applied,seen_x='0,seen_z='0;
integer known_nonzero=0,known_zero=0;
proof dut(.*);
initial begin
 for(integer sample=0;sample<{CHECKS};sample++)begin
  for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
''' + "  {" + ",".join(inputs) + "}=pattern;\n" + directed + \
        "  applied={" + ",".join(inputs) + "};\n" + f'''
  if(sample%3==0)applied[(sample/3)%{bits}]=1'bx;
  if(sample%5==0)applied[(sample/5)%{bits}]=1'bz;
''' + "  {" + ",".join(inputs) + "}=applied;\n" + f'''
  for(integer bit_index=0;bit_index<{bits};bit_index++)begin
   if(applied[bit_index]===1'bx)seen_x[bit_index]=1'b1;
   if(applied[bit_index]===1'bz)seen_z[bit_index]=1'b1;
  end
  #1;
  if(equivalent!==1'b1)$fatal(1,"Comparison mismatch sample=%0d actual=%h expected=%h inputs=%h",
    sample,actual_value,expected_value,applied);
  if(actual_value==='0)known_zero++;
  if((^actual_value)!==1'bx&&actual_value!='0)known_nonzero++;
 end
 if(seen_x!=='1||seen_z!=='1)$fatal(1,"Incomplete X/Z coverage");
 if(known_nonzero<20||known_zero<20)$fatal(1,"Incomplete result coverage positive=%0d zero=%0d",known_nonzero,known_zero);
 $display("FRONTEND_COMPARISONS_FOUR_STATE_PASS checks={CHECKS} input_bits={bits} positive=%0d zero=%0d",known_nonzero,known_zero);
 $finish;
end
endmodule
'''


def mapping_wrapper(inputs, width, selected):
    ports = declarations(inputs, "input ")
    registers = ";\n".join(declarations({name+"_q": bits for name, bits in inputs.items()}))
    assignments = "\n".join(name+"_q <= "+name+";" for name in inputs)
    connections = ",".join("."+name+"("+name+"_q)" for name in inputs)
    return "module comparison_mapping(input logic clk,\n" + ",\n".join(ports) + f''',
output logic [{width-1}:0] o_value);
{registers};
logic [{width-1}:0] actual_value,expected_value;
logic unused_equivalent;
proof dut({connections},.equivalent(unused_equivalent),.actual_value(actual_value),.expected_value(expected_value));
always_ff @(posedge clk)begin
{assignments}
 o_value <= {selected}_value;
end
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
    paths = [ADD, DESCRIPTOR, GEOMETRY, Path("rtl/common/increment_equal.sv")]
    parallel = root/"rtl/common/parallel_unsigned_compare.sv"
    if parallel.exists():
        paths.append(parallel.relative_to(root))
    hashes = {str(root/path): digest(root/path) for path in paths}
    hashes[str(Path(__file__).resolve())] = digest(__file__)
    current = {path: (root/path).read_text() for path in paths}
    previous = {path: read_reference_file(root, args.reference_ref, str(path), text=True) for path in (ADD, DESCRIPTOR, GEOMETRY)}
    reference_add = out/"reference_add_equal.sv"
    reference_add.write_text(re.sub(r"\badd_equal\b", "reference_add_equal", previous[ADD]))
    descriptor_helper = out/"descriptor_match.sv"
    descriptor_helper.write_text(module(current[DESCRIPTOR], "conv_descriptor_match"))
    support = [root/ADD, root/"rtl/common/increment_equal.sv", reference_add, descriptor_helper]
    if "module conv_history_wrap_select" in current[GEOMETRY]:
        history_helper = out/"history_wrap_select.sv"
        history_helper.write_text(module(current[GEOMETRY], "conv_history_wrap_select"))
        support.append(history_helper)
    if parallel.exists():
        support.append(parallel)
    specifications = [(f"add_width{width}_preserve{preserve}", add_model(width, preserve))
                      for width in (1, 2, 3, 4, 5, 8, 16, 27, 29, 32, 33, 64) for preserve in (0, 1)]
    specifications += [(f"active_width{width}", active_model(width, current[DESCRIPTOR], previous[DESCRIPTOR]))
                       for width in (1, 2, 3, 4, 5, 6, 8, 16, 31, 32)]
    specifications.append(("history_wrap", history_model(current[GEOMETRY], previous[GEOMETRY])))
    cases, mapping_cases = [], {}
    for name, (inputs, width, text, directed) in specifications:
        generated = out/(name+"_model.sv")
        generated.write_text(text.replace("always_comb", "always @*"))
        script, log, tb, binary, build, simulation = [out/(name+suffix) for suffix in
            (".ys", ".formal.log", ".sv", ".vvp", ".build.log", ".four_state.log")]
        script.write_text("read_slang -DSYNTHESIS --top proof " + shlex.join(map(str, support+[generated])) +
            "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
            "prep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as handle:
            subprocess.run([sys.executable, str(root/"scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=180)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        tb.write_text(bench(inputs, width, directed))
        with build.open("w") as handle:
            subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                *map(str, support+[generated, tb])], stdout=handle, stderr=subprocess.STDOUT, check=True)
        with simulation.open("w") as handle:
            subprocess.run([args.vvp, str(binary)], stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=120)
        if "FRONTEND_COMPARISONS_FOUR_STATE_PASS" not in simulation.read_text():
            raise RuntimeError(str(simulation))
        binary.unlink()
        cases.append(dict(name=name,formal_passed=True,four_state_checks=CHECKS,input_bits=sum(inputs.values()),
                          all_input_bits_x_z=True,model_sha256=digest(generated),
                          formal_log_sha256=digest(log),simulation_log_sha256=digest(simulation)))
        if name in ("add_width32_preserve1", "active_width5", "history_wrap"):
            for kind in ("actual", "expected"):
                wrapper = out/(name+"_"+kind+"_mapping.sv")
                wrapper.write_text(mapping_wrapper(inputs, width, kind))
                mapping_cases[name+"_"+kind] = dict(top="comparison_mapping",options=["-D", "SYNTHESIS=1"],
                    sources=list(map(str,support+[generated,wrapper])),configuration="Registered complete combinational comparison")
        print("FRONTEND_COMPARISONS_PASS", name, flush=True)
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError("检查期间源码发生变化")
    (out/"mapping_cases.json").write_text(json.dumps(mapping_cases,indent=2)+"\n")
    report = dict(passed=True,source_sha256=hashes,sources_unchanged=True,reference_ref=args.reference_ref,
        reference_sha256={str(path):hashlib.sha256(value.encode()).hexdigest() for path,value in previous.items()},
        inputs_constrained=False,cases=cases,mapping_cases=str(out/"mapping_cases.json"))
    (out/"summary.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")


if __name__ == "__main__":
    main()
