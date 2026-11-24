#!/usr/bin/env python3
"""Verify the complete frontend state transition and response qualification."""
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

from check_stream_admission import normalize_stream_control
from check_request_qualification import inline_control

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment(source: str, name: str) -> str:
    return re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S).group()


class Statements:
    """Retain control nesting while selecting the state-owned assignments."""

    def __init__(self, source: str, keep_state: bool = True, select_assignment=None):
        source = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.S)
        self.tokens = re.findall(r"\$?\w+|'[a-zA-Z0-9_]+|<=|===|!==|==|!=|&&|\|\||<<|>>|[^\s]", source)
        self.index = 0
        self.assignments = 0
        self.keep_state = keep_state
        self.select_assignment = select_assignment

    def take(self) -> str:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def parentheses(self) -> str:
        assert self.take() == "("
        depth, result = 1, []
        while depth:
            token = self.take()
            depth += (token == "(") - (token == ")")
            if depth:
                result.append(token)
        return " ".join(result)

    def statement(self) -> str:
        token = self.take()
        if token == "begin":
            children = []
            while self.tokens[self.index] != "end":
                child = self.statement()
                if child:
                    children.append(child)
            self.take()
            return "begin\n" + "\n".join(children) + "\nend" if children else ""
        if token == "if":
            condition = self.parentheses()
            yes = self.statement()
            no = ""
            if self.index < len(self.tokens) and self.tokens[self.index] == "else":
                self.take()
                no = self.statement()
            if not yes and not no:
                return ""
            return "if (" + condition + ") " + (yes or ";") + (" else " + no if no else "")
        if token in ("unique", "priority"):
            token = self.take()
        if token == "case":
            expression = self.parentheses()
            children = []
            while self.tokens[self.index] != "endcase":
                label = []
                while self.tokens[self.index] != ":":
                    label.append(self.take())
                self.take()
                children.append(" ".join(label) + ": " + (self.statement() or ";"))
            self.take()
            return "case (" + expression + ")\n" + "\n".join(children) + "\nendcase"
        tokens = [token]
        while tokens[-1] != ";":
            tokens.append(self.take())
        text = " ".join(tokens)
        if self.select_assignment is not None:
            return self.select_assignment(text)
        is_state = bool(re.match(r"\{ word_output_q , state \} <=", text))
        if not self.keep_state:
            return text if not is_state and text != ";" else ""
        if is_state:
            self.assignments += 1
            return text.replace("{ word_output_q , state } <=", "{ expected_word, expected_state } =", 1)
        return ""


