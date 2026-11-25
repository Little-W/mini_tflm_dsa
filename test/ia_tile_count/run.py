#!/usr/bin/env python3
"""证明 IA 配置分块数量的全部输入位，并检查四态算术传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/loaders/ia_loader.sv"
CASES = ((32, 16), (32, 8), (32, 3), (16, 16), (17, 32), (7, 4), (64, 16), (32, 1))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(source, name):
    first = source.index("    assign packed_reduction_nxt =")
    last = source.index("    // 配置接收时先求出下一列分块的有效宽度", first)
    body = source[first:last]
    extra = ("    logic [REG_WIDTH:0] packed_tiles_parallel_sum;\n"
             "    logic packed_tiles_round_up;\n" if "packed_tiles_parallel_sum" in body else "")
    return f"""module {name} #(
    parameter int unsigned REG_WIDTH=32, SIZE=16
) (
    input logic [REG_WIDTH-1:0] cfg_global_reduction, n, cfg_n,
    input logic [1:0] state,
    output wire [REG_WIDTH:0] o_value
);
    localparam int LOG2_SIZE=$clog2(SIZE);
    localparam logic [1:0] IDLE=2'b00;
    logic [REG_WIDTH-1:0] packed_reduction_nxt, packed_k_tiles_nxt;
    logic unused_packed_tiles_carry;
    assign o_value={{unused_packed_tiles_carry,packed_k_tiles_nxt}};
""" + extra + body + "\nendmodule\n"


BENCH = """module tb;
    parameter integer REG_WIDTH=32, SIZE=16;
    logic [REG_WIDTH-1:0] cfg_global_reduction, n, cfg_n;
    logic [1:0] state;
    wire [REG_WIDTH:0] reference_value, current_value;
    integer checks=0, known_values=0;
    reference #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) u_reference (
        .cfg_global_reduction,.n,.cfg_n,.state,.o_value(reference_value));
    current #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) u_current (
        .cfg_global_reduction,.n,.cfg_n,.state,.o_value(current_value));
    task automatic compare;
        #1;
        if (reference_value !== current_value)
            $fatal(1,"tile count differs global=%h n=%h saved=%h state=%b ref=%h current=%h",
                   cfg_global_reduction,n,cfg_n,state,reference_value,current_value);
        checks=checks+1;
        if ((^current_value) !== 1'bx) known_values=known_values+1;
    endtask
    initial begin
        for (integer mode=0; mode<4; mode=mode+1) begin
            state=2'(mode);
            for (integer value=0; value<128; value=value+1) begin
                cfg_global_reduction=REG_WIDTH'(value);n=REG_WIDTH'(SIZE);cfg_n='1;compare();
                cfg_global_reduction=~REG_WIDTH'(value);compare();
                cfg_global_reduction='0;n=REG_WIDTH'(value);cfg_n=~REG_WIDTH'(value);compare();
            end
        end
        for (integer item=0; item<20000; item=item+1) begin
            cfg_global_reduction=REG_WIDTH'({$urandom,$urandom});
            n=REG_WIDTH'({$urandom,$urandom});
            cfg_n=REG_WIDTH'({$urandom,$urandom});
            state=2'($urandom);
            if (item%3==0) cfg_global_reduction='0;
            compare();
            case (item%6)
                0: cfg_global_reduction[$urandom_range(0,REG_WIDTH-1)]=1'bx;
                1: n[$urandom_range(0,REG_WIDTH-1)]=1'bz;
                2: cfg_n[$urandom_range(0,REG_WIDTH-1)]=1'bx;
                3: state=2'bxz;
                4: begin cfg_global_reduction='0;cfg_n=n;state=2'bzx;end
                5: begin cfg_global_reduction='x;n='z;cfg_n='x;state='x;end
            endcase
            compare();
        end
        if (known_values<1000) $fatal(1,"insufficient known-value coverage");
        $display("IA_TILE_COUNT_PASS checks=%0d known_values=%0d",checks,known_values);
        $finish;
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="18ce45a8")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_source = ROOT / SOURCE
    original = subprocess.check_output(["git", "show", args.reference_ref + ":" + SOURCE],
                                       cwd=ROOT, text=True)
    common = ROOT / "rtl/common/parallel_prefix_add.sv"
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in (current_source, common)}
    design = out / "arithmetic.sv"
    design.write_text(extract(original, "reference") + extract(current_source.read_text(), "current") + """
module miter #(parameter int unsigned REG_WIDTH=32, SIZE=16)(
    input logic [REG_WIDTH-1:0] cfg_global_reduction, n, cfg_n,
    input logic [1:0] state,
    output logic o_equal
);
    wire [REG_WIDTH:0] reference_value, current_value;
    reference #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) u_reference (
        .cfg_global_reduction,.n,.cfg_n,.state,.o_value(reference_value));
    current #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) u_current (
        .cfg_global_reduction,.n,.cfg_n,.state,.o_value(current_value));
    assign o_equal=reference_value==current_value;
endmodule
""")
    bench = out / "tb.sv"
    bench.write_text(BENCH)
    summary = dict(passed=False, inputs_constrained=False, source_sha256=hashes,
                   reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
                   arithmetic_extracted_verbatim=True, runs=[])
    for width, size in CASES:
        folder = out / f"width{width}_size{size}"
        folder.mkdir(exist_ok=True)
        script = folder / "proof.ys"
        script.write_text("\n".join([
            f"read_slang --top miter -DSYNTHESIS=1 -GREG_WIDTH={width} -GSIZE={size} {design} {common}",
            "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
            "prep -top miter -flatten",
            "sat -verify -prove o_equal 1 -show-inputs -show-outputs",
        ]) + "\n")
        log = folder / "proof.log"
        with log.open("w") as stream:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                     "--worker", str(script)], cwd=ROOT,
                                    stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode or "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(log.read_text()[-8000:])
        binary = folder / "four_state.vvp"
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-DSYNTHESIS=1", "-s", "tb",
                            f"-Ptb.REG_WIDTH={width}", f"-Ptb.SIZE={size}", "-o", str(binary),
                            str(design), str(common), str(bench)], cwd=ROOT, check=True,
                           stdout=stream, stderr=subprocess.STDOUT)
        result = subprocess.run(["vvp", str(binary)], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        (folder / "four_state.log").write_text(result.stdout)
        if result.returncode or "IA_TILE_COUNT_PASS" not in result.stdout:
            raise RuntimeError(result.stdout)
        counts = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", result.stdout)}
        record = dict(REG_WIDTH=width, SIZE=size, passed=True, formal=True, four_state=counts,
                      proof_log_sha256=sha(log))
        summary["runs"].append(record)
        print(json.dumps(record), flush=True)
    if hashes != {str(path.relative_to(ROOT)): sha(path) for path in (current_source, common)}:
        raise RuntimeError("Source changed during verification")
    summary["passed"] = True
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
