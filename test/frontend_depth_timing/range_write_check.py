#!/usr/bin/env python3
"""从实际时钟过程提取组范围完整下一值，证明全部控制输入下逐位一致。"""
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
REFERENCE = Path(__file__).resolve().parent / "range_reference.sv"


class RangeStatements:
    """保留目标赋值及决定其执行顺序的原始 if、case 和语句块。"""

    def __init__(self, text):
        self.text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)

    def skip(self, pos):
        while pos < len(self.text) and self.text[pos].isspace():
            pos += 1
        return pos

    def word(self, pos, value):
        return re.match(r"\b" + value + r"\b", self.text[pos:]) is not None

    def balanced(self, pos, opening="(", closing=")"):
        pos = self.skip(pos)
        assert self.text[pos] == opening
        start, depth = pos, 1
        pos += 1
        while depth:
            depth += (self.text[pos] == opening) - (self.text[pos] == closing)
            pos += 1
        return self.text[start:pos], pos

    def statement(self, pos):
        pos = self.skip(pos)
        if self.word(pos, "begin"):
            pos += 5
            pieces = []
            while not self.word(self.skip(pos), "end"):
                item, pos = self.statement(pos)
                if item:
                    pieces.append(item)
            pos = self.skip(pos) + 3
            return ("begin\n" + "\n".join(pieces) + "\nend" if pieces else ""), pos
        if self.word(pos, "if"):
            condition, pos = self.balanced(pos + 2)
            yes, pos = self.statement(pos)
            pos = self.skip(pos)
            no = ""
            if self.word(pos, "else"):
                no, pos = self.statement(pos + 4)
            if not yes and not no:
                return "", pos
            return "if " + condition + " " + (yes or ";") + (" else " + no if no else ""), pos
        if self.word(pos, "case"):
            expression, pos = self.balanced(pos + 4)
            arms = []
            while not self.word(self.skip(pos), "endcase"):
                start = pos = self.skip(pos)
                depth = 0
                while self.text[pos] != ":" or depth:
                    depth += self.text[pos] in "([{"
                    depth -= self.text[pos] in ")] }".replace(" ", "")
                    pos += 1
                label = self.text[start:pos]
                body, pos = self.statement(pos + 1)
                arms.append((label, body))
            pos = self.skip(pos) + 7
            if not any(body for _, body in arms):
                return "", pos
            return ("case " + expression + "\n" +
                    "\n".join(label + ": " + (body or ";") for label, body in arms) +
                    "\nendcase"), pos
        if self.word(pos, "for"):
            expression, pos = self.balanced(pos + 3)
            body, pos = self.statement(pos)
            return ("for " + expression + " " + body if body else ""), pos
        end = self.text.index(";", pos) + 1
        text = self.text[pos:end]
        match = re.fullmatch(r"group_range_q\s*<=\s*(.*);", text, re.S)
        return ("result = " + match[1] + ";" if match else ""), end


def extracted(source):
    first = source.index("  // 行切换、组切换和通道递增先选择范围")
    last = source.index("  // 当前通道和新描述符并行准备", first)
    helpers = source[first:last]
    if "range_context_write" in helpers:
        ff = helpers.index("always_ff")
        helper_text = helpers[:ff]
        statement_text = helpers[helpers.index("begin", ff):]
    else:
        helper_text = helpers
        first = source.index("  // 保存前端配置、描述符和坐标状态。")
        first = source.index("always_ff", first)
        statement_text = source[source.index("begin", first):]
    body, _ = RangeStatements(statement_text).statement(0)
    state_type = re.search(r"  typedef enum logic \[21:0\].*?  } st_t;", source, re.S).group(0)
    return state_type, helper_text, body


