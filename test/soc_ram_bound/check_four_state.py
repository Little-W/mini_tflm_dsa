#!/usr/bin/env python3
"""比较生产 RAM 的地址越界条件与低字节进位的完整四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/soc/soc_axi_ram.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wrapper(name, source):
    region = re.search(r"    (?:wire|logic) rd_issue_oob.*?(?=    wire rd_issue_fault)",
                       source, re.S).group(0)
    return f"""module {name} (
    input logic [32:0] rd_byte_addr_q, rd_pipe_cmd_byte_addr,
    input logic [2:0] rd_size_active_q,
    input logic [1:0] rd_burst_active_q,
    input logic rd_pipe_cmd, rd_pipe_beat,
    output logic o_bound, o_carry
);
    localparam AW=32, DW=64, DP=32768, ADDR_LSB=3, WORD_ADDR_BITS=29;
    wire [AW:0] step = 33'd1 << rd_size_active_q;
    wire [AW:0] next_address = rd_burst_active_q==2'b00 ? rd_byte_addr_q :
        (rd_byte_addr_q & ~(step-33'd1)) + step;
    wire [AW:0] selected_address = rd_pipe_cmd ? rd_pipe_cmd_byte_addr :
        (rd_pipe_beat ? next_address : rd_byte_addr_q);
    wire [WORD_ADDR_BITS:0] rd_issue_word_addr = selected_address[AW:ADDR_LSB];
{region}
    assign o_bound = rd_issue_oob;
    assign o_carry = g_read_predicted_bound.lower_carry;
endmodule
"""


BENCH = r"""`timescale 1ns/1ps
module tb;
    logic [32:0] rd_byte_addr_q, rd_pipe_cmd_byte_addr;
    logic [2:0] rd_size_active_q;
    logic [1:0] rd_burst_active_q;
    logic rd_pipe_cmd, rd_pipe_beat;
    wire current_bound, reference_bound, current_carry, reference_carry;
    integer tests=0;
    logic [31:0] rng=32'h41a9cd17;
    bound_current current_design (.*,.o_bound(current_bound),.o_carry(current_carry));
    bound_reference reference_design (.*,.o_bound(reference_bound),.o_carry(reference_carry));

    function automatic logic digit(input integer value);
        case (value & 3)
            0: digit=1'b0;
            1: digit=1'b1;
            2: digit=1'bx;
            3: digit=1'bz;
        endcase
    endfunction

    task check;
        #1;
        if (current_bound !== reference_bound || current_carry !== reference_carry)
            $fatal(1,"RAM_BOUND_FOUR_STATE_MISMATCH test=%0d",tests);
        tests++;
    endtask

    task advance_random;
        rng=rng^(rng<<13);
        rng=rng^(rng>>17);
        rng=rng^(rng<<5);
    endtask

    initial begin
        rd_byte_addr_q='1;
        rd_pipe_cmd_byte_addr='0;
        rd_burst_active_q=2'b01;
        rd_pipe_cmd=0;
        rd_pipe_beat=1;
        for (integer sample=0;sample<65536;sample++) begin
            for (integer bit_index=0;bit_index<8;bit_index++)
                rd_byte_addr_q[bit_index]=digit(sample>>(2*bit_index));
            for (integer size=0;size<8;size++) begin
                rd_size_active_q=3'(size);
                check();
            end
        end
        for (integer sample=0;sample<64;sample++) begin
            for (integer bit_index=0;bit_index<3;bit_index++)
                rd_size_active_q[bit_index]=digit(sample>>(2*bit_index));
            for (integer address=0;address<256;address++) begin
                rd_byte_addr_q[7:0]=8'(address);
                check();
            end
        end
        for (integer sample=0;sample<65536;sample++) begin
            for (integer bit_index=0;bit_index<33;bit_index++) begin
                advance_random();
                rd_byte_addr_q[bit_index]=digit(integer'(rng));
                advance_random();
                rd_pipe_cmd_byte_addr[bit_index]=digit(integer'(rng));
            end
            for (integer bit_index=0;bit_index<3;bit_index++) begin
                advance_random();
                rd_size_active_q[bit_index]=digit(integer'(rng));
            end
            advance_random();
            rd_burst_active_q={digit(integer'(rng>>2)),digit(integer'(rng))};
            rd_pipe_cmd=digit(integer'(rng>>4));
            rd_pipe_beat=digit(integer'(rng>>6));
            check();
        end
        $display("RAM_BOUND_FOUR_STATE_PASS tests=%0d",tests);
        $finish;
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="f02e539e210161e285e595ec2271b0f1067450a6")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", args.reference + ":" + str(SOURCE)],
                                        cwd=ROOT, text=True)
    for name, source in (("current", current), ("reference", reference)):
        (out / (name + ".sv")).write_text(wrapper("bound_" + name, source))
    (out / "tb.sv").write_text(BENCH)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([out / 'current.sv', out / 'reference.sv', out / 'tb.sv'], ROOT)
    source_hashes = {str(path.relative_to(ROOT)): digest(path)
                     for path in sources if path.is_relative_to(ROOT)}
    with (out / "compile.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(out / "sim.vvp"),
                        *map(str, sources)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(["vvp", str(out / "sim.vvp")], capture_output=True, text=True, timeout=180)
    (out / "run.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    assert "RAM_BOUND_FOUR_STATE_PASS tests=606208" in result.stdout
    assert current == (ROOT / SOURCE).read_text()
    assert all(digest(ROOT / name) == value for name, value in source_hashes.items())
    report = {"passed": True, "tests": 606208, "reference_commit": args.reference,
              "source_sha256": digest(ROOT / SOURCE), "run_log_sha256": digest(out / "run.log"),
              "dependency_sha256": source_hashes,
              "source_snapshot_sha256": {name: digest(out / (name + ".sv"))
                                           for name in ("current", "reference")},
              "testbench_sha256": digest(out / "tb.sv"),
              "outputs": ["address_out_of_range", "lower_byte_increment_carry"]}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
