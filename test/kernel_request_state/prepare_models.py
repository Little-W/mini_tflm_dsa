#!/usr/bin/env python3
"""展开实际加载器，导出全部寄存器状态及验证输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parents[2]
RTL = Path("rtl/npu/loaders/kernel_loader.sv")
CTRL = Path("rtl/npu/loaders/kernel_loader_ctrl.sv")
BUFFER = Path("rtl/npu/loaders/kernel_loader_buffer.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from pyosys import libyosys as ys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--size", type=int, default=16)
    parser.add_argument("--count-width", type=int, default=29)
    parser.add_argument("--bus-width", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = dict(SIZE=args.size, REG_WIDTH=32, COUNT_WIDTH=args.count_width,
                      DATA_WIDTH=16, BUS_WIDTH=args.bus_width)
    hashes, commands = {}, []
    design = ys.Design()
    for label, source in (("reference", args.reference_root), ("current", args.source_root)):
        files = []
        originals = [source / RTL, source / CTRL, source / BUFFER]
        originals.extend(sorted(path for path in (source / "rtl/common").glob("*")
                                if path.suffix in (".sv", ".v")))
        for original in originals:
            relative = original.relative_to(source)
            target = out / "inputs" / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            text = original.read_text()
            hashes[str(original)] = digest(original)
            if relative == RTL:
                marker = "    output logic                        o_admission_request\n"
                assert text.count(marker) == 1
                text = text.replace(marker, marker.rstrip() + ",\n"
                                    "    output logic formal_hold_ok,\n"
                                    "    output logic [13:0] formal_controls,\n"
                                    "    output logic [2*SIZE*DATA_WIDTH-1:0] formal_rows\n", 1)
                marker = "    .repeat_dbg            ()"
                assert text.count(marker) == 1
                text = text.replace(marker, marker + ",\n"
                                    "    .formal_pending_ok(formal_hold_ok)", 1)
                controls = ("dma_start", "cache_hit_fire", "discard_fire", "demand_dma_start",
                            "prefetch_dma_start", "prefetch_capture", "buf_send_start",
                            "ctrl_dma_start", "response_accept", "beat_valid", "last_ext_beat",
                            "buf_load_start", "dma_done", "weight_data_valid")
                observation = "\n  assign formal_controls = {" + ", ".join(controls) + "};\n"
                observation += "  for (genvar formal_column=0; formal_column<SIZE; formal_column++) begin\n"
                observation += "    assign formal_rows[formal_column*DATA_WIDTH+:DATA_WIDTH] = row_acc_n[formal_column];\n"
                observation += "    assign formal_rows[(SIZE+formal_column)*DATA_WIDTH+:DATA_WIDTH] = row_emit_n[formal_column];\n  end\n"
                text = text.replace("\nendmodule", observation + "\nendmodule", 1)
            if relative == CTRL:
                marker = "    output logic [REG_WIDTH-1:0]        repeat_dbg\n"
                assert text.count(marker) == 1
                text = text.replace(marker, marker.rstrip() + ",\n"
                                    "    output logic formal_pending_ok\n", 1)
                relation = ("1'b1" if label == "reference" else
                            "load_pending_q == ((state == S_RUN) && !all_loads_issued)")
                marker = "  logic                 all_loads_issued;"
                assert text.count(marker) == 1
                text = text.replace(marker, marker + "\n  assign formal_pending_ok = " + relation + ";", 1)
            target.write_text(text)
            files.append(target)
        options = " ".join(f"-G{name}={value}" for name, value in parameters.items())
        steps = ["read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 " + options +
                 " --top kernel_loader " + shlex.join(map(str, files)),
                 "prep -top kernel_loader -flatten", "memory_map", "opt_clean",
                 f"rename kernel_loader {label}",
                 "write_json " + shlex.quote(str(out / (label + ".json"))), "design -reset"]
        for command in steps:
            commands.append(command)
            ys.run_pass(command, design)
    if hashes != {name: digest(Path(name)) for name in hashes}:
        raise RuntimeError("模型展开期间源文件发生变化")
    report = dict(parameters=parameters, source_sha256=hashes, commands=commands,
                  current_controller_sha256=digest(args.source_root / CTRL))
    (out / "config.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
