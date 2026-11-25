#!/usr/bin/env python3
"""在生产参数下逐周期比较完整 IA 控制模块的全部公开输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/loaders/ia_loader_ctrl.sv")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_loop(name: str, dimensions: str, body: str) -> str:
    dimensions = re.findall(r"\[([^\]]+)\]", dimensions)
    if not dimensions:
        return "    " + body.format(value=name) + "\n"
    assert len(dimensions) == 1
    if ":" in dimensions[0]:
        low, high = dimensions[0].split(":")
        begin, end = low, f"({high})+1"
    else:
        begin, end = "0", dimensions[0]
    return (f"    for(int lane={begin};lane<{end};lane++) "
            + body.format(value=name + "[lane]") + "\n")


def simulation_sources(out: Path, ports: list) -> dict:
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    hashes = {}
    for label in ("reference", "current"):
        base = out / "inputs" / label
        files = resolve([base / SOURCE], base)
        blocks = []
        hashes[label] = {str(path.relative_to(base)): digest(path) for path in files}
        for path in files:
            text = path.read_text()
            if path.name == SOURCE.name:
                begin = text.index(") (") + 3
                end = text.index("\n);", begin)
                declarations = [f"    {direction} {kind} {name} {dimensions}"
                                for direction, kind, name, dimensions in ports]
                text = text[:begin] + "\n" + ",\n".join(declarations) + text[end:]
            # 常量数组逐项连接，每次调用完整赋值的局部整数使用静态声明。
            text = re.sub(r"\bautomatic int col;(?=\s+col\s*=)", "int col;", text)
            text = text.replace(
                "assign cache_slot_rows = '{default:'0};",
                "for (genvar zero_slot=0;zero_slot<SLOT_BLOCKS;zero_slot++) "
                "begin : g_zero_slot_rows assign cache_slot_rows[zero_slot]='0; end",
            )
            text = text.replace(
                "assign cache_row_value = '{default:'0};",
                "for (genvar zero_port=0;zero_port<3;zero_port++) "
                "begin : g_zero_row_values assign cache_row_value[zero_port]='0; end",
            )
            blocks.append(text)
        combined = "\n".join(blocks)
        if label == "reference":
            names = set(re.findall(r"\b(?:module|package)\s+(\w+)\b", combined))
            pattern = r"\b(?:" + "|".join(sorted(names, key=len, reverse=True)) + r")\b"
            combined = re.sub(pattern, lambda match: "ref__" + match[0], combined)
        (out / (label + ".sv")).write_text(combined)
    return hashes


def testbench(ports: list, parameters: dict) -> str:
    lines = ["`timescale 1ns/1ps\nmodule tb;\n"]
    lines += [f"localparam integer {name}={value};\n"
              for name, value in parameters.items()]
    lines += ["localparam integer SLOT_BLOCKS=COMPACT_S8?64:32;\n"]
    for direction, kind, name, dimensions in ports:
        kind = re.sub(r"\bwire\s+", "", kind)
        if direction == "input":
            lines.append(f"{kind} {name} {dimensions};\n")
        else:
            kind = kind.replace("logic", "wire", 1)
            lines.append(f"{kind} {name} {dimensions},ref_{name} {dimensions};\n")
    for module, instance, prefix in (
        ("ia_loader_ctrl", "dut", ""),
        ("ref__ia_loader_ctrl", "reference_dut", "ref_"),
    ):
        parameter_list = ",\n".join(f".{name}({name})" for name in parameters)
        connection_list = ",\n".join(
            f".{name}({prefix + name if direction == 'output' else name})"
            for direction, _, name, _ in ports
        )
        lines.append(f"{module} #(\n{parameter_list}\n) {instance} (\n{connection_list}\n);\n")
    lines += [
        "integer cycles=0,valid_cycles=0;logic[4:0]states_seen=0;\n",
        "task compare_outputs;\n",
    ]
    for direction, _, name, dimensions in ports:
        if direction == "output":
            reference = "ref_" + name + ("[lane]" if dimensions else "")
            body = ("if ({value} !== " + reference + ') $fatal(1,"control output '
                    + name + ' differs cycle=%0d",cycles);')
            lines.append(array_loop(name, dimensions, body))
    lines += [
        "endtask\n",
        "task tick;#2;compare_outputs();clk=1;#2;compare_outputs();\n",
        "if(ia_data_valid===1'b1)valid_cycles++;\n",
        "if(dut.state<5)states_seen[dut.state]=1;cycles++;clk=0;#1;endtask\n",
        "initial begin\n",
    ]
    for direction, _, name, dimensions in ports:
        if direction == "input":
            lines.append(array_loop(name, dimensions, "{value}='0;"))
    lines += [
        "repeat(4)tick();\nfor(integer sample=0;sample<20000;sample++)begin\n",
        "rst_n=sample%127!=0;\n",
    ]
    for direction, _, name, dimensions in ports:
        if direction == "input" and name not in ("clk", "rst_n"):
            lines.append(array_loop(name, dimensions, "{value}=$urandom;"))
    overrides = dict(
        cfg_k=16, cfg_n=16, cfg_cache_blocks=32, cfg_slot_mask="SLOT_BLOCKS-1",
        cfg_valid=1, cfg_ia_reuse_num=1, cfg_w_reuse_num=1,
        horizontal_tile_num=1, vertical_tile_num=1, l2_group_num=1, l1_per_l2=1,
        ia_reuse_num_act=1, w_groups_total=1, w_group_last_width=1,
        output_col_tile_num=1, rsp_beats_per_row_normal=2,
        rsp_beats_per_row_last=2, rsp_rows_last_tile=16,
        init_start="sample%43==0", load_ia_granted=1,
    )
    present = {name for direction, _, name, _ in ports if direction == "input"}
    for name, value in overrides.items():
        if name in present:
            lines.append(f"{name}={value};\n")
    selected = [(name, dimensions) for direction, _, name, dimensions in ports
                if direction == "input" and name != "clk"]
    lines.append(f"if(sample>=3000)begin case(sample%{2*len(selected)+1})\n")
    for index, (name, dimensions) in enumerate(selected):
        for parity, value in enumerate(("x", "z")):
            lines.append(f"{2*index+parity}:begin\n"
                         + array_loop(name, dimensions, "{value}='" + value + ";")
                         + "end\n")
    lines += [
        "default:;endcase end\ntick();end\n",
        "if(states_seen!==5'b11111 || valid_cycles<10)\n",
        '$fatal(1,"insufficient control activity states=%b valid=%0d",'
        "states_seen,valid_cycles);\n",
        '$display("CONTROL_FOUR_STATE_PASS cycles=%0d valid=%0d states=%b",'
        "cycles,valid_cycles,states_seen);$finish;end\nendmodule\n",
    ]
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="45c6caec")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(ROOT / "test/ia_step_product/prepare_measurement.py"),
         "--reference", args.reference, "--out", str(out / "inputs")], check=True,
    )
    input_hashes = json.loads((out / "inputs/source_sha256.json").read_text())
    parse_ports = runpy.run_path(str(ROOT / "test/ia_timing/run_interface.py"))["port_declarations"]
    ports = {}
    for label in ("reference", "current"):
        source = (out / "inputs" / label / SOURCE).read_text()
        ports[label] = parse_ports(re.sub(r"\(\*.*?\*\)", "", source, flags=re.S))
    assert ports["reference"] == ports["current"]
    ports = ports["current"]
    sources = simulation_sources(out, ports)
    records = []
    for compact in (0, 1):
        folder = out / f"compact{compact}"
        folder.mkdir(exist_ok=True)
        parameters = dict(
            SIZE=16, DATA_WIDTH=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=29,
            CACHE_BLOCKS=32, COMPACT_S8=compact, PS_FRAME_COUNT=16,
            p_indexed_slot_rows=1, p_precomputed_slot_mask=1,
            p_precomputed_frame_rows=1, p_precomputed_packed_tiles=1,
            p_parallel_request_match=1,
        )
        (folder / "tb.sv").write_text(testbench(ports, parameters))
        command = [
            "iverilog", "-g2012", "-DSYNTHESIS=1", "-DXILINX_FPGA=1", "-s", "tb",
            "-o", str(folder / "sim.vvp"), str(out / "reference.sv"),
            str(out / "current.sv"), str(folder / "tb.sv"),
        ]
        with (folder / "compile.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        run = subprocess.run(
            ["vvp", str(folder / "sim.vvp")], capture_output=True,
            text=True, timeout=180,
        )
        (folder / "run.log").write_text(run.stdout + run.stderr)
        print(run.stdout, end="", flush=True)
        run.check_returncode()
        match = re.search(
            r"CONTROL_FOUR_STATE_PASS cycles=(\d+) valid=(\d+) states=([01]+)",
            run.stdout,
        )
        assert match and int(match[1]) == 20004 and match[3] == "11111"
        records.append(dict(
            passed=True, parameters=parameters, cycles=int(match[1]),
            valid_cycles=int(match[2]), states_seen=match[3],
            outputs=sum(direction == "output" for direction, *_ in ports),
            compile_command=command, testbench_sha256=digest(folder / "tb.sv"),
            run_log_sha256=digest(folder / "run.log"),
        ))
    assert digest(ROOT / SOURCE) == input_hashes["sources"]["current"][str(SOURCE)]
    summary = dict(
        passed=True, reference_commit=input_hashes["reference_commit"],
        profiles=records, compare_before_and_after_edge=True,
        source_sha256=sources,
        simulation_source_sha256={label: digest(out / (label + ".sv"))
                                  for label in ("reference", "current")},
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
