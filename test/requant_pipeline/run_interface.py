#!/usr/bin/env python3
"""逐周期比较量化模块的配置、参数读取、数据、有效位和尾块完成输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'monitors'))
from sources import with_observers

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
            if re.match(r'(input|output)\b', line):
                raise RuntimeError('无法解析端口声明：' + line)
            continue
        direction, signed, width, name, unpacked = match.groups()
        if name == "mismatch":
            continue
        if direction == "input":
            inputs.append(name)
        else:
            outputs.append(name)
            declarations.append("logic " + (signed or "") + (width or "") + "ref_" + name + (unpacked or "") + ";")
    if not inputs or not outputs or len(outputs) > 32:
        raise RuntimeError(f"接口数量不符合比较器容量：{len(inputs)} inputs, {len(outputs)} outputs")
    parameters = ".BUS_WIDTH(BUS_WIDTH), .VLEN(VLEN), .REG_WIDTH(REG_WIDTH), .MAX_IA_REUSE(MAX_IA_REUSE), .ENABLE_PER_CHANNEL(ENABLE_PER_CHANNEL), .ENABLE_IS_MODE(ENABLE_IS_MODE), .ENABLE_S16(ENABLE_S16)"
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
    parser.add_argument("--reference-rev", default="dde5e7c9")
    parser.add_argument("--bus-width", type=int, nargs="+", default=[32, 64])
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
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
        primitive_options = ["-DSYNTHESIS", str(model_file)]
    result = {"implementation": "Yosys Xilinx 7-series functional models" if args.xilinx else "generic", "reference_rev": args.reference_rev, "ports": ports, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "runs": []}
    result["shared_multiplier_sha256"] = hashlib.sha256(shared_source.read_bytes()).hexdigest()
    rtl_sources = with_observers([source, ROOT / 'rtl/common/regfile.v', shared_source,
        ROOT / 'rtl/npu/writeback/requant_group_buffer.sv', reference, wrapper])
    result['input_sha256'] = {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest()
                              for path in rtl_sources}
    for bus in args.bus_width:
        folder = out / f"bus{bus}"
        folder.mkdir(exist_ok=True)
        command = [args.verilator, "--cc", "--exe", "--build", "--assert", "-j", str(args.jobs), "-Wno-fatal",
                   "--top-module", "requant_interface_top", "--Mdir", str(folder / "obj"),
                   f"-GBUS_WIDTH={bus}", "-GVLEN=16", "-GMAX_IA_REUSE=32", "-GENABLE_S16=1",
                   "-CFLAGS", f"-std=c++17 -DTEST_BUS_WIDTH={bus}",
                   *map(str, rtl_sources),
                   *primitive_options, str(HERE / "interface_main.cpp")]
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
        if result['input_sha256'] != {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                      for path in rtl_sources}:
            raise RuntimeError('验证期间输入源码发生变化')
        (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
