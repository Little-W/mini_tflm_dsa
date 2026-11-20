#!/usr/bin/env python3
"""证明窗口队列占用寄存位及全部公开字段的逐周期等价性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
QUEUE = "rtl/npu/dma/conv_window_queue.sv"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def instrument(source, name):
    """只添加观察端口，原有状态和组合表达式均保留。"""
    source, count = re.subn(r"\bmodule\s+conv_window_queue\b", "module " + name, source, count=1)
    assert count == 1
    header = "input logic frontend_rsp_last,frontend_error);"
    assert source.count(header) == 1
    source = source.replace(header, """input logic frontend_rsp_last,frontend_error,
  output logic [(97+TAG_W)*DEPTH+2*PTR_W+COUNT_W+100-1:0] formal_state,
  output logic [(97+TAG_W)*DEPTH+97-1:0] formal_nonreset,
  output logic [173+TAG_W+COL_W-1:0] formal_public,
  output logic [3:0] formal_events,
  output logic formal_invariant,formal_nonempty);""", 1)
    extra = """
  // 描述符存储和前端描述符寄存器没有复位，比较时允许相同的任意初始内容。
  logic [(97+TAG_W)*DEPTH-1:0] formal_storage;
  for (genvar entry=0;entry<DEPTH;entry++) begin : g_formal_storage
    assign formal_storage[entry*(97+TAG_W)+:(97+TAG_W)] =
        {p0[entry],q0[entry],cols[entry],cols_valid[entry],tags[entry]};
  end
  assign formal_nonreset =
      {frontend_p0,frontend_q0,frontend_cols,frontend_cols_valid,formal_storage};
  assign formal_state =
      {head,tail,count,active,failed,descriptor_prepared,formal_nonreset};
  // 有效位为零时也比较数据、标签、掩码、错误和前端描述符。
  assign formal_public = {req_ready,rsp_valid,rsp_tag,rsp_col,
      rsp_data[0],rsp_data[1],rsp_data[2],rsp_data[3],rsp_mask,rsp_last,rsp_error,busy,
      frontend_valid,frontend_active,frontend_p0,frontend_q0,frontend_cols,
      frontend_cols_valid,frontend_rsp_ready};
  assign formal_events = {failed,launch,accept,retire};
  assign formal_nonempty = count != COUNT_W'(0);
  assign formal_invariant = busy == formal_nonempty;
"""
    assert source.count("endmodule") == 1
    return source.replace("endmodule", extra + "\nendmodule", 1)


def miter(depth):
    inputs = """
  input logic clk,rst_n,configure,enable,req_valid,rsp_ready,frontend_ready,
  input logic [31:0] req_p0,req_q0,req_cols,
  input logic [1:0] req_tag,
  input logic frontend_rsp_valid,
  input logic [3:0] frontend_rsp_col,
  input logic signed [15:0] frontend_rsp_data[4],
  input logic [3:0] frontend_rsp_mask,
  input logic frontend_rsp_last,frontend_error
"""
    names = ("clk", "rst_n", "configure", "enable", "req_valid", "rsp_ready", "frontend_ready",
             "req_p0", "req_q0", "req_cols", "req_tag", "frontend_rsp_valid", "frontend_rsp_col",
             "frontend_rsp_data", "frontend_rsp_mask", "frontend_rsp_last", "frontend_error")
    connections = ",".join("." + name + "(" + name + ")" for name in names)
    text = "module window_queue_busy_proof(" + inputs + """,
  output logic relation,observable_equal,unreset_equal,candidate_invariant,
  output logic cover_invalid_response,cover_configure_nonempty,cover_disabled_nonempty,
  output logic cover_failed_nonempty,cover_accept_retire,cover_launch_retire);
"""
    text += f"  localparam int DEPTH={depth};\n"
    text += """
  localparam int PTR_W=$clog2(DEPTH),COUNT_W=$clog2(DEPTH+1);
  localparam int STATE_W=99*DEPTH+2*PTR_W+COUNT_W+100;
  localparam int NONRESET_W=99*DEPTH+97;
  logic [STATE_W-1:0] reference_state,candidate_state;
  logic [NONRESET_W-1:0] reference_nonreset,candidate_nonreset;
  logic [178:0] reference_public,candidate_public;
  logic [3:0] reference_events,candidate_events;
  logic reference_invariant,reference_nonempty,candidate_nonempty,reference_rsp_valid;
"""
    for label, module in (("reference", "reference_window_queue"), ("candidate", "candidate_window_queue")):
        text += f"  {module} #(.DEPTH(DEPTH)) u_{label}({connections},\n"
        text += f"      .formal_state({label}_state),.formal_nonreset({label}_nonreset),\n"
        text += f"      .formal_public({label}_public),.formal_events({label}_events),\n"
        text += f"      .formal_invariant({label}_invariant),.formal_nonempty({label}_nonempty)"
        if label == "reference":
            text += ",.rsp_valid(reference_rsp_valid)"
        text += ");\n"
    text += """
  assign relation = (reference_state == candidate_state) && candidate_invariant;
  assign observable_equal = (reference_public == candidate_public) &&
      (reference_events == candidate_events);
  assign unreset_equal = reference_nonreset == candidate_nonreset;
  assign cover_invalid_response = rst_n && !reference_rsp_valid;
  assign cover_configure_nonempty = rst_n && configure && candidate_nonempty;
  assign cover_disabled_nonempty = rst_n && !enable && candidate_nonempty;
  assign cover_failed_nonempty = rst_n && !configure && candidate_nonempty && candidate_events[3];
  assign cover_accept_retire = rst_n && !configure && (&candidate_events[1:0]);
  assign cover_launch_retire = rst_n && !configure && candidate_events[2] && candidate_events[0];
