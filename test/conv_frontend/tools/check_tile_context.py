#!/usr/bin/env python3
"""验证描述符接收资格对全部状态编码和四态控制输入的等价性。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
FRONTEND = Path("rtl/npu/conv/conv_im2col_frontend.sv")
SIGNALS = ("state", "tile_ready_static", "cache_rsp_success", "wr_ready", "row_last_q",
           "chunk_reaches_end", "cfg_valid", "tile_prepared_valid", "tile_commit")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(name, text):
    expressions = []
    for signal in ("stream_output_accept", "finishing_tile", "wr_valid", "wr_last", "tile_ready"):
        match = re.search(r"  assign " + signal + r"\s*=.*?;", text, re.S)
        if match is None:
            raise RuntimeError("未找到实际赋值：" + signal)
        expressions.append(match.group())
    if "  conv_im2col_tile_context u_tile_context (" in text:
        first = text.index("  conv_im2col_tile_context u_tile_context (")
        expressions.append(text[first:text.index("  assign tile_ready =", first)])
    else:
        expressions.append(re.search(r"  assign tile_ready_context\s*=.*?;", text, re.S).group())
    return f"""module {name} #(parameter bit REGISTER_DESCRIPTOR=0)(
  input logic [34:0] stimulus,output logic [1:0] observed);
  import conv_im2col_frontend_pkg::*;
  logic [26:0] state;
  logic tile_ready_static,cache_rsp_success,wr_ready,row_last_q,chunk_reaches_end;
  logic cfg_valid,tile_prepared_valid,tile_commit;
  logic stream_output_accept,finishing_tile,wr_valid,wr_last,tile_ready_context,tile_ready;
  logic [1:0] tile_context_ready;
  assign {{{','.join(SIGNALS)}}}=stimulus;
{chr(10).join(expressions)}
  assign observed={{tile_ready_context,tile_ready}};
endmodule
"""


def run(command, log):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, reference, out = args.source_root.resolve(), args.reference_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root / FRONTEND, reference / FRONTEND,
               root / "rtl/npu/conv/conv_im2col_frontend_pkg.sv"]
    hashes = {str(path): digest(path) for path in sources}
    candidate, original = sources[0].read_text(), sources[1].read_text()
    helper = re.search(r"(?m)^module conv_im2col_tile_context\b.*?endmodule", candidate, re.S)
    if helper is None:
        raise RuntimeError("未找到完整接收资格模块")
    text = model("candidate", candidate) + model("reference", original) + helper.group() + "\n"
    text += """module comparison #(parameter bit REGISTER_DESCRIPTOR=0)(
      input logic [34:0] stimulus,output logic equivalent);
      logic [1:0] expected,actual;
      reference #(.REGISTER_DESCRIPTOR(REGISTER_DESCRIPTOR)) u_reference(.*,.observed(expected));
      candidate #(.REGISTER_DESCRIPTOR(REGISTER_DESCRIPTOR)) u_candidate(.*,.observed(actual));
      assign equivalent=expected===actual;
    endmodule
"""
    model_file = out / "model.sv"
    model_file.write_text(text)
    results = []
    for registered in (0, 1):
        script, log = out / f"registered_{registered}.ys", out / f"registered_{registered}.log"
        script.write_text("read_slang --top comparison -DSYNTHESIS=1 " +
            f"-GREGISTER_DESCRIPTOR={registered} " +
            " ".join(shlex.quote(str(path)) for path in (sources[-1], model_file)) + "\n"
            "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
            "prep -top comparison -flatten\ncheck -assert\n"
            "sat -verify -prove equivalent 1 -set-def-inputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
        results.append({"register_descriptor": registered, "passed": True, "log_sha256": digest(log)})
    bench = out / "four_state.sv"
    bench.write_text(text + """module tb;
      logic [34:0] stimulus,saved;
      logic [1:0] equivalent;
      logic [31:0] random_state=32'h29f10347;
      integer checks=0;
      comparison #(.REGISTER_DESCRIPTOR(0)) direct_mode(.stimulus,.equivalent(equivalent[0]));
      comparison #(.REGISTER_DESCRIPTOR(1)) saved_mode(.stimulus,.equivalent(equivalent[1]));
      task automatic check;
        #1;if(equivalent!==2'b11)$fatal(1,"Tile context differs at sample %0d",checks);
        checks++;
      endtask
      initial begin
        for(integer trial=0;trial<32;trial++)begin
          for(integer bit_index=0;bit_index<35;bit_index++)begin
            random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
            stimulus[bit_index]=random_state[0];
          end
          if(trial%4==0)stimulus='0;
          if(trial%4==1)stimulus='1;
          saved=stimulus;check();
          for(integer bit_index=0;bit_index<35;bit_index++)begin
            stimulus=saved;stimulus[bit_index]=1'bx;check();
            stimulus=saved;stimulus[bit_index]=1'bz;check();
          end
          stimulus='x;check();stimulus='z;check();
        end
        $display("TILE_CONTEXT_FOUR_STATE_PASS checks=%0d",checks);$finish;
      end
    endmodule
""")
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", sources[-1], bench],
        out / "four_state_compile.log")
    run(["vvp", out / "four_state.vvp"], out / "four_state.log")
    if "TILE_CONTEXT_FOUR_STATE_PASS checks=2336" not in (out / "four_state.log").read_text():
        raise RuntimeError("接收资格四态检查未完成")
    if any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError("检查期间源码发生变化")
    result = {"passed": True, "state_bits_unconstrained": 27, "formal_profiles": results,
              "four_state_vectors": 2336, "configurations_per_vector": 2,
              "source_sha256": hashes, "model_sha256": digest(model_file), "checker_sha256": digest(__file__)}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("TILE_CONTEXT_PASS", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
