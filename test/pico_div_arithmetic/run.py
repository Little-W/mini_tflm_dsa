#!/usr/bin/env python3
"""验证 RV32M 除法算术的完整状态、四态行为和独立数值结果。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/soc/picorv32_npu.v"
STATE_WIDTHS = {
    "instr_div": 1, "instr_divu": 1, "instr_rem": 1, "instr_remu": 1,
    "pcpi_wait_q": 1, "dividend": 32, "divisor": 63, "quotient": 32,
    "quotient_msk": 32, "running": 1, "outsign": 1,
    "pcpi_wr": 1, "pcpi_rd": 32, "pcpi_wait": 1, "pcpi_ready": 1,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run(command: list[str], log: Path, timeout: int = 900) -> str:
    save(log.with_suffix(".command.json"), command)
    with log.open("w") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=timeout, check=True)
    return log.read_text()


def module_text(text: str, name: str) -> str:
    match = re.search(r"module picorv32_pcpi_div\s*\(.*?\nendmodule", text, re.S)
    if match is None:
        raise RuntimeError("无法定位完整除法模块")
    return match[0].replace("module picorv32_pcpi_div", "module " + name, 1)


def formal_division(out: Path, sources: dict[str, Path]) -> list[dict]:
    results = []
    for alternative_operations in (False, True):
        commands = []
        defines = "-D SYNTHESIS=1 -D XILINX_FPGA=1 "
        if alternative_operations:
            defines += "-D RISCV_FORMAL_ALTOPS=1 "
        for label, source in sources.items():
            commands += [
                "read_slang " + defines + "--top picorv32_pcpi_div " + shlex.quote(str(source)),
                "prep -top picorv32_pcpi_div -flatten", "async2sync", "opt_clean",
                f"rename picorv32_pcpi_div {label}", f"design -stash {label}",
            ]
        commands += [
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current equivalent", "hierarchy -top equivalent",
            "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2", "equiv_status -assert",
        ]
        script = out / f"division_{int(alternative_operations)}.ys"
        script.write_text("\n".join(commands) + "\n")
        log = script.with_suffix(".log")
        text = run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], log)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if match is None or int(match[2]):
            raise RuntimeError("除法模块状态等价检查未完成")
        results.append({"passed": True, "alternative_operations": alternative_operations,
                        "equivalent_bits": int(match[1]), "log_sha256": digest(log)})
    return results


COMMON_BENCH = r"""
module tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg resetn = 0, pcpi_valid = 0;
  reg [31:0] pcpi_insn = 0, pcpi_rs1 = 0, pcpi_rs2 = 0;
  wire reference_wr, reference_wait, reference_ready;
  wire current_wr, current_wait, current_ready;
  wire [31:0] reference_rd, current_rd;
  division_reference reference (.clk(clk), .resetn(resetn), .pcpi_valid(pcpi_valid),
    .pcpi_insn(pcpi_insn), .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
    .pcpi_wr(reference_wr), .pcpi_rd(reference_rd), .pcpi_wait(reference_wait),
    .pcpi_ready(reference_ready));
  division_current current (.clk(clk), .resetn(resetn), .pcpi_valid(pcpi_valid),
    .pcpi_insn(pcpi_insn), .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
    .pcpi_wr(current_wr), .pcpi_rd(current_rd), .pcpi_wait(current_wait),
    .pcpi_ready(current_ready));
  integer checks = 0;
