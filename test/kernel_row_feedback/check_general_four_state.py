#!/usr/bin/env python3
"""比较非二次幂和单通道配置的公开输出与行反馈四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, pattern, value):
    text, count = re.subn(pattern, value, text)
    if count != 1:
        raise RuntimeError("完整四态测试结构未匹配：" + pattern)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepared, out = args.prepared.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads((prepared / "summary.json").read_text())
    if not report["passed"]:
        raise RuntimeError("完整四态比较尚未完成")
    for name, expected in report["source_sha256"].items():
        if digest(Path(name)) != expected:
            raise RuntimeError("源文件与准备结果不同：" + name)
    original_bench = prepared / "tb_loader_four_state.sv"
    records = []
    for profile in (dict(SIZE=6, DATA_WIDTH=16, BUS_WIDTH=24, DMA_LANES=3, COUNT_WIDTH=7),
                    dict(SIZE=4, DATA_WIDTH=8, BUS_WIDTH=8, DMA_LANES=1, COUNT_WIDTH=8)):
        parameters = report["parameters"] | profile
        folder = out / f"lanes_{parameters['DMA_LANES']}"
        folder.mkdir(exist_ok=True)
        bench = original_bench.read_text()
        for name, value in parameters.items():
            bench = replace_once(bench, rf"localparam int {name} = \d+;",
                                 f"localparam int {name} = {value};")
        bench = replace_once(bench, r"sample<\d+", "sample<4000")
        bench = replace_once(bench, r"known_positions < \d+", "known_positions < 100")
        bench = replace_once(bench, r"  task automatic tick;", """  integer nonzero_feedback_words = 0, finished_rows = 0;
  task automatic tick;""")
        bench = replace_once(bench, r"    checked_cycles\+\+;", """    if ($isunknown(dut.last_ext_beat) || $isunknown(reference_loader.last_ext_beat))
      $fatal(1, "Row completion must be a resolved conditional result");
    if (dut.last_ext_beat) finished_rows++;
    for (int column=0; column<SIZE; column++) begin
      if (dut.row_acc[column] !== reference_loader.row_acc[column])
        $fatal(1, "Row feedback mismatch, column=%0d cycle=%0d", column, checked_cycles);
      if (!$isunknown(dut.row_acc[column]) && dut.row_acc[column] != '0)
        nonzero_feedback_words++;
    end
    checked_cycles++;""")
        bench = replace_once(bench, r"    repeat \(4\) tick\(\);", """    repeat (4) tick();
    rst_n = 1'b1;
    // 两个实现采用相同返回资格，独立检查列更新及完成条件的四态输入。
    force dut.response_accept = 1'b1;
    force reference_loader.response_accept = 1'b1;
    for (int transfer=0; transfer<32; transfer++) begin
      ext_dma_wr_slot = 1'b0;
      ext_dma_wr_col_base = (transfer % ((SIZE+DMA_LANES-1)/DMA_LANES))*DMA_LANES;
      for (int lane=0; lane<DMA_LANES; lane++) begin
        ext_dma_wr_valid[lane] = 1'b1;
        ext_dma_wr_data[lane] = DATA_WIDTH'(transfer*DMA_LANES+lane+1);
      end
      case (transfer % 8)
        0: ext_dma_wr_valid[0] = 1'bx;
        1: ext_dma_wr_col_base[0] = 1'bx;
        2: ext_dma_wr_data[0][0] = 1'bx;
        3: ext_dma_wr_valid[0] = 1'bz;
        4: ext_dma_wr_data[0][0] = 1'bz;
        default: ;
      endcase
      tick();
    end
    release dut.response_accept;
    release reference_loader.response_accept;""")
        bench = replace_once(bench, r"    \$finish;", """    if (nonzero_feedback_words == 0 || finished_rows == 0)
      $fatal(1, "Row data and completion coverage required");
    $display("ROW_FEEDBACK_PASS nonzero_words=%0d completed_rows=%0d", nonzero_feedback_words, finished_rows);
    $finish;""")
        if parameters["DMA_LANES"] == 1:
            # 单通道端口连接其唯一数组元素。
            for name in ("ext_dma_wr_data", "ext_dma_wr_valid"):
                bench = bench.replace(f".{name}({name})", f".{name}({name}[0])")
        target = folder / "tb_general_four_state.sv"
        target.write_text(bench)
        command = list(report["compile_command"])
        command[command.index("-o") + 1] = str(folder / "compare.vvp")
        command = [str(target) if item == str(original_bench) else item for item in command]
        sources = [Path(item) for item in command if Path(item).suffix in (".sv", ".v")]
        hashes = {str(path): digest(path) for path in sources}
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(["vvp", str(folder / "compare.vvp")], text=True,
                                capture_output=True, timeout=180, check=True)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        match = re.search(r"KERNEL_LOADER_FOUR_STATE_PASS cycles=(\d+) outputs=(\d+) known_positions=(\d+)",
                          result.stdout)
        coverage = re.search(r"ROW_FEEDBACK_PASS nonzero_words=(\d+) completed_rows=(\d+)", result.stdout)
        if match is None or int(match[1]) != 4036 or int(match[2]) != report["compared_outputs"] or not coverage:
            raise RuntimeError(str(folder / "run.log"))
        if hashes != {str(path): digest(path) for path in sources}:
            raise RuntimeError("验证期间源文件发生变化")
        record = dict(passed=True, parameters=parameters, cycles=int(match[1]),
                      compared_outputs=int(match[2]), known_positions=int(match[3]),
                      nonzero_feedback_words=int(coverage[1]), completed_rows=int(coverage[2]),
                      source_sha256=hashes, compile_command=command)
        records.append(record)
        print(json.dumps({key: record[key] for key in ("parameters", "cycles", "nonzero_feedback_words", "completed_rows")}))
    summary = dict(passed=True, profiles=records, prepared_summary_sha256=digest(prepared / "summary.json"))
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
