#!/usr/bin/env python3
"""证明权重行组装的全部输入位模式及完整加载器状态。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/loaders/kernel_loader.sv")
COMMON = tuple(Path(name) for name in (
    "rtl/npu/loaders/kernel_loader_ctrl.sv",
    "rtl/npu/loaders/kernel_loader_buffer.sv",
    "rtl/common/regfile.v", "rtl/common/add_equal.sv", "rtl/common/add3_equal.sv", "rtl/common/parallel_prefix_add.sv", "rtl/common/unsigned_compare.sv"))
ARITHMETIC = ((4, 8, 8), (4, 8, 24), (4, 8, 32), (6, 16, 64),
              (16, 16, 32), (16, 16, 64), (16, 16, 128))
COMPLETE = ((4, 8, 32, 8), (16, 16, 64, 29))
HEADER = """module row_assembly #(
parameter integer SIZE=16,DATA_WIDTH=16,BUS_WIDTH=64,REG_WIDTH=32
)(
input logic cache_flush,managed_mode,transfer_discard,response_accept,ext_dma_wr_slot,
input logic [$clog2(SIZE)-1:0] ext_dma_wr_col_base,
input logic signed [DATA_WIDTH-1:0] ext_dma_wr_data[BUS_WIDTH/8],
input logic ext_dma_wr_valid[BUS_WIDTH/8],
input logic signed [DATA_WIDTH-1:0] row_acc[SIZE],
input logic [REG_WIDTH-1:0] ext_dma_valid_cols_r[2],ext_dma_logical_cols_r[2],
output logic signed [DATA_WIDTH-1:0] row_acc_n[SIZE],row_emit_n[SIZE],
output logic beat_valid,last_ext_beat
);
localparam integer BYTE_PER_BEAT=BUS_WIDTH/8;
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(source, current):
    marker = ("  // 有效传输的最后一个元素决定整行完成" if current else
              "\t  always_comb begin\n\t        beat_valid =")
    start = source.index(marker)
    end = source.index("\n\t  always_ff @(posedge clk or negedge rst_n) begin", start)
    return source[:start], source[start:end], source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="015b4187")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--parts", nargs="+", choices=("arithmetic", "complete"),
                        default=["arithmetic", "complete"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    reference_parts, current_parts = section(original, False), section(current, True)
    if reference_parts[0] != current_parts[0] or reference_parts[2] != current_parts[2]:
        raise RuntimeError("Source outside row assembly differs")
    snapshots, arithmetic = {}, {}
    for label, source, parts in (("reference", original, reference_parts), ("current", current, current_parts)):
        snapshots[label] = out / (label + "_loader.sv")
        snapshots[label].write_text(source)
        arithmetic[label] = out / (label + "_arithmetic.sv")
        arithmetic[label].write_text(HEADER + parts[1] + "\nendmodule\n")
    report = dict(reference_ref=args.reference, source_sha256=digest(ROOT / SOURCE),
                  reference_sha256=digest(snapshots["reference"]), inputs_constrained=False,
                  unchanged_outside_row_assembly=True,
                  dependency_sha256={str(path): digest(ROOT / path) for path in COMMON},
                  arithmetic=[], complete=[])

    def compare(name, top, sources, parameters, sequential=False, helpers=()):
        folder = out / name
        folder.mkdir(exist_ok=True)
        commands = []
        for label, source in sources.items():
            paths = [source, *helpers]
            commands += ["read_slang --top " + top + " " + parameters + " " +
                         " ".join(shlex.quote(str(path)) for path in paths),
                         "prep -top " + top + " -flatten"]
            if sequential:
                commands += ["memory_map", "async2sync", "opt_clean"]
            commands += ["rename " + top + " " + label, "design -stash " + label]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "opt_merge", "equiv_simple -short -seq 1", "opt_clean"]
        if sequential:
            commands += ["equiv_induct -seq 1"]
        commands += ["equiv_status -assert"]
        script, log_path = folder / "run.ys", folder / "formal.log"
        script.write_text("\n".join(commands) + "\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        log = log_path.read_text()
        if "Equivalence successfully proven" not in log:
            raise RuntimeError("Equivalence incomplete: " + name)
        matched = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log)
        return dict(case=name, passed=True, equivalent_bits=int(matched.group(1)),
                    log_sha256=digest(log_path))

    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = out / "xilinx_models.sv"
    model_text = "\n\n".join(re.search(r"^module " + name + r"\b.*?^endmodule",
        library.read_text(), re.M | re.S).group(0)
        for name in ("LUT1", "LUT6", "LUT6_2", "MUXF7", "MUXF8", "DSP48E1"))
    model.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", model_text, flags=re.S) + "\n")
    report["primitive_library_sha256"] = digest(library)
    report["primitive_model_sha256"] = digest(model)

    if "arithmetic" in args.parts:
        for fpga in (False, True):
            for size, data_width, bus_width in ARITHMETIC:
                params = f"-GSIZE={size} -GDATA_WIDTH={data_width} -GBUS_WIDTH={bus_width}"
                params += " -D SYNTHESIS -D YOSYS -D VERIFIC" if fpga else " -D ASIC_SYNTHESIS"
                label = "fpga" if fpga else "generic"
                item = compare(f"arithmetic_{label}_s{size}_d{data_width}_b{bus_width}", "row_assembly",
                               arithmetic, params, helpers=[model] if fpga else [])
                item.update(SIZE=size, DATA_WIDTH=data_width, BUS_WIDTH=bus_width, REG_WIDTH=32, fpga=fpga,
                            input_bits=5+math.ceil(math.log2(size))+(bus_width//8)*(data_width+1)+size*data_width+128)
                report["arithmetic"].append(item)
                print(json.dumps(item), flush=True)
    if "complete" in args.parts:
        for size, data_width, bus_width, count_width in COMPLETE:
            params = (f"-GSIZE={size} -GDATA_WIDTH={data_width} -GBUS_WIDTH={bus_width} -GCOUNT_WIDTH={count_width} "
                      "-D SYNTHESIS -D YOSYS -D VERIFIC")
            item = compare(f"complete_s{size}_d{data_width}_b{bus_width}", "kernel_loader", snapshots,
                           params, sequential=True, helpers=[*(ROOT / path for path in COMMON), model])
            item.update(SIZE=size, DATA_WIDTH=data_width, BUS_WIDTH=bus_width, COUNT_WIDTH=count_width, fpga=True)
            report["complete"].append(item)
            print(json.dumps(item), flush=True)
    if report["source_sha256"] != digest(ROOT / SOURCE):
        raise RuntimeError("Source changed during verification")
    for path in COMMON:
        if report["dependency_sha256"][str(path)] != digest(ROOT / path):
            raise RuntimeError("Dependency changed during verification")
    report["passed"] = True
    report["equivalent_bits"] = sum(item["equivalent_bits"] for part in args.parts for item in report[part])
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
