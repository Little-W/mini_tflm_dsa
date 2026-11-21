#!/usr/bin/env python3
"""验证平衡前缀加法器的完整二值结果及四态传播。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REQUESTED_WIDTHS = (1, 4, 7, 8, 9, 16, 17, 18, 32, 35, 48, 64)
ADDITIONAL_WIDTHS = (33, 34)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(source: Path, destination: Path, name: str) -> None:
    text, count = re.subn(
        r"\bmodule\s+parallel_prefix_add\b", f"module {name}",
        source.read_text(), count=1,
    )
    if count != 1:
        raise ValueError(f"未找到 parallel_prefix_add 模块：{source}")
    destination.write_text(text)


FORMAL = """module prefix_tree_formal #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_group_width = 8,
    parameter bit p_preserve_groups = 1'b0
) (
    input logic [p_width-1:0] i_a, i_b,
    input logic i_carry,
    output logic o_equal
);
    logic [p_width:0] reference_result, candidate_result, arithmetic_result;
    prefix_add_reference #(
        .p_width(p_width), .p_group_width(p_group_width),
        .p_preserve_groups(p_preserve_groups)
    ) u_reference (
        .i_a, .i_b, .i_carry,
        .o_sum(reference_result[p_width-1:0]), .o_carry(reference_result[p_width])
    );
    prefix_add_candidate #(
        .p_width(p_width), .p_group_width(p_group_width),
        .p_preserve_groups(p_preserve_groups)
    ) u_candidate (
        .i_a, .i_b, .i_carry,
        .o_sum(candidate_result[p_width-1:0]), .o_carry(candidate_result[p_width])
    );
    // 扩展一位后相加，同时检查全部结果位和最终进位。
    assign arithmetic_result = {1'b0, i_a} + {1'b0, i_b} + (p_width+1)'(i_carry);
    assign o_equal = (reference_result == candidate_result) &&
                     (reference_result == arithmetic_result) &&
                     (candidate_result == arithmetic_result);
