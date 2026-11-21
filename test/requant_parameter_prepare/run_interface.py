#!/usr/bin/env python3
"""逐周期比较量化参数准备后的完整并行接口与配置竞争情况。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def make_wrapper(source):
    header = source[source.index("module vec_requant #("):source.index("\n);", source.index("module vec_requant #(")) + 3]
    header = header.replace("module vec_requant #(", "module requant_interface_top #(")
    header = header[:-3].rstrip() + ",\n    output logic [31:0] mismatch\n);\n"
    inputs = []
    outputs = []
    declarations = []
    for line in header.splitlines():
        line = line.split("//", 1)[0].strip().rstrip(",")
        match = re.match(r"(input|output)\s+(?:wire\s+)?logic\s+(signed\s+)?(\[[^]]+\]\s*)?(\w+)(\[[^]]+\])?(?:\s*=.*)?$", line)
        if not match:
            continue
        direction, signed, width, name, unpacked = match.groups()
        if name == "mismatch":
            continue
        if direction == "input":
            inputs.append(name)
        else:
            outputs.append(name)
            declarations.append("logic " + (signed or "") + (width or "") + "ref_" + name + (unpacked or "") + ";")
    if len(inputs) != 22 or len(outputs) != 19:
        raise RuntimeError(f"Unexpected interface: {len(inputs)} inputs, {len(outputs)} outputs")
    parameters = ".BUS_WIDTH(BUS_WIDTH), .VLEN(VLEN), .REG_WIDTH(REG_WIDTH), .MAX_IA_REUSE(MAX_IA_REUSE), .ENABLE_PER_CHANNEL(ENABLE_PER_CHANNEL), .ENABLE_IS_MODE(ENABLE_IS_MODE), .ENABLE_S16(ENABLE_S16), .p_compute_lanes(p_compute_lanes), .p_input_rows(p_input_rows)"
    body = header + "\n" + "\n".join(declarations) + "\n"
    body += "vec_requant #(" + parameters + ") u_current (\n" + ",\n".join("    ." + name + "(" + name + ")" for name in inputs + outputs) + "\n);\n"
    body += "vec_requant_reference #(" + parameters + ") u_reference (\n" + ",\n".join("    ." + name + "(" + ("ref_" if name in outputs else "") + name + ")" for name in inputs + outputs) + "\n);\n"
    body += "always_comb begin\n    mismatch = '0;\n"
    for bit, name in enumerate(outputs):
        if name in ("out_vec_s8", "out_vec_s16", "quant_multiplier_lane", "quant_shift_lane"):
            body += f"    for (int lane = 0; lane < VLEN; lane++) mismatch[{bit}] |= {name}[lane] !== ref_{name}[lane];\n"
        else:
            body += f"    mismatch[{bit}] = {name} !== ref_{name};\n"
    body += "end\nendmodule\n"
    return body, outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="2297cb12")
    parser.add_argument("--bus-width", type=int, nargs="+", default=[32, 64])
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--xilinx", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/npu/writeback/vec_requant.sv"
    current = source.read_text()
    old = read_rtl_source(args.reference_rev + ":rtl/npu/writeback/vec_requant.sv", cwd=ROOT, text=True)
    shared_source = ROOT / "rtl/npu/conv/vector_scalar_multiplier.sv"
    if re.search(r"\bregistered_multiplier_s32\b", old):
        old += "\n" + read_rtl_source(args.reference_rev + ":rtl/npu/conv/vector_scalar_multiplier.sv", cwd=ROOT, text=True)
    reference = out / "reference.sv"
    reference_modules = re.findall(r"^module\s+(\w+)", old, re.MULTILINE)
    reference.write_text(re.sub(r"\b(" + "|".join(map(re.escape, reference_modules)) + r")\b",
                                r"\1_reference", old))
    wrapper = out / "requant_interface_top.sv"
    wrapper_text, ports = make_wrapper(old)
    wrapper.write_text(wrapper_text)
    primitive_options = []
    if args.xilinx:
        import pyosys
        library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
        library_source = library.read_text()
        models = [re.search(r"^module " + name + r"\b.*?^endmodule", library_source,
                            re.MULTILINE | re.DOTALL).group(0) for name in ("LUT6_2", "DSP48E1", "FDRE", "CARRY4")]
        model_file = out / "xilinx_primitives.sv"
        model_file.write_text("\n".join(models) + "\n")
        primitive_options = ["-DSYNTHESIS", "-DXILINX_FPGA", str(model_file)]
    driver = out / 'interface_main.cpp'
    main_source = (ROOT / 'test/requant_pipeline/interface_main.cpp').read_text()
    main_source = main_source.replace('uint64_t cycles = 0, vectors = 0, dma_commands = 0, dma_beats = 0;',
        'uint64_t cycles = 0, vectors = 0, dma_commands = 0, dma_beats = 0;\n'
        '    uint64_t config_with_input = 0, consecutive_configs = 0, first_inputs = 0;')
    main_source = main_source.replace('dut.rst_n = 0; dut.init_cfg = 0; dut.in_valid = 0;',
        'dut.rst_n = 0; dut.init_cfg = 0; dut.in_valid = 0; dut.i_group_start = 0; dut.i_group_rows = 0;')
    main_source = main_source.replace('dut.init_cfg = 1; dut.in_valid = 0; dut.in_tile_done = 0;',
        'dut.init_cfg = 1; dut.in_valid = 1; dut.in_tile_done = 1; ++config_with_input;')
    marker = 'unsigned response_left = 0, response_delay = 0, rows = 0;'
    main_source = main_source.replace(marker, 'if (scenario % 4 == 0) {\n                for (unsigned reload = 0; reload < 3; ++reload) {\n                    dut.init_cfg = 1; dut.in_valid = 1; dut.cfg_s16 ^= 1;\n                    if (!dut.cfg_per_channel) {\n                        dut.multiplier_in = random(); dut.shift_in = shifts[(scenario + reload) % shifts.size()];\n                    }\n                    tick(); ++consecutive_configs; ++config_with_input;\n                }\n                dut.init_cfg = 0;\n            }\n            unsigned response_left = 0, response_delay = 0, rows = 0;')
    main_source = main_source.replace('dut.in_valid = dut.quant_params_valid && ((random() & 3) != 0);',
        'dut.in_valid = dut.quant_params_valid && (cycle == 0 || ((random() & 3) != 0));\n'
        '                if (cycle == 0 && dut.in_valid) ++first_inputs;')
    marker = '                if (cycle == 1023 && scenario % 13 == 0) {'
    main_source = main_source.replace(marker, '                if (cycle == 511 && scenario % 11 == 0) {\n                    dut.init_cfg = 1; dut.in_valid = 1; dut.in_tile_done = 1; dut.cfg_s16 ^= 1;\n                    dut.dma_raw_valid = 0;\n                    if (!dut.cfg_per_channel) {\n                        dut.multiplier_in = random(); dut.shift_in = shifts[(scenario + cycle) % shifts.size()];\n                    }\n                    tick(); ++config_with_input; dut.init_cfg = 0;\n                    response_left = 0; response_delay = 0;\n                }\n' + marker)
    main_source = main_source.replace('<< ",\\\"dma_beats\\\":" << dma_beats',
        '<< ",\\\"config_with_input\\\":" << config_with_input\n'
        '                  << ",\\\"consecutive_configs\\\":" << consecutive_configs\n'
        '                  << ",\\\"first_inputs\\\":" << first_inputs\n'
        '                  << ",\\\"dma_beats\\\":" << dma_beats')
    driver.write_text(main_source)
    result = {"implementation": "official Xilinx functional models" if args.xilinx else "generic", "reference_rev": args.reference_rev, "ports": ports, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "runs": []}
    result["shared_multiplier_sha256"] = hashlib.sha256(shared_source.read_bytes()).hexdigest()
    for bus in args.bus_width:
        folder = out / f"bus{bus}"
        folder.mkdir(exist_ok=True)
        command = [args.verilator, "--cc", "--exe", "--build", "-j", str(args.jobs), "-Wno-fatal",
                   "--assert", "--output-split", "20000", "--output-split-cfuncs", "100",
                   "--top-module", "requant_interface_top", "--Mdir", str(folder / "obj"),
                   f"-GBUS_WIDTH={bus}", "-GVLEN=16", "-GMAX_IA_REUSE=32", "-GENABLE_S16=1",
                   "-CFLAGS", f"-std=c++17 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_BUS_WIDTH={bus} --param=ggc-min-expand=10 --param=ggc-min-heapsize=32768",
                   "-LDFLAGS", "-fsanitize=undefined",
                   str(source), str(ROOT / "rtl/common/regfile.v"),
                   str(ROOT / "rtl/npu/writeback/requant_compute_lane.sv"),
                   str(ROOT / "rtl/npu/writeback/requant_group_buffer.sv"),
                   str(ROOT / "test/monitors/requant_group_buffer_observer.sv"),
                   str(ROOT / "rtl/common/parallel_prefix_add.sv"),
                   str(ROOT / "rtl/npu/conv/vector_scalar_multiplier.sv"), str(reference), str(wrapper),
                   *primitive_options, str(driver)]
        with (folder / "build.log").open("w") as stream:
            completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if completed.returncode:
            raise RuntimeError((folder / "build.log").read_text()[-16000:])
        completed = subprocess.run([str(folder / "obj/Vrequant_interface_top")], cwd=ROOT, capture_output=True, text=True)
        (folder / "run.log").write_text(completed.stdout + completed.stderr)
        print(completed.stdout + completed.stderr, end="", flush=True)
        if completed.returncode:
            raise RuntimeError("Interface comparison failed")
        result["runs"].append(json.loads(completed.stdout.strip().splitlines()[-1]))
        binary = folder / 'obj/Vrequant_interface_top'
        result['runs'][-1]['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
        result['test_cpp_sha256'] = hashlib.sha256(driver.read_bytes()).hexdigest()
        result['wrapper_sha256'] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
        shutil.copy2(binary, folder / binary.name)
        shutil.rmtree(folder / 'obj')
        (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
