#!/usr/bin/env python3
"""验证原查询边沿保存字段后的请求范围、字地址和快照匹配。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from rtl_source_view import read_sources, module_definition, request_module, controller_module, source_manifest
import re
import runpy
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")
sys.path.insert(0, str(ROOT / "test/conv_frontend/tools"))
from check_state_context import Statements

PORTS = """input logic clk,
input logic [1:0] fg_state,
input logic req_fire,lookup_input_valid,preview_source_select,bypass_q,request_count,
input logic [31:0] head_address,request_address,preview_address,work_address,demand_addr,
input logic [SI-1:0] head_set,request_set,preview_set,demand_set,demand_fill_set,
input logic head_range,request_range,
input logic [31:0] base_q,end_q"""
NAMES = ("fg_state", "req_fire", "lookup_input_valid", "preview_source_select", "bypass_q",
         "request_count", "head_address", "request_address", "preview_address", "work_address",
         "demand_addr", "head_set", "request_set", "preview_set", "demand_set", "demand_fill_set",
         "head_range", "request_range", "base_q", "end_q")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expression(source: str, name: str) -> str:
    found = re.findall(r"\b" + re.escape(name) + r"\s*<=\s*(.*?);", source, re.S)
    if len(found) != 1:
        raise RuntimeError("寄存器表达式数量不符：" + name)
    return found[0]


def model(name: str, source: str, retimed: bool) -> str:
    source = request_module(source)
    start = source.index("  assign lookup_head_matches =")
    end = source.index("  if (DEMAND_DEPTH == 1) begin : g_direct_snapshot_fields", start) if retimed else \
        source.index("  // 地址范围结果随接收描述保存", start)
    comparisons = source[start:end]
    if "  if (DEMAND_DEPTH == 1) begin : g_direct_read_source" in source:
        start = source.index("  if (DEMAND_DEPTH == 1) begin : g_direct_read_source")
    else:
        start = source.index("  always_comb begin\n    lookup_read_request = request_count")
    end = source.index("  logic [3:0][31:2] lookup_candidate_word", start)
    read_source = source[start:end]
    body = comparisons + read_source
    body = body.replace("request_queue[DQ_AW'(request_head + DQ_AW'(1))]", "head_request")
    body = body.replace("request_queue[request_head]", "head_request")
    if "assign demand_word_matches_next" not in body:
        body += "\nassign demand_word_matches_next=" + expression(source, "demand_word_matches_q") + ";\n"
    if retimed:
        start = source.index("  if (DEMAND_DEPTH == 1) begin : g_direct_snapshot_fields")
        start = source.index("    logic [SI-1:0] expected_set;", start)
        end = source.index("  end else begin : g_queued_snapshot_fields", start)
        clocked = source[start:end].replace("request_queue[request_head]", "head_request")
        clocked = clocked.replace(".o_request(work_request)", ".o_request(updated_request)")
        clocked += """
  assign observed={updated_request.address,updated_request.set_index,updated_request.in_range,
      direct_response_snapshot_ready,work_snapshot_matches_q,work_word_matches_q,demand_word_matches_q};
"""
    else:
        clocked = """
  always_ff @(posedge clk)
    observed<={lookup_read_request.address,lookup_read_request.set_index,lookup_read_request.in_range,
        response_snapshot_ready,work_snapshot_matches_next,work_word_matches_next,demand_word_matches_next};
