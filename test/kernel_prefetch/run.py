#!/usr/bin/env python3
"""Verify two-slot kernel prefetch using RTL RAM and an independent DMA model."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--bus-width", type=int, choices=(32,64,128), default=64)
    parser.add_argument("--count-width", type=int, default=29)
    parser.add_argument("--reuse-build", action="store_true")
    parser.add_argument("--fpga", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    test = root / "test/kernel_prefetch"
    out = args.out.resolve()
    obj = out / "obj"
    obj.mkdir(parents=True, exist_ok=True)
    sources = [
        Path(__file__).resolve(), test / "tb.sv", test / "main.cpp",
        root / "rtl/npu/loaders/kernel_loader.sv",
        root / "rtl/npu/loaders/kernel_loader_buffer.sv",
        root / "rtl/npu/loaders/kernel_loader_ctrl.sv",
        root / "rtl/common/regfile.v",
        root / "rtl/common/add_equal.sv",
        root / "rtl/common/add3_equal.sv",
        root / "rtl/common/parallel_prefix_add.sv",
    ]
    before = {str(path.relative_to(root)): digest(path) for path in sources}
    primitive_sources = []
    primitive_library_sha256 = None
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        model = out / 'xilinx_models.sv'
        model.write_text('\n\n'.join(re.search(r'^module ' + name + r'\b.*?^endmodule',
                         library.read_text(), re.M | re.S).group(0)
                         for name in ('LUT1', 'LUT6', 'LUT6_2', 'MUXF7', 'MUXF8', 'DSP48E1')) + '\n')
        primitive_sources = ['-DSYNTHESIS', str(model)]
        primitive_library_sha256 = digest(library)
    rules = out / "compile_rules.mk"
    rules.write_text("""%.o: %.cpp
	$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<
$(VK_OBJS_FAST): %.o: %.cpp
	$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<
$(VK_OBJS_SLOW): %.o: %.cpp
	$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<
$(VK_GLOBAL_OBJS): %.o: %.cpp
	$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<
""")
    flags = f"-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_BUS_WIDTH={args.bus_width}"
    command = [
        args.verilator, "--cc", "--exe", "--build", "-j", "1", "--assert", "-Wno-fatal",
        "--top-module", "kernel_prefetch_tb", f"-GBUS_WIDTH={args.bus_width}",
        f"-GCOUNT_WIDTH={args.count_width}", "--Mdir", str(obj),
        "--output-groups", "0", "--output-split", "10000", "--output-split-cfuncs", "1000",
        "-CFLAGS", flags, "-LDFLAGS", "-fsanitize=undefined",
        "-MAKEFLAGS", f"CXX={args.compiler} OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}",
    ] + primitive_sources + [str(path) for path in sources if path.suffix in (".v", ".sv", ".cpp")]
    binary = obj / "Vkernel_prefetch_tb"
    start = time.monotonic()
    if args.reuse_build:
        previous = json.loads((out / "summary.json").read_text())
        if (not previous.get("passed") or previous["source_sha256"] != before or
                previous["parameters"]["BUS_WIDTH"] != args.bus_width or
                previous["parameters"].get("COUNT_WIDTH") != args.count_width or
                previous.get('fpga', False) != args.fpga or
                previous.get('primitive_library_sha256') != primitive_library_sha256):
            raise RuntimeError("Stored build differs from the current sources")
        if digest(binary) != previous["binary_sha256"]:
            raise RuntimeError("Stored executable differs")
        command = previous["compile_command"]
    else:
        with (out / "compile.log").open("w") as log:
            result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"RTL build failed: {out / 'compile.log'}")
    units = [line for line in (out / "compile.log").read_text().splitlines() if " -c " in line and " -o " in line]
    if not units or any("-fsanitize=undefined" not in line or "-fno-sanitize-recover=all" not in line for line in units):
        raise RuntimeError("All C++ compilation units must enable UBSan")
    result = subprocess.run([str(binary)], cwd=root, text=True, capture_output=True)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"RTL simulation failed: {(result.stdout + result.stderr).strip()}")
    report = json.loads(result.stdout.strip().splitlines()[-1])
    if not report.get("passed"):
        raise RuntimeError("RTL simulation did not report success")
    if before != {str(path.relative_to(root)): digest(path) for path in sources}:
        raise RuntimeError("Sources changed during validation")
    report.update(
        source_sha256=before, binary_sha256=digest(binary), compile_command=command,
        run_command=[str(binary)], undefined_behavior_sanitizer=True,
        sanitized_translation_units=len(units),
        fpga=args.fpga, primitive_library_sha256=primitive_library_sha256,
        parameters=dict(SIZE=16, DATA_WIDTH=16, BUS_WIDTH=args.bus_width, COUNT_WIDTH=args.count_width),
        compiler_version=subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0],
        verilator_version=subprocess.check_output([args.verilator, "--version"], text=True).strip(),
        elapsed_seconds=time.monotonic() - start,
    )
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    for path in obj.iterdir():
        if path.suffix in (".o", ".d", ".gch"):
            path.unlink()
    print(json.dumps({key: value for key, value in report.items() if key not in ("source_sha256", "compile_command", "run_command")}))


if __name__ == "__main__":
    main()
