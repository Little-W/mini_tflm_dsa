#!/usr/bin/env python3
"""证明队列全部公开输出的逐周期关系，并穷举准备标志的四态输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RTL = Path("rtl/npu/dma/conv_window_queue.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def flag_model(name, text):
    first = text.index("descriptor_prepared<=1'b0")
    first = text.rindex("  always_ff", 0, first)
    end = text.index("  always_ff", first + 4)
    block = text[first:end]
    expressions = [re.search(r"  assign " + signal + r"\s*=.*?;", text, re.S).group()
                   for signal in ("launch", "descriptor_read_available")]
    if "  conv_window_prepared_flag u_prepared_flag" in text:
        expressions.append(re.search(r"  conv_window_prepared_flag u_prepared_flag.*?\);", text, re.S).group())
    return f"""module {name}(input logic clk,input logic [6:0] stimulus,output logic observed);
      logic rst_n,configure,descriptor_multiple,descriptor_available,frontend_valid,frontend_ready,accept;
      logic launch,descriptor_read_available,descriptor_prepared,descriptor_prepared_nxt;
      assign {{rst_n,configure,descriptor_multiple,descriptor_available,frontend_valid,frontend_ready,accept}}=stimulus;
      {chr(10).join(expressions)}
      {block}
      assign observed=descriptor_prepared;
    endmodule
