#!/usr/bin/env python3
"""对任意访问序列证明 SRAM 写入缓冲、读取转发和输出保持。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import process_tree_rss


def proof_source(width, depth, unit, ports, no_change=0):
    address_width = max(1, (depth - 1).bit_length())
    macro_depth = 128 if depth <= 384 else 1024
    low_width = 7 if macro_depth == 128 else 10
    banks = (depth + macro_depth - 1) // macro_depth
    lines = [f"""module regfile_asic_proof (
    input logic clk,
    input logic i_wr_en,
    input logic [{address_width-1}:0] i_wr_addr,
    input logic [{width-1}:0] i_wr_data,
    input logic [{width//unit-1}:0] i_wr_mask,
    input logic [{ports-1}:0] i_rd_en,
    input logic [{ports-1}:0][{address_width-1}:0] i_rd_addr,
    input logic [{address_width-1}:0] i_watch,
    input logic [15:0] i_other_data
);
    logic [{width-1}:0] reference_word;
    logic [{ports-1}:0][{width-1}:0] reference_output, actual_output;
    logic [{ports-1}:0] watched_output;
    logic [{address_width-1}:0] previous_watch;
    logic started;
    regfile #(.p_data_width({width}), .p_depth({depth}), .p_write_unit({unit}),
        .p_read_ports({ports}), .p_sync_read(1'b1), .p_no_change_collision({no_change})) dut (
        .clk(clk), .i_wr_en(i_wr_en), .i_wr_addr(i_wr_addr), .i_wr_data(i_wr_data),
        .i_wr_mask(i_wr_mask), .i_rd_en(i_rd_en), .i_rd_addr(i_rd_addr), .o_rd_data(actual_output)
    );
    // 任意固定观察地址用于表达全部逻辑存储地址的归纳关系。
    always_comb begin
        assume (i_watch < {depth});
        if (started) assume (i_watch == previous_watch);
    end
    always_ff @(posedge clk) begin
        previous_watch <= i_watch;
        started <= 1'b1;
        for (int port_index=0; port_index<{ports}; port_index++) begin
            if (i_rd_en[port_index] && !({no_change} && i_wr_en && (|i_wr_mask) &&
                i_wr_addr < {depth} && i_rd_addr[port_index] == i_wr_addr)) begin
                reference_output[port_index] <= reference_word;
                watched_output[port_index] <= i_rd_addr[port_index] == i_watch;
            end
        end
        if (i_wr_en && i_wr_addr == i_watch) begin
            for (int segment=0; segment<{width//unit}; segment++) begin
                if (i_wr_mask[segment])
                    reference_word[segment*{unit}+:{unit}] <= i_wr_data[segment*{unit}+:{unit}];
            end
        end
    end
    always_comb if (started) begin
        for (int port_index=0; port_index<{ports}; port_index++) begin
            if (watched_output[port_index]) assert (reference_output[port_index] == actual_output[port_index]);
        end
    end
"""]
    for port in range(ports):
        segment_width = width if no_change else unit
        for segment in range(width // segment_width):
            name = f"p{port}_s{segment}"
            lines.append(f"    wire [{segment_width-1}:0] {name}_bank [{banks}];")
            for bank in range(banks):
                for lane in range((segment_width + 15) // 16):
                    count = min(16, segment_width - lane * 16)
                    scope = (f"dut.g_asic_masked_storage.g_read_port[{port}]." if no_change else
                             f"dut.g_asic_storage.g_read_port[{port}].g_write_segment[{segment}].")
                    memory = (scope + f"u_storage.g_bank[{bank}].g_lane[{lane}]."
                              f"g_{macro_depth}.u_sram.u_model.watched_word")
                    lines.append(f"    assign {name}_bank[{bank}][{lane*16}+:{count}] = "
                                 f"{memory}[{count-1}:0];")
            lines.append(f"    wire [{segment_width-1}:0] {name}_physical = {name}_bank[i_watch >> {low_width}];")
            logical = f"{name}_physical"
            if not no_change:
                logical = (f"dut.g_asic_storage.pending_mask_q[{segment}] && "
                           f"dut.g_asic_storage.pending_address_q == i_watch ? "
                           f"dut.g_asic_storage.pending_data_q[{segment*unit}+:{unit}] : {name}_physical")
            lines.append(f"    wire [{segment_width-1}:0] {name}_logical = {logical};")
            lines.append(f"    always_comb if (started) assert "
                         f"(reference_word[{segment*segment_width}+:{segment_width}] == {name}_logical);")
    return "\n".join(lines) + "\nendmodule\n"


def formal_macro_model(source):
    """保留任意固定地址的每一位，其他地址的数据由自由输入提供。"""
    first = source.index("    logic [15:0] memory")
    last = source.index("\nendmodule", first)
    return source[:first] + """    logic [15:0] watched_word;
    wire [p_address_width-1:0] watched_address = p_address_width'(regfile_asic_proof.i_watch);
    always_comb if (regfile_asic_proof.started)
        assert (!(!CENA && !CENB && AA == AB && |(~WENB)));
    always @(posedge CLKA) begin
        if (!CENA) QA <= AA == watched_address ? watched_word : regfile_asic_proof.i_other_data;
    end
    always @(posedge CLKB) begin
        if (!CENB && AB == watched_address) begin
            for (int bit_index=0; bit_index<16; bit_index++) begin
                if (!WENB[bit_index]) watched_word[bit_index] <= DB[bit_index];
            end
        end
    end
""" + source[last:]


def run_limited(script, log, memory_limit=600 * 1024 * 1024, timeout=180):
    start = time.monotonic()
    peak = 0
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)]
    with log.open("w") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, cwd=ROOT)
        while process.poll() is None:
            peak = max(peak, process_tree_rss(process.pid))
            if peak > memory_limit or time.monotonic() - start > timeout:
                process.terminate()
                process.wait(timeout=10)
                raise RuntimeError("形式检查达到本次运行的资源限制")
            time.sleep(0.2)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    return {"elapsed_seconds": round(time.monotonic() - start, 2), "peak_process_tree_rss_bytes": peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", default=["16:64:16:1", "64:512:8:1", "32:256:32:1",
        "32:256:32:2", "16:384:16:1", "16:385:16:1", "16:1100:16:1",
        "19:128:19:1", "32:256:8:1", "14:128:14:1",
        "128:256:8:1:1", "64:512:8:1:1", "14:128:7:1:1",
        "32:256:8:2:1", "19:128:1:1:1", "16:130:4:1:1"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / "rtl/common/regfile.v", ROOT / "asic/rtl/smic40_sram_1r1w.sv",
             Path(__file__).with_name("sram_model.sv")]
    snapshots = []
    for path in paths:
        target = out / "inputs" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        snapshots.append(target)
    report = {"passed": False, "source_sha256": {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshots},
              "production_inputs_constrained": False,
              "properties": ["任意逻辑地址的存储内容与写入缓冲叠加关系", "全部读取端口的原有采样周期和保持行为", "物理宏无同址读写冲突"],
              "profiles": []}
    macro_model = out / "inputs/sram_formal.sv"
    macro_model.write_text(formal_macro_model(snapshots[2].read_text()))
    report["formal_macro_model_sha256"] = hashlib.sha256(macro_model.read_bytes()).hexdigest()
    for profile in args.profiles:
        values = tuple(map(int, profile.split(":")))
        if len(values) not in (4, 5):
            parser.error("配置格式为 width:depth:write_unit:read_ports[:no_change]")
        width, depth, unit, ports = values[:4]
        no_change = values[4] if len(values) == 5 else 0
        macro_depth = 128 if depth <= 384 else 1024
        segment_width = width if no_change else unit
        macro_count = ((segment_width + 15) // 16) * ((depth + macro_depth - 1) // macro_depth)
        min_bits = 1024 if macro_depth == 128 else 4096
        if depth < 32 or width % unit or depth * segment_width < ports * macro_count * min_bits:
            parser.error(f"{profile} 使用行为级存储，不适用于 SRAM 形式检查")
        folder = out / profile.replace(":", "_")
        folder.mkdir(exist_ok=True)
        source = folder / "proof.sv"
        source.write_text(proof_source(width, depth, unit, ports, no_change))
        script = folder / "run.ys"
        script.write_text("read_slang --top regfile_asic_proof -D ASIC_SRAM=1 " +
                          shlex.join(map(str, [*snapshots[:2], macro_model, source])) +
                          "\nprep -top regfile_asic_proof -flatten\nopt -full\nmemory_map\nopt -full\n"
                          "async2sync\nchformal -lower\nsat -seq 2 -tempinduct -maxsteps 4 -set-init-zero "
                          "-set-assumes -prove-asserts -verify -timeout 60\n")
        stage = run_limited(script, folder / "proof.log")
        record = {"width": width, "depth": depth, "unit": unit, "ports": ports, "no_change": no_change, "passed": True, **stage}
        report["profiles"].append(record)
        (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