endmodule
"""
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=ROOT / QUEUE)
    parser.add_argument("--reference", default="b20921b3b1fc3351b1f6447dd688af12ac60ef19")
    parser.add_argument("--tool-repo", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "build/window_queue_busy")
    args = parser.parse_args()
    args.candidate = args.candidate.resolve()
    args.out = args.out.resolve()
    args.tool_repo = args.tool_repo.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    reference_commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", args.reference + "^{commit}"], text=True).strip()
    reference = subprocess.check_output(["git", "-C", str(ROOT), "show", reference_commit + ":" + QUEUE])
    candidate = args.candidate.read_bytes()
    worker = args.tool_repo / "scripts/fpga/open_fpga_synth.py"
    worker_sha = sha(worker.read_bytes())
    models = instrument(reference.decode(), "reference_window_queue") + "\n" + instrument(
        candidate.decode(), "candidate_window_queue")
    covers = ("invalid_response", "configure_nonempty", "disabled_nonempty", "failed_nonempty",
              "accept_retire", "launch_retire")
    results = []
    for depth in (2, 3, 4, 7, 8):
        directory = args.out / ("depth" + str(depth))
        directory.mkdir(exist_ok=True)
        design, script, log = (directory / name for name in ("proof.sv", "run.ys", "run.log"))
        design.write_text(models + "\n" + miter(depth))
        commands = [
            "read_slang --top window_queue_busy_proof " + shlex.quote(str(design)),
            "prep -top window_queue_busy_proof -flatten", "memory_map", "opt -full", "async2sync", "opt_clean",
            # 复位基础只令未复位状态相同，保持其内容任意。
            "sat -verify -seq 1 -set-def-inputs -set-init-def -set rst_n 0 -set unreset_equal 1 "
            "-prove relation 1 -prove observable_equal 1 -show-inputs -show-outputs",
            # 当前状态关系足以推出全部公开字段和内部接收、退休、启动事件相同。
            "sat -verify -seq 1 -set-def-inputs -set-init-def -set relation 1 "
            "-prove observable_equal 1 -show-inputs -show-outputs",
            # 一次时钟转换维持完整状态关系，下一周期所有公开字段也相同。
            "sat -verify -seq 2 -set-def-inputs -set-init-def -set-at 1 relation 1 -prove-skip 1 "
            "-prove relation 1 -prove observable_equal 1 -show-inputs -show-outputs",
            # 独立证明占用位不变量，无需另一版本状态相同的条件。
            "sat -verify -seq 2 -set-def-inputs -set-init-def -set-at 1 candidate_invariant 1 -prove-skip 1 "
            "-prove candidate_invariant 1 -show-inputs -show-outputs",
        ]
        for cover in covers:
            commands.append("sat -seq 1 -set-def-inputs -set-init-def -set relation 1 -set cover_" + cover +
                            " 1 -show-inputs -show-outputs")
        script.write_text("\n".join(commands) + "\n")
        start = time.monotonic()
        with log.open("w") as stream:
            process = subprocess.run([sys.executable, str(worker), "--worker", str(script)],
                                     cwd=args.tool_repo, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        contents = log.read_text()
        if process.returncode or contents.count("SUCCESS!") != 4 or contents.count("SAT solving finished - model found:") != 6:
            raise RuntimeError(str(log) + "\n" + contents[-6000:])
        item = {"depth": depth, "passed": True, "proofs": 4, "covers": list(covers),
                "public_output_bits": 179, "elapsed_seconds": time.monotonic() - start,
                "design_sha256": sha(design.read_bytes()), "script_sha256": sha(script.read_bytes()),
                "log_sha256": sha(log.read_bytes())}
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    assert args.candidate.read_bytes() == candidate
    assert sha(worker.read_bytes()) == worker_sha
    report = {"passed": True, "reference_commit": reference_commit, "reference_sha256": sha(reference),
              "candidate_path": str(args.candidate), "candidate_sha256": sha(candidate),
              "source_sha256": sha(candidate),
              "source_unchanged_during_verification": True, "actual_source_modules": True,
              "source_transformation": "仅重命名模块并添加观察端口，保留原有状态和组合表达式。",
              "data_input_constraints": [], "control_input_constraints_for_induction": [],
              "initial_state_relation": "两个实现的原有状态相同；新增占用位等于候选计数非零。",
              "reset_base": "复位有效，未复位描述符与前端描述符状态为相同的任意二值内容。",
              "sequential_argument": "复位建立状态关系；任意输入的一步转换维持状态关系；每个状态关系下全部公开字段和接收、退休、启动事件相同。",
              "covers_scope": "各条件在任意满足归纳状态关系的状态中均可满足，未添加配置空闲或有效周期假设。",
              "proof_script_sha256": sha(Path(__file__).read_bytes()), "worker_sha256": worker_sha,
              "cases": results}
    (args.out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "cases": len(results), "proofs": 20, "cover_conditions": 30,
                      "summary": str(args.out / 'summary.json')}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
