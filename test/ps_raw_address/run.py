#!/usr/bin/env python3
"""验证倒数常量的类型扩展，并遍历生产地址的全部商与余数。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], log: Path, cwd: Path) -> str:
    with log.open("w") as stream:
        subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, check=True)
    return log.read_text()


def reciprocal_expression(source: str) -> str:
    found = re.search(r"localparam\s+\[WIDTH:0\]\s+RECIPROCAL\s*=([^;]+);", source)
    if found is None:
        raise ValueError("源文件中未找到 RECIPROCAL 参数")
    return found.group(1).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="caace947")
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.out.resolve()
    inputs = out / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    relative = Path("rtl/npu/ps_compact/ps_raw_address.sv")
    production = root / relative
    current = inputs / "ps_raw_address.sv"
    current.write_bytes(production.read_bytes())
    reference_commit = subprocess.check_output(
        ["git", "rev-parse", args.reference], cwd=root, text=True
    ).strip()
    reference_bytes = subprocess.check_output(
        ["git", "show", f"{reference_commit}:{relative.as_posix()}"], cwd=root
    )
    reference = inputs / "ps_raw_address_reference_source.sv"
    reference.write_bytes(reference_bytes)
    renamed_reference = inputs / "ps_raw_address_reference.sv"
    renamed_reference.write_text(re.sub(
        r"\bmodule\s+ps_raw_address\b", "module ps_raw_address_reference",
        reference_bytes.decode(), count=1
    ))
    old_expression = reciprocal_expression(reference.read_text())
    new_expression = reciprocal_expression(current.read_text())
    report = {
        "passed": False,
        "reference_commit": reference_commit,
        "source_sha256": {relative.as_posix(): digest(current)},
        "reference_source_sha256": {relative.as_posix(): digest(reference)},
        "constant_parameter_domain": {
            "width_minimum": 1, "width_maximum": 63,
            "divisor_minimum": 1, "divisor_maximum": 2147483647,
            "divisor_type": "signed 32-bit integer",
        },
        "arithmetic_bounds": {
            "largest_intermediate_sum": str((1 << 63) + (1 << 31) - 1),
            "unsigned_64_limit": str(1 << 64),
            "reciprocal_maximum": "2**WIDTH",
            "reciprocal_storage_bits": "WIDTH+1",
        },
        "formal": {"passed": False},
        "elaboration": {"passed": False},
        "numeric": {"passed": False},
    }
    summary = out / "summary.json"

    def save() -> None:
        summary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    proof = inputs / "reciprocal_constant_proof.sv"
    proof.write_text(f"""`default_nettype none
module reciprocal_constant_proof(input wire signed [31:0] DIVISOR);
    always_comb assume (DIVISOR > 0);
    // 同时覆盖全部正整数除数，每个展开分支检查一个固定地址位宽。
    for (genvar width_index=1; width_index<=63; width_index++) begin : g_width
        localparam integer WIDTH=width_index;
        wire [WIDTH:0] reference_value={old_expression};
        wire [WIDTH:0] current_value={new_expression};
        always_comb assert (current_value == reference_value);
    end
endmodule
`default_nettype wire
""")
    script = out / "constant_proof.ys"
    script.write_text(
        "read_slang --top reciprocal_constant_proof " + shlex.quote(str(proof)) +
        "\nprep -top reciprocal_constant_proof -flatten\nopt -full\n"
        "chformal -lower\nsat -set-assumes -prove-asserts -verify -timeout 60\n"
    )
    run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"),
         "--worker", str(script)], out / "constant_proof.log", root)
    report["formal"] = {
        "passed": True, "width_configurations": 63,
        "all_positive_signed_32_divisors": True,
        "proof_source_sha256": digest(proof),
    }
    save()

    divisors = list(range(1, 9)) + [15, 16, 17, 255, 256, 257, 65535, 65536, 65537, 2147483647]
    constant_tb = inputs / "tb_reciprocal_constants.sv"
    lines = ["module tb_reciprocal_constants;"]
    constant_count = 0
    for width in range(1, 64):
        for divisor in divisors:
            expected = ((1 << width) + divisor - 1) // divisor
            lines += [f"  if (1) begin : g_w{width}_d{divisor}",
                      f"    localparam integer WIDTH={width}, DIVISOR={divisor};",
                      f"    localparam [WIDTH:0] reference_value={old_expression};",
                      f"    localparam [WIDTH:0] current_value={new_expression};",
                      f"    initial if (reference_value !== (WIDTH+1)'(64'h{expected:016x}) ||",
                      f"                current_value !== (WIDTH+1)'(64'h{expected:016x}))",
                      f"      $fatal(1, \"Reciprocal mismatch WIDTH={width} DIVISOR={divisor}\");",
                      "  end"]
            constant_count += 1
    lines += [f'  initial begin #1; $display("RECIPROCAL_CONSTANTS_PASS cases={constant_count}"); $finish; end',
              "endmodule"]
    constant_tb.write_text("\n".join(lines) + "\n")
    constant_binary = out / "constants.vvp"
    run(["iverilog", "-g2012", "-s", "tb_reciprocal_constants", "-o",
         str(constant_binary), str(constant_tb)], out / "constants_compile.log", root)
    text = run(["vvp", str(constant_binary)], out / "constants_simulation.log", root)
    if f"RECIPROCAL_CONSTANTS_PASS cases={constant_count}" not in text:
        raise RuntimeError("常量展开检查没有完成")
    constant_binary.unlink()
    report["elaboration"] = {
        "passed": True, "widths": list(range(1, 64)), "divisors": divisors,
        "constant_configurations": constant_count,
        "reference_arithmetic": "Python arbitrary-precision integers",
        "testbench_sha256": digest(constant_tb),
    }
    save()

    numeric_tb = inputs / "tb_ps_raw_address.sv"
    numeric_tb.write_text("""`timescale 1ns/1ps
module tb_ps_raw_address;
    logic [15:0] linear;
    wire [15:0] quotient [0:2], reference_quotient [0:2];
    wire [2:0] remainder [0:2], reference_remainder [0:2];
    integer cases=0;
    for (genvar index=0; index<3; index++) begin : g_divisor
        ps_raw_address #(.WIDTH(16), .DIVISOR(index+5)) dut (
            .linear(linear), .quotient(quotient[index]), .remainder(remainder[index]));
        ps_raw_address_reference #(.WIDTH(16), .DIVISOR(index+5)) reference_dut (
            .linear(linear), .quotient(reference_quotient[index]), .remainder(reference_remainder[index]));
    end
    initial begin
        for (integer value=0; value<65536; value++) begin
            linear=16'(value);
            #1;
            for (integer index=0; index<3; index++) begin
                if (quotient[index] !== 16'(value/(index+5)) ||
                    remainder[index] !== 3'(value%(index+5)) ||
                    quotient[index] !== reference_quotient[index] ||
                    remainder[index] !== reference_remainder[index])
                    $fatal(1, "Address mismatch linear=%0d divisor=%0d", value, index+5);
                cases++;
            end
        end
        if (cases != 196608) $fatal(1, "Incomplete address coverage");
        $display("PS_RAW_ADDRESS_PASS cases=%0d quotient_checks=%0d remainder_checks=%0d", cases, cases, cases);
        $finish;
    end
endmodule
""")
    numeric_binary = out / "numeric.vvp"
    run(["iverilog", "-g2012", "-s", "tb_ps_raw_address", "-o", str(numeric_binary),
         str(current), str(renamed_reference), str(numeric_tb)], out / "numeric_compile.log", root)
    text = run(["vvp", str(numeric_binary)], out / "numeric_simulation.log", root)
    line = next(line for line in text.splitlines() if line.startswith("PS_RAW_ADDRESS_PASS"))
    counts = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
    if counts != {"cases": 196608, "quotient_checks": 196608, "remainder_checks": 196608}:
        raise RuntimeError("商余数检查数量不符")
    numeric_binary.unlink()
    report["numeric"] = {
        "passed": True, "width": 16, "divisors": [5, 6, 7],
        "inputs_per_divisor": 65536, **counts,
        "reciprocals": [13108, 10923, 9363],
        "reference": "caace RTL and independent integer division/remainder",
        "testbench_sha256": digest(numeric_tb),
    }
    if digest(production) != report["source_sha256"][relative.as_posix()]:
        raise RuntimeError("生产源码摘要与本次验证副本不一致")
    report["snapshot_sha256"] = {
        str(path.relative_to(out)): digest(path) for path in sorted(inputs.iterdir()) if path.is_file()
    }
    report["passed"] = True
    save()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