"""


def columns_model(name, text):
    expressions = [re.search(r"  assign " + signal + r"\s*=.*?;", text, re.S).group()
                   for signal in ("launch", "descriptor_read_available", "descriptor_forward")]
    if "  conv_window_cols_candidates u_cols_candidates" in text:
        first = text.index("  conv_window_cols_candidates u_cols_candidates")
        region = text[first:text.index("  // 加一与减一", first)]
        expressions.append("  assign descriptor_request_cols_valid = request_cols_valid;")
        region = region.replace("always_ff @(posedge clk) frontend_cols_valid <= descriptor_cols_value;",
                                "assign observed = descriptor_cols_value;")
    else:
        first = text.index("frontend_cols_valid <=")
        first = text.rindex("  always_ff", 0, first)
        region = text[first:text.index("  // 加一与减一", first)]
        region = region.replace("always_ff @(posedge clk) begin", "always_comb begin\n    observed=frontend_cols_valid;", 1)
        region = region.replace("frontend_cols_valid <=", "observed =")
        region = region.replace("req_cols>0 && req_cols<=32'(p_max_cols)", "request_cols_valid")
    return f"""module {name}(input logic [8:0] stimulus,output logic observed);
      logic descriptor_available,descriptor_multiple,accept,frontend_valid,frontend_ready;
      logic request_cols_valid,descriptor_current_cols_valid,descriptor_next_cols_valid,frontend_cols_valid;
      logic descriptor_request_cols_valid,descriptor_cols_value,descriptor_cols_selected;
      logic descriptor_read_available,descriptor_forward,launch;
      logic [1:0] descriptor_cols_candidates;
      assign {{descriptor_available,descriptor_multiple,accept,frontend_valid,frontend_ready,
               request_cols_valid,descriptor_current_cols_valid,descriptor_next_cols_valid,frontend_cols_valid}}=stimulus;
      {chr(10).join(expressions)}
      {region}
    endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, reference, out = args.source_root.resolve(), args.reference_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root / RTL, reference / RTL, root / "rtl/common/regfile.v", reference / "rtl/common/regfile.v"]
    hashes = {str(path): digest(path) for path in sources}
    cases = []
    for depth, lanes, outstanding in ((2, 4, 1), (3, 8, 2), (4, 8, 3), (7, 16, 4)):
        directory = out / f"depth{depth}_lanes{lanes}_outstanding{outstanding}"
        directory.mkdir(exist_ok=True)
        commands = []
        for label, directory_root in (("gold", reference), ("gate", root)):
            options = ["--top", "conv_window_queue", "-DSYNTHESIS=1", f"-GDEPTH={depth}",
                       f"-GWINDOW_LANES={lanes}", f"-Gp_frontend_outstanding={outstanding}"]
            commands += ["read_slang " + shlex.join(options + [str(directory_root / "rtl/common/regfile.v"),
                                                                 str(directory_root / RTL)]),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top conv_window_queue -flatten", "check -assert", "memory_map",
                         "setundef -undriven -undef", "async2sync", "opt", "check -assert", f"rename conv_window_queue {label}", f"design -stash {label}"]
        commands += ["design -copy-from gold -as gold gold", "design -copy-from gate -as gate gate",
                     "equiv_make gold gate equivalent", "hierarchy -top equivalent", "equiv_simple -seq 1",
                     "equiv_induct -seq 3", "equiv_status -assert"]
        script, log = directory / "proof.ys", directory / "proof.log"
        script.write_text("\n".join(commands) + "\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
        if "Equivalence successfully proven!" not in log.read_text():
            raise RuntimeError("窗口队列公开输出证明未完成")
        cases.append({"depth": depth, "lanes": lanes, "outstanding": outstanding,
                      "passed": True, "log_sha256": digest(log)})
        print("WINDOW_QUEUE_PUBLIC_PASS", depth, lanes, outstanding, flush=True)
    candidate, original = sources[0].read_text(), sources[1].read_text()
    helper = re.search(r"(?m)^module conv_window_prepared_flag\b.*?endmodule", candidate, re.S).group()
    text = flag_model("candidate", candidate) + flag_model("reference", original) + helper + "\n"
    text += """module tb;
      logic clk=0;
      logic [6:0] stimulus;
      logic expected,actual;
      candidate u_candidate(.*,.observed(actual));
      reference u_reference(.*,.observed(expected));
      function automatic logic four_state(input integer value);
        case(value&3)0:four_state=0;1:four_state=1;2:four_state=1'bx;3:four_state=1'bz;endcase
      endfunction
      initial begin
        for(integer sample=0;sample<16384;sample++)begin
          for(integer bit_index=0;bit_index<7;bit_index++)stimulus[bit_index]=four_state(sample>>(2*bit_index));
          #1;clk=1;#1;
          if(expected!==actual)$fatal(1,"Prepared flag differs at sample %0d",sample);
          clk=0;#1;
        end
        $display("PREPARED_FLAG_FOUR_STATE_PASS checks=16384");$finish;
      end
    endmodule
"""
    model = out / "four_state.sv"
    model.write_text(text)
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", model], out / "four_state_compile.log")
    run(["vvp", out / "four_state.vvp"], out / "four_state.log")
    if "PREPARED_FLAG_FOUR_STATE_PASS checks=16384" not in (out / "four_state.log").read_text():
        raise RuntimeError("准备标志四态穷举未完成")
    columns_checks = 0
    if "module conv_window_cols_candidates" in candidate:
        columns_helper = "\n".join(
            re.search(r"(?m)^module " + module + r"\b.*?endmodule", candidate, re.S).group()
            for module in ("conv_window_cols_candidates", "conv_window_cols_select"))
        columns_text = (columns_model("candidate", candidate) + columns_model("reference", original) +
                        columns_helper + "\n")
        columns_text += """module tb;
          logic [8:0] stimulus;
          logic expected,actual;
          candidate u_candidate(.*,.observed(actual));
          reference u_reference(.*,.observed(expected));
          function automatic logic four_state(input integer value);
            case(value&3)0:four_state=0;1:four_state=1;2:four_state=1'bx;3:four_state=1'bz;endcase
          endfunction
          initial begin
            for(integer sample=0;sample<262144;sample++)begin
              for(integer bit_index=0;bit_index<9;bit_index++)stimulus[bit_index]=four_state(sample>>(2*bit_index));
              #1;if(expected!==actual)$fatal(1,"Column qualification differs at sample %0d",sample);
            end
            $display("COLUMNS_FOUR_STATE_PASS checks=262144");$finish;
          end
        endmodule
"""
        columns = out / "columns_four_state.sv"
        columns.write_text(columns_text)
        run(["iverilog", "-g2012", "-s", "tb", "-o", out / "columns_four_state.vvp", columns],
            out / "columns_four_state_compile.log")
        run(["vvp", out / "columns_four_state.vvp"], out / "columns_four_state.log")
        if "COLUMNS_FOUR_STATE_PASS checks=262144" not in (out / "columns_four_state.log").read_text():
            raise RuntimeError("列资格四态穷举未完成")
        columns_checks = 262144
    if any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError("检查期间源码发生变化")
    result = {"passed": True, "all_public_outputs": True, "output_valid_qualification": False,
              "state_assumptions": [], "cases": cases, "four_state_combinations": 16384,
              "column_four_state_combinations": columns_checks,
              "source_sha256": hashes, "model_sha256": digest(model), "checker_sha256": digest(__file__)}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("WINDOW_PREPARED_FLAG_PASS", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
