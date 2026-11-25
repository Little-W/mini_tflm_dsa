#!/usr/bin/env python3
"""检查 IA 地址和读数据恢复的 X/Z 传播、使能和保持。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from check_mapped_arithmetic import read_restore_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7ddc0d8d")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = "rtl/npu/loaders/ia_loader_cache_mgr.sv"
    original = subprocess.check_output(["git", "show", f"{args.reference}:{relative}"], cwd=ROOT, text=True)
    current = (ROOT / relative).read_text()
    design = out / "restore.sv"
    design.write_text(read_restore_source(original, "reference_restore") +
                      read_restore_source(current, "current_restore"))
    bench = out / "tb.sv"
    bench.write_text("""module tb;
    parameter integer OFFSET_WIDTH=9;
    reg clk=0, i_enable, i_compact;
    reg signed [OFFSET_WIDTH-1:0] i_offset;
    reg signed [15:0] i_data [16];
    wire signed [15:0] reference_data [16], current_data [16];
    reg [31:0] i_base, i_step;
    wire [31:0] address;
    reg [31:0] random_state=32'd20261125;
    integer cycles=0, checks=0;
    reference_restore #(.p_compact_offset_width(OFFSET_WIDTH)) u_reference(
        .clk,.i_enable,.i_compact,.i_offset,.i_data,.o_data(reference_data));
    current_restore #(.p_compact_offset_width(OFFSET_WIDTH)) u_current(
        .clk,.i_enable,.i_compact,.i_offset,.i_data,.o_data(current_data));
    ia_address_add u_address(.i_base,.i_step,.o_address(address));
    function automatic [31:0] random_word;
        begin
            random_state=random_state^(random_state<<13);
            random_state=random_state^(random_state>>17);
            random_state=random_state^(random_state<<5);
            random_word=random_state;
        end
    endfunction
    initial begin
        for (integer sample=0; sample<20000; sample=sample+1) begin
            i_enable=1'(random_word());i_compact=1'(random_word());
            i_offset=OFFSET_WIDTH'(random_word());i_base=random_word();i_step=random_word();
            for (integer lane=0; lane<16; lane=lane+1) i_data[lane]=16'(random_word());
            case (sample%8)
                0: i_offset[random_word()%OFFSET_WIDTH]=1'bx;
                1: i_data[random_word()%16][random_word()%16]=1'bz;
                2: i_compact=1'bx;
                3: i_enable=1'bz;
                4: i_base[random_word()%32]=1'bx;
                5: i_step[random_word()%32]=1'bz;
                6: begin
                    i_data[random_word()%16][random_word()%16]=1'bx;
                    i_offset[random_word()%OFFSET_WIDTH]=1'bz;
                end
                default: ;
            endcase
            #1;clk=1;#1;
            for(integer lane=0;lane<16;lane=lane+1) begin
                if(reference_data[lane] !== current_data[lane])
                    $fatal(1,"IA restore differs at sample %0d lane %0d",sample,lane);
                checks=checks+1;
            end
            if(address !== (i_base+i_step))
                $fatal(1,"IA address differs at sample %0d",sample);
            checks=checks+1;cycles=cycles+1;clk=0;
        end
        $display("PASS cycles=%0d checks=%0d",cycles,checks);$finish;
    end
endmodule
""")
    sources = [ROOT / "rtl/npu/loaders/ia_address_add.sv", ROOT / "rtl/common/parallel_prefix_add.sv"]
    summary = dict(passed=False, seed=20261125, source_sha256={
        relative: hashlib.sha256(current.encode()).hexdigest(),
        **{str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}, runs=[])
    for width in (1, 8, 9, 16):
        binary = out / f"offset{width}.vvp"
        with (out / f"offset{width}_compile.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", f"-Ptb.OFFSET_WIDTH={width}",
                            "-o", str(binary), str(bench), str(design), *map(str, sources)], cwd=ROOT,
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        output = subprocess.check_output(["vvp", str(binary)], text=True)
        (out / f"offset{width}.log").write_text(output)
        record = dict(offset_width=width, passed="PASS cycles=20000 checks=340000" in output,
                      cycles=20000, comparisons=340000)
        summary["runs"].append(record)
        summary["passed"] = all(r["passed"] for r in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not record["passed"]:
            raise RuntimeError("IA arithmetic four-state comparison did not complete")
    if summary["source_sha256"] != {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
        **{str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}:
        raise RuntimeError("RTL changed during arithmetic verification")


if __name__ == "__main__":
    main()
