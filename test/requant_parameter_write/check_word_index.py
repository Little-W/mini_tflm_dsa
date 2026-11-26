#!/usr/bin/env python3
"""检查参数末次写入资格的完整范围、四态行为和装载周期。"""
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
SOURCE = "rtl/npu/writeback/vec_requant.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run([str(item) for item in command], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/requant_word_index")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference", default="584233d8564344715d90936ba25afbabef03b897")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = args.source_root.resolve() / SOURCE
    content = path.read_text()
    if args.reference_root is not None:
        reference = (args.reference_root.resolve() / SOURCE).read_text()
        reference_identifier = str(args.reference_root.resolve())
    else:
        reference_identifier = subprocess.check_output(
            ["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip()
        reference = subprocess.check_output(
            ["git", "show", reference_identifier + ":" + SOURCE], cwd=ROOT, text=True)
    def controller(text):
        first = text.index("  // 主状态机")
        last = text.index("  // 数据通路（", first)
        return re.sub(r"\s+", "", text[first:last])
    if controller(content) != controller(reference):
        raise RuntimeError("参数装载控制的状态转移或更新条件发生变化")
    # 完整生产辅助模块直接参与证明，参考表达式独立定义索引截断顺序。
    helper_path = args.source_root.resolve() / "rtl/npu/writeback/requant_parameter_last.sv"
    helper_content = helper_path.read_text() if helper_path.is_file() else content
    match = re.search(r"^module requant_parameter_last\b.*?^endmodule", helper_content, re.M | re.S)
    if match is None:
        raise RuntimeError("缺少完整参数末次写入比较模块")
    helper = match[0]
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    reports = []
    profiles = [(1,1,0),(1,2,0),(1,2,1),(3,3,0),(3,3,1),(3,3,2),
                (8,2,0),(8,2,1),(9,2,0),(9,2,1),(16,8,0),(16,8,7),(31,2,0),(31,2,1),
                (32,2,0),(32,2,1),(32,4,3),(36,2,0),(36,2,1),(36,3,2)]
    for width, banks, word_index in profiles:
        folder = out / f"index{width}_banks{banks}_word{word_index}"
        folder.mkdir(exist_ok=True)
        source = folder / "last_parameter.sv"
        source.write_text(f"""module last_parameter(
    input wire [31:0] quant_need_load_r,
    input wire [{width-1}:0] quant_rsp_idx,
    output logic actual, output wire expected, equal);
    localparam integer PARAM_BANKS={banks}, QBUF_IDX_W={width}, word={word_index};
    wire [QBUF_IDX_W-1:0] reference_index = quant_rsp_idx + QBUF_IDX_W'(word);
    requant_parameter_last #(.p_index_width(QBUF_IDX_W), .p_banks(PARAM_BANKS), .p_word(word)) dut (
        .i_index(quant_rsp_idx), .i_limit(quant_need_load_r), .o_last(actual)
    );
    assign expected = ({{1'b0, 32'(reference_index)}} + 33'(PARAM_BANKS)) >=
        {{1'b0, quant_need_load_r}};
    assign equal = actual == expected;
endmodule
{helper}
""")
        script = folder / "proof.ys"
        sources = resolve([source], args.source_root.resolve())
        script.write_text("read_slang --top last_parameter -DSYNTHESIS=1 " + shlex.join(list(map(str, sources))) + "\n"
                          "prep -top last_parameter -flatten\n"
                          "sat -verify -prove equal 1 -show-inputs -show-outputs\n")
        execute([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                folder / "formal.log")
        bench = folder / "tb.sv"
        bench.write_text(f"""module tb;
    reg [31:0] quant_need_load_r;
    reg [{width-1}:0] quant_rsp_idx;
    reg [31:0] saved_size;
    reg [{width-1}:0] saved_index;
    wire actual, expected, equal;
    integer checks=0, seed=20261125;
    last_parameter dut(.*);
    task verify; begin
        #1;
        if(actual !== expected) $fatal(1,"参数末次写入资格不一致");
        checks++;
    end endtask
    initial begin
        seed=$urandom(seed);
        for(integer sample=0;sample<10000;sample++) begin
            quant_rsp_idx={{$urandom,$urandom}};
            case(sample%11)
                0:quant_rsp_idx='0;
                1:quant_rsp_idx='1;
                2:quant_rsp_idx[{min(width,32)-1}:0]='1;
                3:quant_rsp_idx={width}'(1);
                4:quant_rsp_idx={width}'(32'hfffffffe);
                default:begin end
            endcase
            quant_need_load_r=$urandom;
            case(sample%8)
                0:quant_need_load_r=0;
                1:quant_need_load_r={banks};
                2:quant_need_load_r={banks+1};
                3:quant_need_load_r=32'({width}'(quant_rsp_idx+{width}'({word_index})))+{banks};
                4:quant_need_load_r=32'({width}'(quant_rsp_idx+{width}'({word_index})))+{banks+1};
                5:quant_need_load_r=32'hffffffff;
                default:begin end
            endcase
            verify(); saved_size=quant_need_load_r; saved_index=quant_rsp_idx;
            quant_need_load_r[sample%32]=1'bx; verify();
            quant_need_load_r=saved_size;quant_rsp_idx[sample%{width}]=1'bz;verify();
            quant_rsp_idx=saved_index;
        end
        $display("LAST_PARAMETER_PASS checks=%0d",checks);$finish;
    end
endmodule
""")
        binary = folder / "simulation"
        execute(["iverilog", "-g2012", "-s", "tb", "-o", binary, *sources, bench], folder / "compile.log")
        execute(["vvp", binary], folder / "simulation.log")
        if "LAST_PARAMETER_PASS checks=30000" not in (folder / "simulation.log").read_text():
            raise RuntimeError("参数末次写入资格的四态检查未完成")
        reports.append(dict(index_width=width, banks=banks, word=word_index, passed=True,
                            input_bits=width+32, four_state_comparisons=30000,
                            formal_log_sha256=digest(folder / "formal.log"),
                            simulation_log_sha256=digest(folder / "simulation.log")))
    if content != path.read_text():
        raise RuntimeError("检查期间生产源码发生变化")
    result = dict(passed=True, source_sha256=digest(path), reference=reference_identifier,
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  helper_sha256=hashlib.sha256(helper_content.encode()).hexdigest(),
                  control_updates_unchanged=True, input_assumptions=[], random_seed=20261125, profiles=reports,
                  four_state_comparisons=sum(row["four_state_comparisons"] for row in reports))
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(reports),
                      "four_state_comparisons": result["four_state_comparisons"],
                      "source_sha256": result["source_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