PORTS = """input logic [21:0] state,
input conv_im2col_pkg::conv_cfg_t c,
input logic rst_n,cfg_valid,cfg_ready,tile_commit,tile_invalid,tile_fast,
input logic cache_rsp_valid,cache_rsp_error,wr_valid,wr_ready,chunk_reaches_end,
input logic row_last_q,past_active_q,group_end_o_equal,group_shape_o_valid,
input logic [31:0] q0,decode_index,
input logic [CHUNK_COUNT_W-1:0] chunk_count,
input logic [TILE_COUNT_W-1:0] active_remaining,
input logic [p_saved_group_lanes:0] tile_channel_range,group_range_q,group_range_cfg,
input logic [5:0][p_saved_group_lanes:0] group_range_next"""
PARAMETERS = """parameter int SIZE=16,LANES=8,TILE_COUNT_W=$clog2(SIZE+1),
CHUNK_COUNT_W=$clog2(LANES+1),p_saved_group_lanes=LANES>4 && LANES<=8 ? 8 : 4"""
NAMES = ("state c rst_n cfg_valid cfg_ready tile_commit tile_invalid tile_fast "
         "cache_rsp_valid cache_rsp_error wr_valid wr_ready chunk_reaches_end "
         "row_last_q past_active_q group_end_o_equal group_shape_o_valid q0 decode_index "
         "chunk_count active_remaining tile_channel_range group_range_q group_range_cfg group_range_next").split()


def unit(name, source):
    if re.search(r"\bmodule\s+range_reference\b", source):
        return re.sub(r"\bmodule\s+range_reference\b", "module " + name, source, count=1)
    state_type, helpers, body = extracted(source)
    return f"module {name} #({PARAMETERS})(\n{PORTS},output logic [p_saved_group_lanes:0] result);\n" + state_type + """
typedef struct packed {
  logic invalid,fast;
  logic[p_saved_group_lanes:0] channel_range;
} tile_t;
tile_t committing_tile;
assign committing_tile={tile_invalid,tile_fast,tile_channel_range};
""" + helpers + "\nalways_comb begin\nresult=group_range_q;\n" + body + "\nend\nendmodule\n"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--candidate", type=Path, default=ROOT / "rtl/npu/conv/conv_im2col_frontend.sv")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = {"reference": args.reference.resolve(), "current": args.candidate.resolve()}
    hashes = {label: digest(path) for label, path in inputs.items()}
    text = "".join(unit(label, path.read_text()) for label, path in inputs.items())
    text += f"module comparison #({PARAMETERS})(\n{PORTS},output logic equivalent);\n"
    text += "logic[p_saved_group_lanes:0] expected,actual;\n"
    connections = ",".join(f".{name}({name})" for name in NAMES)
    for label, output in (("reference", "expected"), ("current", "actual")):
        text += f"{label} #(.SIZE(SIZE),.LANES(LANES)) u_{label}({connections},.result({output}));\n"
    text += "assign equivalent=expected==actual;\nendmodule\n"
    source = out / "range_write.sv"
    source.write_text(text)
    cases = []
    for size, lanes in ((2,1), (2,4), (2,16), (16,4), (16,5), (16,8), (16,16), (64,8)):
        name = f"s{size}_l{lanes}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        files = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", source]
        script.write_text(f"read_slang --top comparison -GSIZE={size} -GLANES={lanes} " +
                          shlex.join(map(str, files)) + "\nprep -top comparison -flatten\n"
                          "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("范围寄存器下一值证明未完成: " + name)
        cases.append(dict(SIZE=size, LANES=lanes, passed=True, log_sha256=digest(log)))
        print("RANGE_WRITE_PASS", name, flush=True)
    if hashes != {label: digest(path) for label, path in inputs.items()}:
        raise RuntimeError("验证期间前端源码发生变化")
    report = dict(passed=True, input_assumptions=[], cases=cases,
                  source_sha256=hashes, source_paths={k:str(v) for k,v in inputs.items()},
                  scope="Actual complete group-range next value for all 22-bit state encodings and arbitrary control/data inputs.",
                  generated_source_sha256=digest(source))
    origin = re.search(r"source_sha256:\s*([a-f0-9]{64})", inputs["reference"].read_text())
    if origin:
        report["reference_origin_sha256"] = origin[1]
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