"""
    return f"""module {name} #(parameter integer SI=4)(
{PORTS},output logic [36+SI:0] observed);
  localparam integer DEMAND_DEPTH=1,DQ_CW=1,DQ_AW=1;
  localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
  typedef struct packed {{logic [31:0] address,epoch,retire,progress;
    logic [SI-1:0] set_index;logic geometry,event_first,in_range;}} demand_t;
  demand_t incoming_request,preview_request,work_request,lookup_input_request;
  demand_t head_request,lookup_read_request,updated_request;
  logic [SI-1:0] lookup_set,lookup_read_set;
  logic [31:2] lookup_read_word;
  logic [1:0] lookup_head_matches,lookup_input_matches,lookup_preview_matches,lookup_request_matches;
  logic lookup_next_work_match,lookup_idle_demand_match,lookup_idle_set_match,lookup_pop_work_match;
  logic work_word_matches_next,work_snapshot_matches_next,response_snapshot_ready,demand_word_matches_next;
  logic work_word_matches_q,work_snapshot_matches_q,demand_word_matches_q,direct_response_snapshot_ready;
  logic preview_below_base,preview_below_end,unused_base_equal,unused_end_equal,preview_range;
  unsigned_compare #(.p_width(32)) u_preview_base (
    .i_a(preview_address),.i_b(base_q),.o_less(preview_below_base),.o_equal(unused_base_equal));
  unsigned_compare #(.p_width(32)) u_preview_end (
    .i_a(preview_address),.i_b(end_q),.o_less(preview_below_end),.o_equal(unused_end_equal));
  assign preview_range=!preview_below_base&&preview_below_end;
  assign incoming_request={{request_address,96'd0,request_set,2'd0,request_range}};
  assign preview_request={{preview_address,96'd0,preview_set,2'd0,preview_range}};
  assign work_request={{work_address,96'd0,{{SI{{1'b0}}}},3'd0}};
  assign head_request={{head_address,96'd0,head_set,2'd0,head_range}};
  assign lookup_input_request=preview_source_select ? preview_request : incoming_request;
  assign lookup_set=bypass_q ? demand_fill_set : demand_set;
{body}
{clocked}
endmodule
"""


def support(source):
    names = ('conv_cache_snapshot_fields', 'conv_cache_snapshot_equal', 'conv_cache_registered_equal')
    return '\n'.join(module_definition(source, name) for name in names) + '\n'

def bench() -> str:
    declarations = PORTS.replace("input logic", "logic").replace(",\n", ";\n") + ";\n"
    return f"""module tb;
  localparam integer SI=8,W=233+5*SI;
  {declarations}
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'h82a631e9;
  logic [36+SI:0] expected,actual;
  integer checks=0;
  assign {{{','.join(NAMES)}}}=stimulus;
  reference #(.SI(SI)) u_reference(.*,.observed(expected));
  candidate #(.SI(SI)) u_candidate(.*,.observed(actual));
  function automatic logic value(input integer index);
    case(index)
      0:value=1'b0;
      1:value=1'b1;
      2:value=1'bx;
      3:value=1'bz;
    endcase
  endfunction
  task automatic tick;
    clk=0;#1;clk=1;#1;
    if(expected!==actual)
      $fatal(1,"SNAPSHOT_FIELDS_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
    clk=0;
  endtask
  initial begin
    clk=0;
    for(integer trial=0;trial<16;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      if(trial%4==2) begin
        for(integer index=1;index<5;index++)
          stimulus[66+5*SI+32*index+:32]=stimulus[66+5*SI+:32];
        for(integer index=1;index<5;index++)
          stimulus[66+SI*index+:SI]=stimulus[66+:SI];
      end
      saved=stimulus;
      for(integer controls=0;controls<16384;controls++) begin
        stimulus=saved;
        for(integer b=0;b<7;b++) stimulus[W-7+b]=value((controls>>(2*b))&3);
        tick();
      end
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;tick();
        stimulus=saved;stimulus[b]=1'bz;tick();
      end
      stimulus='x;tick();stimulus='z;tick();
    end
    $display("SNAPSHOT_FIELDS_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def run(command: list, log: Path, cwd: Path) -> None:
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def fill_set_model(name: str, source: str, retimed: bool) -> str:
    controller, request = controller_module(source), request_module(source)
    retimed = bool(re.search(r"assign\s+lookup_fill_set_match_q\s*=", request))
    if retimed:
        blocks = []
        for signal in ("fill_set", "lookup_snapshot_set"):
            source = controller if signal == "fill_set" else request
            writes = list(re.finditer(r"\b" + signal + r"\s*<=", source))
            if len(writes) != 1:
                raise RuntimeError("组号寄存器的实际写入次数不符：" + signal)
            start = source.rfind("always_ff", 0, writes[0].start())
            start = source.index("begin", start)

            def selected(statement: str) -> str:
                match = re.fullmatch(signal + r"\s*<=\s*(.*);", statement, re.S)
                return "selected_" + signal + " = " + match[1] + ";" if match else ""

            blocks.append(Statements(source[start:], select_assignment=selected).statement())
        match = re.search(r"assign\s+lookup_fill_set_match_q\s*=\s*(.*?);", request, re.S)
        if match is None:
            raise RuntimeError("缺少保存后组号比较表达式")
        comparison = match[1].replace("lookup_snapshot_set", "saved_lookup_set").replace(
            "fill_set", "saved_fill_set")
        body = """logic [SI-1:0] selected_fill_set,selected_lookup_snapshot_set;
  logic [SI-1:0] saved_fill_set,saved_lookup_set;
  always_comb begin
    selected_fill_set=fill_set;
    selected_lookup_snapshot_set=lookup_snapshot_set;
""" + "\n".join(blocks) + """
  end
  always_ff @(posedge clk) begin
    saved_fill_set<=selected_fill_set;
    saved_lookup_set<=selected_lookup_snapshot_set;
  end
  assign observed=""" + comparison + ";\n"
    else:
        source = request
        start = source.index("  if (DEMAND_DEPTH == 1) begin : g_saved_fill_match")
        start = source.index("always_comb begin", start) + len("always_comb ")

        def selected(statement: str) -> str:
            return statement if re.match(r"next_(fill|lookup)_set\s*=", statement) else ""

        block = Statements(source[start:], select_assignment=selected).statement()
        body = "logic [SI-1:0] next_fill_set,next_lookup_set;\nalways_comb " + block + \
            "\nalways_ff @(posedge clk) observed<=" + expression(source, "lookup_fill_set_match_q") + ";\n"
    return f"""module {name} #(parameter integer SI=8)(
  input logic clk,input logic [6+4*SI:0] stimulus,output logic observed);
  localparam logic [1:0] F_IDLE=0;
  logic rst_n,cfg_valid,cfg_ready,fill_success,bypass_q;
  logic [1:0] fill_state;
  logic [SI-1:0] fill_set,select_set,lookup_read_set,lookup_snapshot_set;
  assign {{rst_n,cfg_valid,cfg_ready,fill_state,fill_success,bypass_q,
           fill_set,select_set,lookup_read_set,lookup_snapshot_set}}=stimulus;
{body}
endmodule
"""


def check_fill_sets(root: Path, out: Path, current: str, original: str) -> dict:
    out.mkdir(exist_ok=True)
    modules = fill_set_model("reference", original, False) + fill_set_model("candidate", current, True)
    proof = out / "comparison.sv"
    proof.write_text(modules + """module comparison #(parameter integer SI=8)(
  input logic clk,input logic [6+4*SI:0] stimulus,output logic equivalent);
  logic expected,actual;
  reference #(.SI(SI)) u_reference(.*,.observed(expected));
  candidate #(.SI(SI)) u_candidate(.*,.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles = []
    for width in (1,4,8):
        script, log = out / f"width{width}.ys", out / f"width{width}.log"
        script.write_text(f"read_slang --top comparison -DSYNTHESIS=1 -GSI={width} " +
            shlex.quote(str(proof)) + "\nprep -top comparison -flatten\n"
            "sat -seq 2 -prove-skip 1 -verify -prove equivalent 1 -set-def-inputs -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("保存后组号比较的证明未完成")
        profiles.append(dict(sets=1<<width,passed=True,log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text(modules + """module tb;
  localparam integer SI=8,W=7+4*SI;
  logic clk,expected,actual;
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'h63814a7d;
  integer checks=0;
  reference #(.SI(SI)) u_reference(.*,.observed(expected));
  candidate #(.SI(SI)) u_candidate(.*,.observed(actual));
  function automatic logic value(input integer index);
    case(index)
      0:value=1'b0;1:value=1'b1;2:value=1'bx;3:value=1'bz;
    endcase
  endfunction
  task automatic check;
    clk=0;#1;clk=1;#1;
    if(expected!==actual)
      $fatal(1,"FILL_SET_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;clk=0;
  endtask
  initial begin
    clk=0;
    for(integer trial=0;trial<8;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      if(trial%4==2)
        for(integer index=1;index<4;index++) stimulus[index*SI+:SI]=stimulus[0+:SI];
      saved=stimulus;
      for(integer controls=0;controls<16384;controls++) begin
        stimulus=saved;
        for(integer b=0;b<7;b++) stimulus[W-7+b]=value((controls>>(2*b))&3);
        check();
      end
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus=saved;stimulus[b]=1'bz;check();
      end
      stimulus='x;check();stimulus='z;check();
    end
    $display("FILL_SET_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
""")
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", four],
        out / "four_state_compile.log", root)
    run(["vvp", out / "four_state.vvp"], out / "four_state.log", root)
    match = re.search(r"FILL_SET_FOUR_STATE_PASS checks=(\d+)", (out / "four_state.log").read_text())
    if not match or int(match[1]) != 131712:
        raise RuntimeError("保存后组号比较的四态检查数量不符")
    return dict(passed=True,sat_profiles=profiles,four_state_cases=int(match[1]),
        proof_sha256=digest(proof),four_state_log_sha256=digest(out / "four_state.log"))


def map_fields(root: Path, out: Path, proof: Path, sources: list[Path]) -> dict:
    cases = {label: dict(top=label,sources=[str(proof),*map(str,sources)],
        options=["-DSYNTHESIS=1","-GSI=4"],
        configuration="原查询边沿保存的字段及其完整范围和字地址比较")
        for label in ("reference","candidate")}
    case_file = out / "synthesis_cases.json"
    case_file.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+"\n")
    run([sys.executable,ROOT/"scripts/fpga/open_fpga_synth.py","--source-root",root,
         "--case-config",case_file,"--cases","reference","candidate","--out",out/"mapping",
         "--native-combinational-helpers"],out/"mapping.log",root)
    helper = runpy.run_path(str(ROOT/"test/conv_frontend/tools/measure_complete_paths.py"))
    records = {}
    for label in cases:
        folder = out/"mapping"/label
        module = json.loads((folder/"mapped.json").read_text())["modules"][label]
        report = helper["measure"](module)
        observed, counts = helper["add_interface_boundaries"](module)
        capture = {}
        for name, prefixes in (("preview_address",("preview_address",)),
                               ("input_addresses",("preview_address","request_address","head_address")),
                               ("source_control",("fg_state","request_count","req_fire","preview_source_select"))):
            starts, ends = set(), set()

            def begin(cell_name,cell,port):
                matched = any(cell_name.startswith("__measurement_interface__input:"+prefix+"[")
                              for prefix in prefixes)
                if matched:
                    starts.add((cell_name,port))
                return matched

            def finish(cell_name,cell,port):
                matched = not cell_name.startswith("__measurement_interface__")
                if matched:
                    ends.add((cell_name,port))
                return matched

            paths = helper["connected_paths"](observed,root_filter=begin,sink_filter=finish)
            if not paths["graph_complete"] or not starts or not ends:
                raise RuntimeError("查询字段保存的局部连接图不完整")
            capture[name] = dict(selected_start_ports=len(starts),selected_endpoint_ports=len(ends),
                maximum_combinational_cells=paths["longest_register_path_cells"],
                graph_complete=True,paths=paths["register_to_register_paths"])
        report["capture_scopes"] = capture
        report["top"] = label
        (folder/"complete_paths.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        records[label] = dict(graph_complete=report["graph_complete"],interface_bits=counts,
            path_groups={name:group["maximum_combinational_cells"] for name,group in report["path_groups"].items()},
            capture_scopes={name:{k:v for k,v in group.items() if k!="paths"} for name,group in capture.items()},
            resources=report["resources"],mapped_sha256=digest(folder/"mapped.json"),
            report_sha256=digest(folder/"complete_paths.json"))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="f1910d02")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map", action="store_true")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = read_sources(root, SOURCE)
    original = (read_sources(args.reference_root.resolve(), SOURCE) if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, SOURCE, text=True))
    modules = model("reference", original, "g_direct_snapshot_fields" in request_module(original)) + model("candidate", current, True) + support(current)
    proof = out / "comparison.sv"
    connections = ",".join(f".{name}({name})" for name in ("clk",*NAMES))
    proof.write_text(modules + f"""module comparison #(parameter integer SI=4)(
{PORTS},output logic equivalent);
  logic [36+SI:0] expected,actual;
  reference #(.SI(SI)) u_reference({connections},.observed(expected));
  candidate #(.SI(SI)) u_candidate({connections},.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    sources = [root / "rtl/common/onehot_mux.sv", root / "rtl/common/unsigned_compare.sv"]
    profiles = []
    for width in (1,4,8):
        script, log = out / f"width{width}.ys", out / f"width{width}.log"
        commands = [f"read_slang --top comparison -DSYNTHESIS=1 -GSI={width} " +
                    shlex.join(map(str,[*sources,proof])), "prep -top comparison -flatten"]
        # 七个二值来源控制完整枚举；每个组合中的全部地址、组号和范围输入保持自由。
        for controls in range(128):
            values = {"fg_state": controls & 3}
            for bit, name in enumerate(("req_fire", "lookup_input_valid", "preview_source_select",
                                        "bypass_q", "request_count"), start=2):
                values[name] = (controls >> bit) & 1
            settings = " ".join(f"-set-at 1 {name} {value}" for name, value in values.items())
            commands.append("sat -seq 2 -prove-skip 1 -verify -prove equivalent 1 " +
                            "-set-def-inputs -show-inputs -show-outputs " + settings)
        script.write_text("\n".join(commands)+"\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if log.read_text().count("SAT proof finished - no model found: SUCCESS!") != 128:
            raise RuntimeError("查询字段采样后的等价证明未完成")
        profiles.append(dict(sets=1<<width,passed=True,control_partitions=128,log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text(modules + bench())
    run(["iverilog","-g2012","-s","tb","-o",out / "four_state.vvp",*sources,four],
        out / "four_state_compile.log", root)
    run(["vvp",out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"SNAPSHOT_FIELDS_FOUR_STATE_PASS checks=(\d+)",(out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 270912:
        raise RuntimeError("查询字段采样后的四态检查数量不符")
    fill_sets = check_fill_sets(root, out / "fill_sets", current, original)
    if current != read_sources(root, SOURCE):
        raise RuntimeError("字段检查期间生产源码发生变化")
    result = dict(passed=True,actual_rtl_expressions=True,external_inputs_constrained=False,
        source_sha256=digest(root / SOURCE),reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        sat_profiles=profiles,four_state_cases=int(matched[1]),proof_sha256=digest(proof),
        four_state_log_sha256=digest(out / "four_state.log"),
        dependencies_sha256={str(path):digest(path) for path in sources},fill_sets=fill_sets)
    if args.map:
        result["mapping"] = map_fields(root,out,proof,sources)
    if current != read_sources(root, SOURCE):
        raise RuntimeError("快照映射期间生产源码发生变化")
    result["dependency_sha256"] = source_manifest(root, SOURCE)
    (out / "summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
