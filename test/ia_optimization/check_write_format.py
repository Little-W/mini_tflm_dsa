#!/usr/bin/env python3
"""逐周期检查 IA 写数据排列的全部端口及四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/loaders/ia_loader_cache_mgr.sv"


def extract(source, name):
    first = source.index("    if (p_shared_write_stage && SIZE == 16 && DATA_WIDTH == 16) begin : g_port_write_stage")
    first = source.index("\n", first) + 1
    last = source.index("    end else begin : g_port_data_register", first)
    return f"""module {name} #(parameter integer DMA_LANES=8)(
    input logic clk,
    input logic [3:0] wr_col_base,
    input logic [15:0] wr_data [DMA_LANES],
    input logic wr_valid [DMA_LANES],
    input logic compact_active,
    input logic [7:0] compact_empty_byte,
    input logic [1:0] ram_port_wr_en,
    output logic [127:0] ram_port_wr_data [0:1],
    output logic [15:0] ram_port_wr_mask [0:1],
    output logic [127:0] ram_shared_wr_data
);
""" + source[first:last] + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7ddc0d8d")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    modules = out / "write_format.sv"
    modules.write_text(extract(reference, "reference_format") + extract(current, "current_format"))
    bench = out / "tb.sv"
    bench.write_text("""module tb;
    parameter integer DMA_LANES=8;
    reg clk=0;
    reg [3:0] wr_col_base;
    reg [15:0] wr_data [DMA_LANES];
    reg wr_valid [DMA_LANES];
    reg compact_active;
    reg [7:0] compact_empty_byte;
    reg [1:0] ram_port_wr_en;
    wire [127:0] reference_data [0:1], current_data [0:1];
    wire [15:0] reference_mask [0:1], current_mask [0:1];
    wire [127:0] reference_shared, current_shared;
    reg [31:0] random_state=32'd20261125;
    integer cycles=0, checks=0;
    reference_format #(.DMA_LANES(DMA_LANES)) u_reference(
        .clk, .wr_col_base, .wr_data, .wr_valid, .compact_active, .compact_empty_byte,
        .ram_port_wr_en, .ram_port_wr_data(reference_data), .ram_port_wr_mask(reference_mask),
        .ram_shared_wr_data(reference_shared));
    current_format #(.DMA_LANES(DMA_LANES)) u_current(
        .clk, .wr_col_base, .wr_data, .wr_valid, .compact_active, .compact_empty_byte,
        .ram_port_wr_en, .ram_port_wr_data(current_data), .ram_port_wr_mask(current_mask),
        .ram_shared_wr_data(current_shared));
    function automatic [31:0] random_word;
        begin
            random_state=random_state^(random_state<<13);
            random_state=random_state^(random_state>>17);
            random_state=random_state^(random_state<<5);
            random_word=random_state;
        end
    endfunction
    task check;
        begin
            #1; clk=1; #1;
            for (integer p=0; p<2; p=p+1) begin
                if (reference_data[p] !== current_data[p])
                    $fatal(1,"IA write data differs at cycle %0d port %0d",cycles,p);
                if (reference_mask[p] !== current_mask[p])
                    $fatal(1,"IA write mask differs at cycle %0d port %0d",cycles,p);
                checks=checks+2;
            end
            if (reference_shared !== current_shared)
                $fatal(1,"IA shared write data differs at cycle %0d",cycles);
            checks=checks+1;cycles=cycles+1;clk=0;
        end
    endtask
    initial begin
        for (integer mode=0; mode<2; mode=mode+1) begin
            for (integer column=0; column<16; column=column+1) begin
                for (integer mask=0; mask<256; mask=mask+1) begin
                    compact_active=1'(mode);wr_col_base=4'(column);
                    compact_empty_byte=8'(random_word());ram_port_wr_en=2'(mask);
                    for (integer lane=0; lane<DMA_LANES; lane=lane+1) begin
                        wr_data[lane]=16'(random_word());
                        wr_valid[lane]=1'(mask>>(lane%8));
                    end
                    check();
                end
            end
        end
        for (integer sample=0; sample<20000; sample=sample+1) begin
            compact_active=1'(random_word());wr_col_base=4'(random_word());
            compact_empty_byte=8'(random_word());ram_port_wr_en=2'(random_word());
            for (integer lane=0; lane<DMA_LANES; lane=lane+1) begin
                wr_data[lane]=16'(random_word());wr_valid[lane]=1'(random_word());
            end
            case (sample%8)
                0: wr_col_base[random_word()%4]=1'bx;
                1: wr_valid[random_word()%DMA_LANES]=1'bz;
                2: compact_empty_byte[random_word()%8]=1'bx;
                3: wr_data[random_word()%DMA_LANES][random_word()%16]=1'bz;
                4: compact_active=1'bx;
                5: ram_port_wr_en[1]=1'bx;
                6: begin
                    wr_col_base[random_word()%4]=1'bz;
                    wr_valid[random_word()%DMA_LANES]=1'bx;
                    compact_empty_byte[random_word()%8]=1'bz;
                end
                default: ;
            endcase
            check();
        end
        $display("PASS cycles=%0d checks=%0d",cycles,checks);$finish;
    end
endmodule
""")
    summary = dict(passed=False, seed=20261125,
                   source_sha256=hashlib.sha256(current.encode()).hexdigest(),
                   reference_sha256=hashlib.sha256(reference.encode()).hexdigest(), runs=[])
    for lanes in (4, 8, 16):
        binary = out / f"lanes{lanes}.vvp"
        with (out / f"lanes{lanes}_compile.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", f"-Ptb.DMA_LANES={lanes}",
                            "-o", str(binary), str(bench), str(modules)], cwd=ROOT,
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        output = subprocess.check_output(["vvp", str(binary)], text=True)
        (out / f"lanes{lanes}.log").write_text(output)
        record = dict(dma_lanes=lanes, passed="PASS cycles=28192 checks=140960" in output,
                      cycles=28192, four_state_comparisons=140960)
        summary["runs"].append(record)
        summary["passed"] = all(r["passed"] for r in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not record["passed"]:
            raise RuntimeError("IA write format comparison did not complete")


if __name__ == "__main__":
    main()