endmodule
"""


FOUR_STATE_CASE = """module prefix_four_state_case #(
    parameter integer p_width = 8,
    parameter integer p_group_width = 4,
    parameter bit p_preserve_groups = 1'b0
) (output logic o_done);
    logic [p_width-1:0] i_a, i_b;
    logic i_carry;
    wire [p_width:0] reference_result, candidate_result;
    integer checked, changed, additional_unknown_bits, carry_only_checked;
    integer code, index, pattern, operand, symbol, carry_code;
    logic [p_width-1:0] pattern_a, pattern_b;

    prefix_add_reference #(
        .p_width(p_width), .p_group_width(p_group_width),
        .p_preserve_groups(p_preserve_groups)
    ) u_reference (
        .i_a, .i_b, .i_carry,
        .o_sum(reference_result[p_width-1:0]), .o_carry(reference_result[p_width])
    );
    prefix_add_candidate #(
        .p_width(p_width), .p_group_width(p_group_width),
        .p_preserve_groups(p_preserve_groups)
    ) u_candidate (
        .i_a, .i_b, .i_carry,
        .o_sum(candidate_result[p_width-1:0]), .o_carry(candidate_result[p_width])
    );

    function automatic logic four_state_symbol(input integer value);
        case (value & 3)
            0: four_state_symbol = 1'b0;
            1: four_state_symbol = 1'b1;
            2: four_state_symbol = 1'bx;
            3: four_state_symbol = 1'bz;
        endcase
    endfunction

    task automatic check_result;
        integer bit_index;
        begin
            #1;
            checked = checked + 1;
            if (candidate_result !== reference_result) begin
                $fatal(1, "完整四态结果不一致 width=%0d group=%0d a=%b b=%b carry=%b expected=%b result=%b", p_width, p_group_width, i_a, i_b, i_carry, reference_result, candidate_result);
            end
            for (bit_index = 0; bit_index <= p_width; bit_index = bit_index + 1) begin
                if (candidate_result[bit_index] === 1'b0 || candidate_result[bit_index] === 1'b1) begin
                    if (candidate_result[bit_index] !== reference_result[bit_index]) begin
                        $fatal(1, "已知结果发生差异 width=%0d group=%0d bit=%0d", p_width, p_group_width, bit_index);
                    end
                end else if (reference_result[bit_index] === 1'b0 || reference_result[bit_index] === 1'b1) begin
                    additional_unknown_bits = additional_unknown_bits + 1;
                end
            end
            if (!$isunknown({i_a, i_b})) begin
                carry_only_checked = carry_only_checked + 1;
                if (candidate_result !== reference_result) begin
                    $fatal(1, "操作数已知时结果不一致 width=%0d group=%0d", p_width, p_group_width);
                end
            end
        end
    endtask

    initial begin
        o_done = 1'b0;
        checked = 0;
        changed = 0;
        additional_unknown_bits = 0;
        carry_only_checked = 0;
        if (p_width <= 4) begin
            // 小位宽遍历两个操作数与输入进位的全部四态组合。
            for (code = 0; code < (1 << (2*(2*p_width+1))); code = code + 1) begin
                for (index = 0; index < p_width; index = index + 1) begin
                    i_a[index] = four_state_symbol(code >> (2*index));
                    i_b[index] = four_state_symbol(code >> (2*(p_width+index)));
                end
                i_carry = four_state_symbol(code >> (4*p_width));
                check_result();
            end
        end else begin
            // 大位宽逐位注入 X/Z，覆盖产生、阻断、交替位和跨组传播。
            for (pattern = 0; pattern < 6; pattern = pattern + 1) begin
                for (index = 0; index < p_width; index = index + 1) begin
                    case (pattern)
                        0: begin pattern_a[index] = 0; pattern_b[index] = 0; end
                        1: begin pattern_a[index] = 1; pattern_b[index] = 1; end
                        2: begin pattern_a[index] = index % 2; pattern_b[index] = !(index % 2); end
                        3: begin pattern_a[index] = index % 2; pattern_b[index] = index % 2; end
                        4: begin pattern_a[index] = index % p_group_width == p_group_width-1; pattern_b[index] = pattern_a[index]; end
                        5: begin pattern_a[index] = 1; pattern_b[index] = 0; end
                    endcase
                end
                for (carry_code = 0; carry_code < 4; carry_code = carry_code + 1) begin
                    i_a = pattern_a;
                    i_b = pattern_b;
                    i_carry = four_state_symbol(carry_code);
                    check_result();
                    for (operand = 0; operand < 2; operand = operand + 1) begin
                        for (index = 0; index < p_width; index = index + 1) begin
                            for (symbol = 2; symbol < 4; symbol = symbol + 1) begin
                                i_a = pattern_a;
                                i_b = pattern_b;
                                if (operand == 0) i_a[index] = four_state_symbol(symbol);
                                else i_b[index] = four_state_symbol(symbol);
                                check_result();
                            end
                        end
                    end
                end
            end
        end

        $display("FOUR_STATE_PROFILE width=%0d group=%0d preserve=%0d checked=%0d changed=%0d additional_unknown_bits=%0d carry_only_checked=%0d", p_width, p_group_width, p_preserve_groups, checked, changed, additional_unknown_bits, carry_only_checked);
        o_done = 1'b1;
    end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--reference", type=Path, default=HERE / "reference_prefix.sv")
    parser.add_argument("--candidate", type=Path, default=ROOT / "rtl/common/parallel_prefix_add.sv")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    root = args.repo.resolve()
    reference = (args.reference or root / "rtl/common/parallel_prefix_add.sv").resolve()
    candidate = args.candidate.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {"reference": reference, "candidate": candidate}
    initial_hashes = {key: sha256(path) for key, path in sources.items()}
    copied = {key: out / f"{key}.sv" for key in sources}
    for key, path in sources.items():
        snapshot(path, copied[key], f"prefix_add_{key}")
    formal = out / "formal.sv"
    formal.write_text(FORMAL)
    profiles = [
        (width, group, preserve)
        for width in sorted(REQUESTED_WIDTHS + ADDITIONAL_WIDTHS)
        for group in (4, 8) for preserve in (0, 1)
    ]

    profiles += [(width, group, preserve) for width in (1, 2, 4)
                 for group in (1, 2) for preserve in (0, 1)]

    def prove(profile: tuple[int, int, int]) -> dict:
        width, group, preserve = profile
        folder = out / f"w{width}_g{group}_p{preserve}"
        folder.mkdir(exist_ok=True)
        script, log = folder / "formal.ys", folder / "formal.log"
        options = f"-Gp_width={width} -Gp_group_width={group} -Gp_preserve_groups={preserve}"
        script.write_text(
            f"read_slang --top prefix_tree_formal {options} " +
            shlex.join(map(str, [*copied.values(), formal])) + "\n" +
            "prep -top prefix_tree_formal -flatten\ncheck -assert\n" +
            "sat -verify -prove o_equal 1 -show-inputs -show-outputs\n"
        )
        with log.open("w") as stream:
            subprocess.run(
                [sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=True,
            )
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(f"证明未完成：{log}")
        print(f"SAT width={width} group={group} preserve={preserve}: PASS", flush=True)
        return {"width": width, "group_width": group, "preserve_groups": preserve,
                "unconstrained_input_bits": 2 * width + 1, "passed": True,
                "log": str(log)}

    formal_results = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(prove, profile) for profile in profiles]
        for future in as_completed(futures):
            formal_results.append(future.result())
    formal_results.sort(key=lambda row: (row["width"], row["group_width"], row["preserve_groups"]))
    report = {
        "passed": True,
        "input_sources": {key: {"path": str(path), "sha256": initial_hashes[key]} for key, path in sources.items()},
        "source_copy_change": "module names only",
        "pyosys_version": importlib.metadata.version("pyosys"),
        "two_state": {"passed": True, "input_assumptions": [],
                      "checked_outputs": "all sum bits and final carry; reference, candidate, and extended addition",
                      "requested_widths": list(REQUESTED_WIDTHS), "additional_production_widths": list(ADDITIONAL_WIDTHS),
                      "profiles": formal_results},
    }
    (out / "two_state_summary.json").write_text(json.dumps(report, indent=2) + "\n")

    testbench = out / "four_state.sv"
    top = ["module prefix_four_state_top;", f"wire [{len(profiles)-1}:0] done;"]
    for index, (width, group, preserve) in enumerate(profiles):
        top.append(f"prefix_four_state_case #(.p_width({width}), .p_group_width({group}), "
                   f".p_preserve_groups({preserve})) u_case_{index} (.o_done(done[{index}]));")
    top.extend(["initial begin wait (&done); #1; $display(\"FOUR_STATE_PASS\"); $finish; end", "endmodule"])
    testbench.write_text(FOUR_STATE_CASE + "\n" + "\n".join(top) + "\n")
    executable, compile_log, simulation_log = out / "four_state.vvp", out / "four_state_compile.log", out / "four_state.log"
    compile_command = ["iverilog", "-g2012", "-s", "prefix_four_state_top", "-o", str(executable),
                       *map(str, copied.values()), str(testbench)]
    with compile_log.open("w") as stream:
        subprocess.run(compile_command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    with simulation_log.open("w") as stream:
        subprocess.run(["vvp", str(executable)], stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=True)
    simulation_text = simulation_log.read_text()
    four_state_results = []
    for line in simulation_text.splitlines():
        if line.startswith("FOUR_STATE_PROFILE "):
            four_state_results.append({key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)})
    if "FOUR_STATE_PASS" not in simulation_text or len(four_state_results) != len(profiles):
        raise RuntimeError(f"四态检查未完成：{simulation_log}")
    for key, path in sources.items():
        if sha256(path) != initial_hashes[key]:
            raise RuntimeError(f"运行期间输入源码发生变化：{path}")
    difference_observed = any(row["changed"] for row in four_state_results)
    report["four_state"] = {
        "checks_passed": True, "difference_observed": difference_observed,
        "equivalent": not difference_observed,
        "scope": "all four-state patterns for widths 1, 2 and 4; per-bit X/Z injection for larger widths",
        "checked_properties": ["all result bits and carry match the reference with case equality",
                               "known operands give identical outputs for all four carry states"],
        "profiles": sorted(four_state_results, key=lambda row: (row["width"], row["group"], row["preserve"])),
        "examples": [line for line in simulation_text.splitlines() if line.startswith("FOUR_STATE_EXAMPLE ")],
        "compile_command": compile_command, "log": str(simulation_log),
    }
    if difference_observed:
        raise RuntimeError("四态结果比较未通过")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"完成 {len(profiles)} 组二值证明与四态检查：{out / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
