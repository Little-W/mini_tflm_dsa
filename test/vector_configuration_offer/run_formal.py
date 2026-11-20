#!/usr/bin/env python3
"""从实际 RTL 提取配置有效信号的使用条件，并证明配置等待性质。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
VECTOR = ROOT / "rtl/npu/conv/vector_engine.sv"
ARBITER = ROOT / "rtl/npu/dma/axi_block_dma_arbiter.sv"
DUAL = ROOT / "rtl/npu/dma/axi_dual_block_dma.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment(source, name):
    matches = re.findall(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if len(matches) != 1:
        raise RuntimeError("赋值数量与预期不符: " + name)
    return matches[0]


def run_yosys(out, name, commands, expected="SUCCESS!", timeout=180):
    script, log = out / (name + ".ys"), out / (name + ".log")
    script.write_text("\n".join(commands) + "\n")
    with log.open("w") as stream:
        result = subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py",
                                 "--worker", script], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode or expected not in log.read_text():
        raise RuntimeError(str(log) + "\n" + log.read_text()[-7000:])
    return {"passed": True, "script_sha256": digest(script), "log_sha256": digest(log)}


def arbitration_fragment(source):
    begin = source.index("    always_comb begin\n        rd_next_client = C_NONE;")
    end = source.index("    // 每个请求方独立更新", begin)
    body = source[begin:end]
    start = body.index("    always_ff @(posedge clk) begin")
    body = body[:start] + body[start:].replace(
        "always_ff @(posedge clk) begin", "always_comb begin\n        grant_next = rd_grant_client;", 1)
    body = re.sub(r"rd_grant_client\s*<=", "grant_next =", body)
    return body


def make_consumers(out):
    arbiter, dual = ARBITER.read_text(), DUAL.read_text()
    common = '''
    input logic rst_n, configuring, abort,
    input logic [2:0] rd_pending_count_q,
    input logic [2:0] rd_grant_client,
    input logic rd_dma_start_q, rd_dma_start,
    input logic [1:0] rd_client_inflight[5],
    input logic conv_job_q,
    input logic dw_req, kernel_req, quant_req_eff, bias_req, ia_req, win_req_valid,
    input logic dual_busy, dual_done, fe_cfg_ready, win_queue_req_ready,
    input logic job_conv, rd_im2col, rd_finish_beat, win_busy,
    input logic linear_start_ready, conv_active, conv_pending, fe_busy,
    output logic [13:0] observable,
    output logic inactive_ready_difference
'''
    header = "module consumer #(parameter bit OFFER=0)(" + common + ''');
    localparam logic [2:0] C_IA=0,C_KERNEL=1,C_BIAS=2,C_QUANT=3,C_DW=4,C_WINDOW=5,C_NONE=7;
    logic conv_cfg_valid,conv_cfg_ready,dma_conv_cfg_valid,dma_conv_cfg_ready;
    logic rd_active,rd_reservation_space,rd_dma_start_ready;
    logic [3:0] rd_pending_count;
    logic [2:0] rd_next_client,grant_next,rd_command_client;
    logic win_accept_allowed,win_req_ready,win_dma_req_ready;
    logic dual_start_ready,dual_image_ready,accept_linear,accept_image,cfg_fire;
    logic dual_window_valid,dual_window_fire;
    assign rd_pending_count={1'b0,rd_pending_count_q};
    assign conv_cfg_valid=configuring && (OFFER || conv_cfg_ready);
    assign rd_command_client=rd_grant_client;
'''
    body = "\n".join(assignment(arbiter, name) for name in (
        "rd_active", "rd_reservation_space", "dma_conv_cfg_valid", "conv_cfg_ready",
        "win_accept_allowed", "win_req_ready"))
    body += "\n" + arbitration_fragment(arbiter)
    mapping = {"rd_start_ready": "dual_start_ready", "image_start_ready": "dual_image_ready",
               "conv_cfg_ready": "dma_conv_cfg_ready", "conv_cfg_valid": "dma_conv_cfg_valid",
               "rd_start": "rd_dma_start_q", "rd_busy": "dual_busy", "rd_done": "dual_done",
               "win_req_ready": "win_dma_req_ready"}
    for name in ("win_req_ready", "image_start_ready", "rd_start_ready", "accept_linear",
                 "accept_image", "conv_cfg_ready", "cfg_fire"):
        text = assignment(dual, name)
        body += "\n" + re.sub(r"\b(" + "|".join(mapping) + r")\b", lambda m: mapping[m[0]], text)
    body += '''
    assign rd_dma_start_ready=dual_start_ready;
    assign dual_window_valid=win_req_valid && win_accept_allowed && !dma_conv_cfg_valid && !rd_dma_start_q;
    assign dual_window_fire=dual_window_valid && win_queue_req_ready;
    // 没有有效请求时，内部就绪值可以变化；实际接受事件必须逐项相同。
    assign observable={rd_next_client,grant_next,cfg_fire,conv_cfg_valid&&conv_cfg_ready,
                       accept_linear,accept_image,dual_window_fire,
                       win_req_valid&&win_req_ready,rd_dma_start_q&&rd_dma_start_ready,
                       conv_cfg_ready};
    assign inactive_ready_difference=rd_dma_start_ready;
endmodule
'''
    # 端口连接显式列出，避免数组和同一声明内多个名称的歧义。
    inputs = ("rst_n", "configuring", "abort", "rd_pending_count_q", "rd_grant_client",
              "rd_dma_start_q", "rd_dma_start", "rd_client_inflight", "conv_job_q", "dw_req",
              "kernel_req", "quant_req_eff", "bias_req", "ia_req", "win_req_valid", "dual_busy",
              "dual_done", "fe_cfg_ready", "win_queue_req_ready", "job_conv", "rd_im2col",
              "rd_finish_beat", "win_busy", "linear_start_ready", "conv_active", "conv_pending", "fe_busy")
    connections = ",".join("." + name for name in inputs)
    ports = common[:common.index("    output logic")].rstrip().rstrip(",")
    top = "module consumers_proof(" + ports + ''',output logic equivalent);
    logic [13:0] old_observable,new_observable;
    logic old_ready,new_ready;
'''
    top += f"consumer #(.OFFER(0)) old_version({connections},.observable(old_observable),.inactive_ready_difference(old_ready));\n"
    top += f"consumer #(.OFFER(1)) new_version({connections},.observable(new_observable),.inactive_ready_difference(new_ready));\n"
    top += '''
    wire no_requests=!(dw_req||kernel_req||quant_req_eff||bias_req||ia_req||win_req_valid);
    assign equivalent=(!configuring || no_requests) ?
        ((old_observable==new_observable) && (old_ready==new_ready || !rd_dma_start_q)) : 1'b1;
endmodule
'''
    path = out / "consumers.sv"
    path.write_text(header + body + top)
    return path


def prepare_vector(out):
    source = VECTOR.read_text()
    expressions=("dma_cfg_valid = state==CONFIGURE && dma_cfg_ready;",
                 "dma_cfg_valid = state==CONFIGURE;")
    if sum(source.count(value) for value in expressions) != 1:
        raise RuntimeError("向量配置赋值与受测版本不符")
    uses = re.findall(r"\bdma_cfg_valid\b", re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.S))
    if len(uses) != 2:
        raise RuntimeError("dma_cfg_valid 增加了内部使用者，需要扩展验证")
    body = source.replace("module vector_engine #(", "module vector_offer_properties #(", 1)
    body = body.replace("\n);", ",\n  output logic formal_bad, formal_configuring\n);", 1)
    extra = '''
  // 只读观察当前配置及上一等待周期，不改变被测模块的行为。
  localparam int PAYLOAD_WIDTH=$bits(dma_conv_cfg)+2+4*32+4*33;
  wire [PAYLOAD_WIDTH-1:0] formal_payload={dma_conv_cfg,dma_conv_enable,dma_range_enable,
      dma_range_base[0],dma_range_base[1],dma_range_base[2],dma_range_base[3],
      dma_range_end[0],dma_range_end[1],dma_range_end[2],dma_range_end[3]};
  logic formal_started=1'b0;
  logic formal_waited;
  logic [PAYLOAD_WIDTH-1:0] formal_previous_payload;
  always_ff @(posedge clk) begin
    if (!rst_n) begin formal_started<=1'b1;formal_waited<=1'b0;end
    else begin
      formal_waited<=state==CONFIGURE && !dma_cfg_ready;
      formal_previous_payload<=formal_payload;
    end
  end
  assign formal_configuring=formal_started && rst_n && state==CONFIGURE;
  assign formal_bad=formal_started && rst_n && (
      (state==CONFIGURE && (rd_req || rd_start || win_req_valid || wr_req || wr_start || src_wvalid)) ||
      ((state==IDLE || state==CHECK || state==CHECK_WAIT || state==CONFIGURE || state==DONE) && writeback_busy) ||
      (state==CONFIGURE && !config_check_ready) ||
      (formal_waited && formal_payload!=formal_previous_payload) ||
      ((dma_cfg_valid && dma_cfg_ready)!=((state==CONFIGURE) && dma_cfg_ready)));
'''
    body = body.replace("endmodule", extra + "\nendmodule", 1)
    design = out / "vector_properties.sv"
    design.write_text(body)
    files = [ROOT / "rtl/npu/conv" / name for name in ("conv_im2col_pkg.sv", "vector_engine_pkg.sv")]
    files += [p for p in sorted((ROOT / "rtl/npu/conv").glob("*.sv"))
              if p not in files and p != VECTOR]
    files += [ROOT / "rtl/common" / name for name in ("regfile.v", "pseudo_dual_port_ram.v", "add_equal.sv")]
    files.append(design)
    commands = ["read_slang -D SYNTHESIS=1 -D ASIC_SYNTHESIS=1 --top vector_offer_properties "
                "-GTILE=16 -GPE_COUNT=8 -GBUS_WIDTH=64 " + " ".join(shlex.quote(str(p)) for p in files),
                "delete -output vector_offer_properties/w:*",
                "expose vector_offer_properties/formal_bad vector_offer_properties/formal_configuring",
                "prep -top vector_offer_properties -flatten", "async2sync", "setattr -unset keep",
                "opt -full", "write_json " + str(out / "vector.json")]
    result = run_yosys(out, "prepare_vector", commands, "Executing JSON backend.")
    return result, files[:-1] + [VECTOR]


def vector_worker(out):
    from pyosys import libyosys
    design = json.loads((out / "vector.json").read_text())
    module = design["modules"]["vector_offer_properties"]
    wanted = ("state", "c", "global_pool", "input_range_mode", "input_bytes", "weight_bytes",
              "u_config_check.state", "u_writeback.c_st", "formal_started", "formal_waited",
              "formal_previous_payload")
    roots = {bit for name in wanted for bit in module["netnames"].get(name, {}).get("bits", []) if isinstance(bit, int)}
    drivers = {}
    for name, cell in module["cells"].items():
        for port, direction in cell["port_directions"].items():
            if direction == "output":
                for bit in cell["connections"][port]:
                    if isinstance(bit, int):
                        drivers.setdefault(bit, []).append(name)
    keep, seen, pending = set(), set(), list(roots)
    while pending:
        bit = pending.pop()
        if not isinstance(bit, int) or bit in seen:
            continue
        seen.add(bit)
        for name in drivers.get(bit, []):
            cell = module["cells"][name]
            if "dff" in cell["type"].lower():
                keep.add(name)
            else:
                pending.extend(b for p, d in cell["port_directions"].items() if d == "input"
                               for b in cell["connections"][p])
    abstracted = []
    for name, cell in list(module["cells"].items()):
        if "dff" in cell["type"].lower() and name not in keep:
            bits = cell["connections"]["Q"]
            module["cells"][name] = {"hide_name": 1, "type": "$anyseq",
                "parameters": {"WIDTH": format(len(bits), "032b")}, "attributes": {},
                "port_directions": {"Y": "output"}, "connections": {"Y": bits}}
            abstracted.append(name)
    path = out / "vector_abstracted.json"
    path.write_text(json.dumps(design))
    libyosys.run_pass("read_json " + str(path))
    libyosys.run_pass("opt -full")
    libyosys.run_pass("memory_map; opt -full")
    libyosys.run_pass("write_rtlil " + str(out / "vector_control.il"))
    libyosys.run_pass("stat")
    libyosys.run_pass("sat -seq 2 -tempinduct -maxsteps 16 -timeout 30 -set-init-zero "
                     "-prove formal_bad 0 -verify -show state -show u_config_check.state "
                     "-show u_writeback.c_st -show formal_waited -show rst_n "
                     "-dump_vcd " + str(out / "vector_witness.vcd"))
    report = {"passed": True, "preserved_registers": sorted(keep),
              "abstracted_registers": sorted(abstracted), "input_constraints": None,
              "properties": ["CONFIGURE 不发出读写或窗口请求", "配置等待期间载荷稳定",
                             "配置接受事件逐周期相同"], "actual_control_rtl": True}
    (out / "vector_control_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.worker:
        vector_worker(out)
        return
    consumers = make_consumers(out)
    result = {"source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    result["consumers"] = run_yosys(out, "consumers", [
        "read_slang --top consumers_proof " + str(consumers), "prep -top consumers_proof -flatten",
        "sat -verify -prove equivalent 1 -show-inputs -show-outputs"])
    print("配置使用者组合证明通过", flush=True)
    result["prepare_vector"], files = prepare_vector(out)
    files += [ARBITER, DUAL, Path(__file__).resolve()]
    result["source_sha256"] = {str(p.relative_to(ROOT)): digest(p) for p in files}
    log = out / "vector_formal.log"
    with log.open("w") as stream:
        check = subprocess.run([sys.executable, Path(__file__).resolve(), "--worker", "--out", out],
                               cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
    if check.returncode:
        raise RuntimeError(str(log) + "\n" + log.read_text()[-8000:])
    result["vector_control"] = json.loads((out / "vector_control_summary.json").read_text())
    result["vector_control"]["log_sha256"] = digest(log)
    if result["source_sha256"] != {str(p.relative_to(ROOT)): digest(p) for p in files}:
        raise RuntimeError("受测源码在验证期间发生变化")
    result["passed"] = True
    (out / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print("向量配置等待状态证明通过", flush=True)


if __name__ == "__main__":
    main()
