#!/usr/bin/env python3
"""验证实际请求地址归并电路的两态等价关系与四态选择语义。"""
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

from check_request_qualification import control_module

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = Path("rtl/npu/conv/conv_im2col_frontend.sv")
STREAM = Path("rtl/npu/conv/conv_im2col_stream.sv")
DESCRIPTOR = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
SAMPLES = 12288
CONTEXT_INPUTS = {
    "state": 27, "chunk_reaches_end": 1, "row_last_q": 1,
    "row_base_valid": 1, "geometry_tile": 1, "next_row_padding": 1,
    "next_row_word_hit": 1, "group_end_o_equal": 1,
}
INPUTS = {
    "request_tap_context": 1, "incoming_context": 1, "request_row_context": 1,
    "request_stream_context": 1, "request_row_metadata_context": 1,
    "incoming_pixel_select": 10, "incoming_address_candidates": 320,
    "next_tap_addr": 32, "next_row_addr": 32, "stream_request_addr": 32,
    "addr": 32, "unknown_incoming_addr": 32,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def region(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def assignment(source, name):
    match = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if match is None:
        raise ValueError(f"Cannot find assignment: {name}")
    return match.group()


def declarations(direction="input "):
    result = []
    for name, width in INPUTS.items():
        shape = " [9:0][31:0]" if name == "incoming_address_candidates" else \
            f" [{width-1}:0]" if width > 1 else ""
        result.append(direction + "logic" + shape + " " + name)
    return result


def validate_descriptor(source):
    required = (
        "assign o_incoming_address_candidates[candidate] = address_value[0];",
        "assign o_incoming_pixel_select = prepared_word_select;",
        "assign incoming_data_candidate[candidate] = {coordinate_x, coordinate_y, pixel_value, address_value};",
        "{o_incoming_ix, o_incoming_iy, o_incoming_pixel, incoming_group_base, o_incoming_addr} = incoming_data_selected;",
        "(incoming_data_candidate[2*pair] & {p_incoming_data_width{prepared_word_select[2*pair]}})",
        "(incoming_data_candidate[2*pair+1] & {p_incoming_data_width{prepared_word_select[2*pair+1]}})",
    )
    for expected in required:
        if expected not in source:
            raise ValueError("Descriptor address candidate relationship changed: " + expected)


def context_model(frontend, stream):
    statements = "\n".join(assignment(stream, name) for name in
        ("stream_context", "row_request_eligible", "o_request_stream_context",
         "o_request_row_context", "o_request_tap_context"))
    statements = re.sub(r"\b[io]_(\w+)\b", lambda found: found[1], statements)
    ports = ["input logic" + (f" [{width-1}:0]" if width > 1 else "") + " " + name
             for name, width in CONTEXT_INPUTS.items()]
    return "module context_proof #(parameter bit REGISTER_ROW_ADDRESS=0, REGISTER_CACHE_REQUEST=1)(\n" + \
        ",\n".join(ports) + ''', output logic equivalent);
 import conv_im2col_frontend_pkg::*;
 localparam bit p_register_row_address=REGISTER_ROW_ADDRESS;
 localparam bit p_register_cache_request=REGISTER_CACHE_REQUEST;
 logic stream_context,row_request_eligible;
 logic request_stream_context,request_row_context,request_tap_context,request_row_metadata_context;
''' + statements + "\n" + assignment(frontend, "request_row_metadata_context") + '''
 assign equivalent=!(request_tap_context && request_row_metadata_context) &&
     (!request_row_context || request_row_metadata_context);
endmodule
'''


def model(frontend, stream):
    actual = region(frontend, "  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_address",
                    "  // 请求来源先确定候选资格")
    reference = assignment(stream, "o_cache_req_addr")
    reference = re.sub(r"\b[io]_(\w+)\b", lambda found: found[1], reference)
    reference = re.sub(r"\bcache_req_addr\b", "cache_req_addr_reference", reference)
    reference = re.sub(r"\bstream_context\b", "request_stream_context", reference)
    helpers = '(* keep_hierarchy = "yes" *)\n' + control_module(frontend, "conv_im2col_address_sources") + "\n" \
        if "module conv_im2col_address_sources" in frontend else ""
    return helpers + "module proof #(parameter bit REGISTER_DESCRIPTOR=0)(\n" + ",\n".join(declarations()) + ''',
 output logic equivalent, output logic context_valid,
 output logic [63:0] actual_value, expected_value);
 logic [31:0] incoming_addr, incoming_address_selected;
 logic [31:0] cache_req_addr,cache_req_addr_reference,request_address_value,request_address_reference;
''' + "assign incoming_address_selected=" + " | ".join(
        f"(incoming_address_candidates[{i}] & {{32{{incoming_pixel_select[{i}]}}}})"
        for i in range(10)) + ''';
 // 二态候选满足描述符的实际归并关系；未知候选允许任意四态参考地址。
 always_comb begin
   incoming_addr=unknown_incoming_addr;
   case (^{incoming_pixel_select,incoming_address_candidates})
     1'b0,1'b1: incoming_addr=incoming_address_selected;
     default: ;
   endcase
 end
''' + reference + "\n" + assignment(frontend, "request_address_reference") + "\n" + actual + '''
 assign actual_value={cache_req_addr,request_address_value};
 assign expected_value={cache_req_addr_reference,request_address_reference};
 assign equivalent=actual_value===expected_value;
 assign context_valid=!(request_tap_context && request_row_metadata_context) &&
     (!request_row_context || request_row_metadata_context);
endmodule
'''


def bench(registered):
    total = sum(INPUTS.values())
    padded = (total + 31) // 32 * 32
    return "module tb;\n" + ";\n".join(declarations("")) + f''';
 logic equivalent,context_valid;logic [63:0] actual_value,expected_value;
 logic [{padded-1}:0] pattern;
 logic [4:0] context_value;
 logic [319:0] candidate_bits;
 proof #(.REGISTER_DESCRIPTOR({registered})) dut(.*);
 initial begin
  for(integer sample=0;sample<{SAMPLES};sample++)begin
   for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
''' + "   {" + ",".join(INPUTS) + "}=pattern;\n" + '''
   for(integer context_index=0;context_index<5;context_index++)begin
     case ((sample>>(2*context_index))&3)
       0:context_value[context_index]=1'b0;
       1:context_value[context_index]=1'b1;
       2:context_value[context_index]=1'bx;
       3:context_value[context_index]=1'bz;
     endcase
   end
   {request_tap_context,incoming_context,request_row_context,
     request_stream_context,request_row_metadata_context}=context_value;
   case (^context_value)
     1'b0,1'b1: begin
       if(request_row_metadata_context)request_tap_context=1'b0;
       else request_row_context=1'b0;
     end
     default: ;
   endcase
   incoming_pixel_select=10'b1<<((sample/1024)%10);
   if(sample%13==0)incoming_pixel_select='0;
   if(sample%17==0)incoming_pixel_select='1;
   if(sample%19==0)incoming_pixel_select[sample%10]=1'bx;
   if(sample%23==0)incoming_pixel_select[sample%10]=1'bz;
   candidate_bits=incoming_address_candidates;
   if(sample%29==0)candidate_bits[sample%320]=1'bx;
   if(sample%31==0)candidate_bits[sample%320]=1'bz;
   incoming_address_candidates=candidate_bits;
   if(sample%37==0)next_row_addr[sample%32]=1'bx;
   if(sample%41==0)next_tap_addr[sample%32]=1'bz;
   if(sample%43==0)stream_request_addr[sample%32]=1'bx;
   if(sample%47==0)addr[sample%32]=1'bz;
   if(sample%53==0)unknown_incoming_addr[sample%32]=1'bx;
   #1;
   if(equivalent!==1'b1)$fatal(1,"Address selection mismatch sample=%0d actual=%h expected=%h",sample,actual_value,expected_value);
  end
''' + f'  $display("REQUEST_ADDRESS_FOUR_STATE_PASS checks={SAMPLES}");\n' + \
        "  $finish;\n end\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root / p for p in (FRONTEND, STREAM, DESCRIPTOR, Path("rtl/common/onehot_mux.sv"))]
    sources.append(root / "rtl/npu/conv/conv_im2col_frontend_pkg.sv")
    sources.append(Path(__file__).resolve())
    sources.append(Path(__file__).with_name("check_request_qualification.py"))
    hashes = {str(p): digest(p) for p in sources}
    validate_descriptor(sources[2].read_text())
    generated = out / "model.sv"
    generated.write_text(model(sources[0].read_text(), sources[1].read_text()).replace("always_comb", "always @*"))
    context_source = out / "context_model.sv"
    context_source.write_text(context_model(sources[0].read_text(), sources[1].read_text()))
    context_results = []
    for row in (0, 1):
        for request in (0, 1):
            name = f"context_row{row}_request{request}"
            script, formal = out / (name + ".ys"), out / (name + ".log")
            script.write_text(f"read_slang --top context_proof -GREGISTER_ROW_ADDRESS={row} " +
                f"-GREGISTER_CACHE_REQUEST={request} " + shlex.join(map(str, (sources[4], context_source))) +
                "\nprep -top context_proof -flatten\ncheck -assert\n" +
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with formal.open("w") as output:
                subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                               stdout=output, stderr=subprocess.STDOUT, check=True, timeout=180)
            if formal.read_text().count("SAT proof finished - no model found: SUCCESS!") != 1:
                raise RuntimeError(str(formal))
            context_results.append({"register_row_address": row, "register_cache_request": request,
                                    "formal_partitions": 1, "formal_sha256": digest(formal), "passed": True})
    results = []
    for registered in (0, 1):
        name = f"descriptor{registered}"
        script, formal, testbench, binary, build, simulation = (
            out / (name + suffix) for suffix in (".ys", ".formal.log", ".sv", ".vvp", ".build.log", ".four_state.log"))
        script.write_text(f"read_slang --top proof -GREGISTER_DESCRIPTOR={registered} " +
            shlex.join(map(str, (sources[3], generated))) +
            "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n" +
            "prep -top proof -flatten\ncheck -assert\n" +
            "sat -verify -set context_valid 1 -prove equivalent 1 -show-inputs -show-outputs\n")
        with formal.open("w") as output:
            subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           stdout=output, stderr=subprocess.STDOUT, check=True, timeout=180)
        if formal.read_text().count("SAT proof finished - no model found: SUCCESS!") != 1:
            raise RuntimeError(str(formal))
        testbench.write_text(bench(registered))
        with build.open("w") as output:
            subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                            *map(str, (sources[3], generated, testbench))],
                           stdout=output, stderr=subprocess.STDOUT, check=True, timeout=120)
        with simulation.open("w") as output:
            subprocess.run([args.vvp, str(binary)], stdout=output, stderr=subprocess.STDOUT, check=True, timeout=300)
        if f"REQUEST_ADDRESS_FOUR_STATE_PASS checks={SAMPLES}" not in simulation.read_text():
            raise RuntimeError(str(simulation))
        results.append({"register_descriptor": registered, "formal_partitions": 1,
                        "four_state_checks": SAMPLES, "formal_sha256": digest(formal),
                        "four_state_sha256": digest(simulation), "passed": True})
        print("REQUEST_ADDRESS_PASS", name, flush=True)
    if hashes != {str(p): digest(p) for p in sources}:
        raise RuntimeError("Sources changed during verification")
    (out / "summary.json").write_text(json.dumps({"passed": True, "source_sha256": hashes,
        "address_bits": 64, "context_cases": context_results, "cases": results,
        "domain": "Production context assignments prove that row and tap contexts are mutually exclusive and that row requests imply the row metadata context, for all binary states and parameter combinations. Address equivalence then covers every context satisfying those relations, every address, and zero, one or multiple selected descriptor candidates. Four-state checks enumerate the five context signals with valid binary contexts and exercise unknown selectors and address bits."}, indent=2) + "\n")


if __name__ == "__main__":
    main()