"""


def simulate(out: Path, module_file: Path, label: str, body: str,
             synthesis: bool) -> dict:
    bench = out / f"{label}.sv"
    bench.write_text(COMMON_BENCH + body + "\nendmodule\n")
    binary = out / f"{label}.vvp"
    command = ["iverilog", "-g2012", "-s", "tb"]
    if synthesis:
        command.append("-DSYNTHESIS=1")
    command += ["-o", str(binary), str(module_file), str(bench)]
    run(command, out / f"{label}_build.log")
    log = out / f"{label}_run.log"
    text = run(["vvp", str(binary)], log, timeout=180)
    match = re.search(r"PASS checks=(\d+)", text)
    if match is None:
        raise RuntimeError("除法仿真未完成：" + label)
    return {"passed": True, "checks": int(match[1]), "synthesis_expression": synthesis,
            "log_sha256": digest(log)}


def four_state(out: Path, module_file: Path) -> dict:
    assignments = []
    comparisons = []
    for name, width in STATE_WIDTHS.items():
        assignments.append(f"""
      value = {{random_word(), random_word()}};
      if (sample_index[0]) begin
        for (integer bit_index = 0; bit_index < {width}; bit_index = bit_index + 1)
          value[bit_index] = four_value(2'(random_word()));
      end
      reference.{name} = {width}'(value);
      current.{name} = {width}'(value);
""")
        comparisons.append(f"""
      if (reference.{name} !== current.{name})
        $fatal(1, "State mismatch {name} sample=%0d ref=%h got=%h",
          sample_index, reference.{name}, current.{name});
      checks = checks + 1;
""")
    body = r"""
  reg [31:0] random_state = 32'h18ed539a;
  reg [63:0] value;
  function automatic [31:0] random_word;
    begin
      random_state = random_state ^ (random_state << 13);
      random_state = random_state ^ (random_state >> 17);
      random_state = random_state ^ (random_state << 5);
      random_word = random_state;
    end
  endfunction
  function automatic four_value(input [1:0] state_value);
    case (state_value)
      0: four_value = 1'b0;
      1: four_value = 1'b1;
      2: four_value = 1'bx;
      3: four_value = 1'bz;
    endcase
  endfunction
  initial begin
    for (integer sample_index = 0; sample_index < 20000; sample_index = sample_index + 1) begin
      @(negedge clk);
      resetn = sample_index % 16 ? 1'b1 : four_value(2'(sample_index >> 4));
      pcpi_valid = four_value(2'(sample_index >> 2));
      pcpi_insn = 32'h02000033 | ((4 + sample_index % 4) << 12);
      pcpi_rs1 = random_word(); pcpi_rs2 = random_word();
      if (sample_index[0]) begin
        for (integer bit_index = 0; bit_index < 32; bit_index = bit_index + 1) begin
          pcpi_rs1[bit_index] = four_value(2'(random_word()));
          pcpi_rs2[bit_index] = four_value(2'(random_word()));
        end
      end
""" + "\n".join(assignments) + r"""
      @(posedge clk); #1;
""" + "\n".join(comparisons) + r"""
    end
    $display("PASS checks=%0d", checks);
    $finish;
  end
"""
    report = simulate(out, module_file, "four_state", body, synthesis=False)
    report.update({"cycles": 20000, "compared_registers": STATE_WIDTHS,
                   "arbitrary_internal_state": True})
    return report


def numeric(out: Path, module_file: Path) -> dict:
    rng = random.Random(0x18ED539A)
    edges = [0, 1, 2, 3, 7, 0x7ffffffe, 0x7fffffff, 0x80000000,
             0x80000001, 0xfffffffe, 0xffffffff]
    pairs = [(a, b) for a in edges for b in edges]
    pairs += [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(1024)]
    vectors = []
    for function in range(4, 8):
        for a, b in pairs:
            lhs = a - (1 << 32) if function in (4, 6) and a >= (1 << 31) else a
            rhs = b - (1 << 32) if function in (4, 6) and b >= (1 << 31) else b
            if rhs == 0:
                quotient, remainder = -1, lhs
            else:
                quotient = abs(lhs) // abs(rhs)
                if (lhs < 0) != (rhs < 0):
                    quotient = -quotient
                remainder = lhs - quotient * rhs
            result = quotient if function in (4, 5) else remainder
            vectors.append(f"{function:x} {a:08x} {b:08x} {result & 0xffffffff:08x}\n")
    data = out / "division_vectors.txt"
    data.write_text("".join(vectors))
    body = r"""
  integer vector_file, fields, function_value, elapsed, cycles = 0;
  reg [31:0] a, b, expected;
  initial begin
    repeat (4) @(negedge clk);
    resetn = 1;
    vector_file = $fopen("VECTOR_FILE", "r");
    if (!vector_file) $fatal(1, "Cannot read division vectors");
    while (!$feof(vector_file)) begin
      fields = $fscanf(vector_file, "%h %h %h %h\n", function_value, a, b, expected);
      if (fields == 4) begin
        @(negedge clk);
        pcpi_insn = 32'h02000033 | (function_value << 12);
        pcpi_rs1 = a; pcpi_rs2 = b; pcpi_valid = 1;
        elapsed = 0;
        while (!current_ready) begin
          @(negedge clk);
          if ({reference_wr, reference_wait, reference_ready} !==
              {current_wr, current_wait, current_ready})
            $fatal(1, "Division handshake mismatch");
          if (reference_rd !== current_rd) $fatal(1, "Division cycle data mismatch");
          elapsed = elapsed + 1;
          if (elapsed > 40) $fatal(1, "Division timeout");
        end
        if (!current_wr || current_rd !== expected)
          $fatal(1, "Division result f=%0d a=%h b=%h expected=%h actual=%h",
            function_value, a, b, expected, current_rd);
        checks = checks + 1; cycles = cycles + elapsed;
        pcpi_valid = 0;
        repeat (4) @(negedge clk);
      end
    end
    $fclose(vector_file);
    $display("PASS checks=%0d transaction_cycles=%0d", checks, cycles);
    $finish;
  end
""".replace("VECTOR_FILE", str(data))
    report = simulate(out, module_file, "numeric", body, synthesis=True)
    report.update({"operations": ["DIV", "DIVU", "REM", "REMU"],
                   "vectors_sha256": digest(data), "independent_integer_model": True})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source-root", default=ROOT, type=Path)
    parser.add_argument("--reference", default="349e7d98")
    parser.add_argument("--skip-cpu-formal", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {"current": out / "current.v", "reference": out / "reference.v"}
    original = args.source_root.resolve() / SOURCE
    sources["current"].write_bytes(original.read_bytes())
    sources["reference"].write_bytes(subprocess.check_output(
        ["git", "show", args.reference + ":" + SOURCE], cwd=ROOT))
    source_hash = digest(original)
    module_file = out / "division_modules.v"
    module_file.write_text("\n\n".join(
        module_text(source.read_text(), "division_" + label)
        for label, source in sources.items()))
    result = {"passed": False, "reference": args.reference,
              "source_sha256": source_hash, "reference_sha256": digest(sources["reference"]),
              "inputs_constrained": False}
    result["division_formal"] = formal_division(out, sources)
    result["four_state"] = four_state(out, module_file)
    result["numeric"] = numeric(out, module_file)
    if not args.skip_cpu_formal:
        helper = ROOT / "test/pico_pc_arithmetic/run.py"
        spec = importlib.util.spec_from_file_location("pico_full_formal", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result["cpu_formal"] = module.formal(out / "cpu_formal", sources)
        result["cpu_formal_helper_sha256"] = digest(helper)
    if source_hash != digest(original):
        raise RuntimeError("验证期间源文件发生变化")
    result["passed"] = True
    save(out / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