def model(current: str, reference: str, *, payload_context_proved: bool = False) -> str:
    marker = "  // 保存前端配置、描述符和坐标状态。"
    def state_block(source):
        if "module conv_im2col_descriptor_state" in source:
            source = inline_control(source, "conv_im2col_descriptor_state", "u_descriptor_state")
        first = source.index("  assign descriptor_commit_eligible")
        last = source.index(marker, first)
        group_marker = "  // Group addresses use descriptor or movement context"
        if group_marker in source[first:last]:
            last = source.index(group_marker, first)
        return source[first:last]

    payload = []
    def payload_statement(text):
        if re.match(r"\{ word_output_q , state \} <=", text):
            return ""
        if payload_context_proved:
            match = re.match(r"(ix|iy|pixel_index|tap_group_base|row_group_base)\s*<=", text)
            if match:
                return match[1] + " <= selected_payload;"
        return text if text != ";" else ""
    comparable = normalize_stream_control(current) if 'assign stream_operation_accept =' in current else current
    reference_comparable = normalize_stream_control(reference) if 'assign stream_operation_accept =' in reference else reference
    for source in (reference_comparable, comparable):
        first = source.index(marker)
        body = source[first:source.index("  // 解码计数与坐标运算", first)]
        payload.append(Statements(body[body.index("begin"):], keep_state=False,
                                  select_assignment=payload_statement).statement())
    if payload[0] != payload[1]:
        raise ValueError("Payload assignments or their update conditions changed")
    reference_logic = ""
    if "  assign descriptor_commit_eligible" in reference:
        reference_logic = state_block(reference)
        names = ("descriptor_state", "operation_state", "selected_state",
                 "descriptor_commit_eligible", "descriptor_state_context", "state_update",
                 "descriptor_word", "operation_word", "selected_word")
        for name in names:
            reference_logic = re.sub(r"\b" + name + r"\b", "ref_" + name, reference_logic)
        reference_word = ("ref_selected_word" if "selected_word" in reference else
                          "state_uses_word(ref_selected_state)")
        reference_case = ("if(ref_state_update){expected_word,expected_state}={" +
                          reference_word + ",ref_selected_state};")
    else:
        block = reference[reference.index(marker):reference.index("  // 解码计数与坐标运算", reference.index(marker))]
        first = block.index("      unique case (1'b1)")
        parser = Statements(block[first:])
        reference_case = parser.statement()
        expected_count = len(re.findall(r"\{word_output_q,\s*state\}\s*<=", block)) - 1
        if parser.assignments != expected_count:
            raise ValueError((parser.assignments, expected_count))
    if "assign word_output_q = state_uses_word(state);" in current:
        begin = current.index("  // 描述符数据在当前传输完成前形成候选状态。")
        end = current.index("  assign descriptor_commit_eligible", begin)
        register_block = re.sub(r"\s+", " ", current[begin:end])
        expected_register = (
            "if (!rst_n) begin state <= IDLE; end else if (state_update) begin "
            "state <= selected_state; end")
        if expected_register not in register_block or "word_output_q <=" in current:
            raise ValueError("State register or output decode differs from the verified relation")
    candidate = state_block(current)
    actual_word = "selected_word" if "selected_word" in current else "state_uses_word(selected_state)"
    controls = "\n".join(assignment(current, name) for name in (
        "tile_ready_static", "tile_admission_ready", "tile_ready_context", "tile_ready",
        "wr_valid", "wr_last", "finishing_tile"))
    if 'assign stream_operation_accept =' in current:
        controls += '\n' + '\n'.join(assignment(current, name) for name in (
            'stream_response_error', 'stream_output_accept', 'stream_operation_accept'))
    return '''module proof #(parameter bit REGISTER_DESCRIPTOR=0,REGISTER_CACHE_REQUEST=0)(
 input logic[4:0]state_index,
 input logic rst_n,cfg_valid,cfg_ready,tile_valid,tile_prepared_valid,configured,error,
 input logic pred_busy,pred_cfg_busy,pred_cfg_pending,cache_cfg_pending,cache_hint_pending,
 input logic[2:0]cfg_prepare_phase,
 input logic[1:0]address_step_phase,
 input logic wr_ready,cache_rsp_valid,cache_rsp_error,cache_req_ready,row_last_q,chunk_reaches_end,
 input logic commit_invalid,commit_fast,commit_padding,commit_word_hit,
 input logic descriptor_padding,committing_saved_word_hit,committing_live_word_hit,
 input logic p_fast_valid,group_shape_o_valid,kernel_shape_o_valid,
 input logic address_position_valid,geometry_tile,current_word_hit,
 input logic[15:0]group_c,kernel_w,
 input logic[31:0]q0,p0,tap0,decode_index,col_idx,
 input logic[26:0]stream_advance_state,
 output logic equivalent,
 output logic[26:0]actual_state,expected_state,
 output logic actual_word,expected_word
);
 import conv_im2col_frontend_pkg::*;
 logic[26:0]state;
 logic word_output_q;
 logic[26:0]descriptor_state,operation_state,selected_state;
 logic descriptor_commit_eligible,descriptor_state_context,state_update;
 logic descriptor_word,operation_word,selected_word;
 logic[26:0]ref_descriptor_state,ref_operation_state,ref_selected_state;
 logic ref_descriptor_commit_eligible,ref_descriptor_state_context,ref_state_update;
 logic ref_descriptor_word,ref_operation_word,ref_selected_word;
 logic tile_ready_static,tile_admission_ready,tile_ready_context,tile_ready,tile_commit;
 logic wr_valid,wr_last,finishing_tile;
 logic stream_response_error,stream_output_accept,stream_operation_accept;
 wire cache_rsp_success=cache_rsp_valid&&!cache_rsp_error;
 wire cache_rsp_failure=cache_rsp_valid&&cache_rsp_error;
 typedef struct packed {logic invalid,fast,padding,word_hit;} tile_t;
 typedef struct packed {logic[15:0]group_c,kernel_w;} config_t;
 tile_t committing_tile;
 config_t c;
 assign c={group_c,kernel_w};
 assign committing_tile={commit_invalid,commit_fast,commit_padding,commit_word_hit};
 assign state=27'b1<<state_index;
 assign word_output_q=state[$clog2(STREAM)]||state[$clog2(WAIT_WORD)];
 function automatic logic state_uses_word(input logic[26:0]value);
  state_uses_word=value[$clog2(STREAM)]||value[$clog2(WAIT_WORD)];
 endfunction
''' + controls + '''
 assign tile_commit=REGISTER_DESCRIPTOR ?
  tile_prepared_valid&&!error&&(state[$clog2(IDLE)]||finishing_tile) : tile_valid&&tile_ready;
''' + candidate + reference_logic + '''
 always_comb begin
  expected_state=state;expected_word=word_output_q;
  if(!rst_n){expected_word,expected_state}={state_uses_word(IDLE),IDLE};
  else begin
''' + reference_case + '''
  end
 end
 always_comb begin
  actual_state=state;actual_word=word_output_q;
  if(!rst_n){actual_word,actual_state}={state_uses_word(IDLE),IDLE};
  else if(state_update){actual_word,actual_state}={''' + actual_word + ''',selected_state};
 end
 assign equivalent={actual_word,actual_state}==={expected_word,expected_state};
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    reference_options = parser.add_mutually_exclusive_group()
    reference_options.add_argument("--reference-ref")
    reference_options.add_argument("--reference-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = Path("rtl/npu/conv/conv_im2col_frontend.sv")
    source, package = root / relative, root / "rtl/npu/conv/conv_im2col_frontend_pkg.sv"
    reference_file = None
    if args.reference_ref:
        reference = read_reference_file(ROOT, args.reference_ref, str(relative), text=True)
    else:
        reference_file = (args.reference_file or ROOT / "test/conv_frontend/references/state_context.sv.txt").resolve()
        reference = reference_file.read_text()
    current = source.read_text()
    admission_summary = None
    if 'assign stream_operation_accept =' in current:
        admission_output = out/'stream_admission'
        subprocess.run([sys.executable, str(Path(__file__).with_name('check_stream_admission.py')),
            '--source-root', str(root), '--out', str(admission_output),
            '--iverilog', args.iverilog, '--vvp', args.vvp], check=True)
        admission_summary = admission_output/'summary.json'
        if not json.loads(admission_summary.read_text())['passed']:
            raise RuntimeError(str(admission_summary))
    payload_summary = None
    payload_selection_unchanged = False
    payload_start = "  // 数据来源由运行阶段提前选择"
    payload_stop = "  // 请求地址、窗口索引和有效位同时寄存"
    if payload_start in current and payload_start in reference:
        def payload_selection(text):
            start = text.index(payload_start)
            return text[start:text.index(payload_stop, start)]
        payload_selection_unchanged = payload_selection(current) == payload_selection(reference)
    if "assign descriptor_payload_context =" in current and not payload_selection_unchanged:
        payload_reference = out / "payload_reference.sv"
        payload_reference.write_text(reference)
        payload_output = out / "payload_context"
        subprocess.run([sys.executable, str(Path(__file__).with_name("check_payload_context.py")),
                        "--source-root", str(root), "--reference-file", str(payload_reference),
                        "--out", str(payload_output), "--iverilog", args.iverilog, "--vvp", args.vvp],
                       check=True)
        payload_summary = payload_output / "summary.json"
        if not json.loads(payload_summary.read_text())["passed"]:
            raise RuntimeError(str(payload_summary))
    generated = out / "model.sv"
    generated.write_text(model(current, reference, payload_context_proved=payload_summary is not None)
                         .replace("always_comb", "always @*"))
    hashes = {str(p): digest(p) for p in (source, package, generated, Path(__file__).resolve(),
                                         Path(__file__).with_name("check_request_qualification.py"))}
    reference_hash = hashlib.sha256(reference.encode()).hexdigest()
    rows = []
    for descriptor in (0,1):
        for request in (0,1):
            name=f"descriptor{descriptor}_request{request}"
            ys,log = out/(name+".ys"),out/(name+".formal.log")
            ys.write_text(f"read_slang --top proof -GREGISTER_DESCRIPTOR={descriptor} -GREGISTER_CACHE_REQUEST={request} "+
                shlex.join(map(str,(package,generated)))+"\nprep -top proof -flatten\ncheck -assert\n"
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log.open("w") as handle:
                run=subprocess.run([sys.executable,str(ROOT/"scripts/fpga/open_fpga_synth.py"),"--worker",str(ys)],
                    stdout=handle,stderr=subprocess.STDOUT,timeout=180)
            if run.returncode or "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError(str(log))
            print("STATE_CONTEXT_FORMAL_PASS",name,flush=True)
            tb=out/(name+".sv")
            tb.write_text('''module tb;
 logic[4:0]state_index;
 logic rst_n,cfg_valid,cfg_ready,tile_valid,tile_prepared_valid,configured,error;
 logic pred_busy,pred_cfg_busy,pred_cfg_pending,cache_cfg_pending,cache_hint_pending;
 logic[2:0]cfg_prepare_phase;
 logic[1:0]address_step_phase;
 logic wr_ready,cache_rsp_valid,cache_rsp_error,cache_req_ready,row_last_q,chunk_reaches_end;
 logic commit_invalid,commit_fast,commit_padding,commit_word_hit;
 logic descriptor_padding,committing_saved_word_hit,committing_live_word_hit;
 logic p_fast_valid,group_shape_o_valid,kernel_shape_o_valid;
 logic address_position_valid,geometry_tile,current_word_hit;
 logic[15:0]group_c,kernel_w;
 logic[31:0]q0,p0,tap0,decode_index,col_idx;
 logic[26:0]stream_advance_state,actual_state,expected_state;
 logic actual_word,expected_word,equivalent;
 logic[255:0]pattern;
 integer checks=0;
 proof #(.REGISTER_DESCRIPTOR('''+str(descriptor)+'''),.REGISTER_CACHE_REQUEST('''+str(request)+''')) dut(.*);
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
   for(integer bit_index=0;bit_index<256;bit_index++)begin
    case($urandom_range(0,9))
     0:pattern[bit_index]=1'bx;
     1:pattern[bit_index]=1'bz;
     default:pattern[bit_index]=1'($urandom);
    endcase
   end
   {rst_n,cfg_valid,cfg_ready,tile_valid,tile_prepared_valid,configured,error,
    pred_busy,pred_cfg_busy,pred_cfg_pending,cache_cfg_pending,cache_hint_pending,
    cfg_prepare_phase,address_step_phase,wr_ready,cache_rsp_valid,cache_rsp_error,cache_req_ready,
    row_last_q,chunk_reaches_end,commit_invalid,commit_fast,commit_padding,commit_word_hit,
    descriptor_padding,committing_saved_word_hit,committing_live_word_hit,p_fast_valid,
    group_shape_o_valid,kernel_shape_o_valid,address_position_valid,geometry_tile,current_word_hit,
    group_c,kernel_w,q0,p0,tap0,decode_index,col_idx,stream_advance_state}=pattern;
   state_index=5'(sample%28);
   if(sample[2:0]!=3'b111)begin
    rst_n=1'b1;cfg_valid=1'b0;cfg_ready=1'b0;configured=1'b1;error=1'b0;
    pred_busy=0;pred_cfg_busy=0;pred_cfg_pending=0;cache_cfg_pending=0;cache_hint_pending=0;
    cfg_prepare_phase=0;address_step_phase=0;
   end
   #1;
   if(equivalent!==1'b1)$fatal(1,"State mismatch sample=%0d state=%0d actual=%h expected=%h commit=%b en=%b context=%b",
    sample,state_index,actual_state,expected_state,dut.tile_commit,dut.state_update,dut.descriptor_state_context);
   checks++;
  end
  $display("STATE_CONTEXT_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
            binary=out/(name+".vvp");build=out/(name+".build.log");simulation=out/(name+".four_state.log")
            with build.open("w") as handle:
                subprocess.run([args.iverilog,"-g2012","-s","tb","-o",str(binary),*map(str,(package,generated,tb))],
                    stdout=handle,stderr=subprocess.STDOUT,check=True)
            with simulation.open("w") as handle:
                subprocess.run([args.vvp,str(binary)],stdout=handle,stderr=subprocess.STDOUT,check=True,timeout=120)
            if "STATE_CONTEXT_FOUR_STATE_PASS checks=65536" not in simulation.read_text():
                raise RuntimeError(str(simulation))
            rows.append({"register_descriptor":descriptor,"register_cache_request":request,"formal_passed":True,
                         "four_state_checks":65536,"formal_log_sha256":digest(log),"simulation_log_sha256":digest(simulation)})
            print("STATE_CONTEXT_FOUR_STATE_PASS",name,flush=True)
    if hashes != {p:digest(Path(p)) for p in hashes}:
        raise RuntimeError("Source changed during verification")
    (out/"summary.json").write_text(json.dumps({"passed":True,"source_sha256":hashes,"reference_ref":args.reference_ref,
        "reference_file":str(reference_file) if reference_file else None,"reference_sha256":reference_hash,
        "cases":rows,"payload_update_structure_preserved":True,
        "payload_selection_unchanged":payload_selection_unchanged,
        "stream_admission_summary":str(admission_summary) if admission_summary else None,
        "payload_equivalence_summary":str(payload_summary) if payload_summary else None,
        "domain":"All 27 states, the zero encoding, arbitrary descriptor, decode, response and backpressure values"},indent=2)+"\n")
    print("STATE_CONTEXT_PASS",flush=True)


if __name__ == "__main__":
    main()
