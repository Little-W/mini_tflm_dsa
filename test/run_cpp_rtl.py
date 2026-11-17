#!/usr/bin/env python3
"""Build and execute the divider or AXI abort RTL unit with UBSan."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "conv_divider": ("conv_udiv32", "rtl/npu/conv/conv_udiv32.sv"),
    "dma_abort": ("axi_linear_block_dma", "rtl/npu/dma/axi_linear_block_dma.sv"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--reuse-build", action="store_true")
    args = parser.parse_args()
    out = (args.out or ROOT / "build" / args.target).resolve()
    out.mkdir(parents=True, exist_ok=True)
    top, rtl = TARGETS[args.target]
    sources = [Path(__file__).resolve(), ROOT / rtl, ROOT / "test" / args.target / "main.cpp"]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    rules = out / "compile_rules.mk"
    rules.write_text("""%.o: %.cpp
\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<
$(VK_OBJS_FAST): %.o: %.cpp
\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<
$(VK_OBJS_SLOW): %.o: %.cpp
\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<
$(VK_GLOBAL_OBJS): %.o: %.cpp
\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<
""")
    command = [args.verilator, "--cc", "--exe", "--build", "--assert", "-j", "1",
               "--top-module", top, "--Mdir", str(out / "obj"), "-Wno-fatal",
               "--output-groups", "0", "--output-split", "10000",
               "-CFLAGS", "-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all",
               "-LDFLAGS", "-fsanitize=undefined",
               "-MAKEFLAGS", f"-B OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}",
               str(ROOT / rtl), str(sources[-1])]
    binary = out / "obj" / ("V" + top)
    if args.reuse_build:
        old = json.loads((out / "summary.json").read_text())
        if old["source_sha256"] != hashes or old["binary_sha256"] != digest(binary) or not old["passed"]:
            raise RuntimeError("Saved executable does not match current sources")
        command = old["compile_command"]
    else:
        with (out / "compile.log").open("w") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"RTL compilation failed: {out / 'compile.log'}")
    result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr)
    report = json.loads(result.stdout.strip().splitlines()[-1])
    if not report["passed"] or any(digest(ROOT / p) != value for p, value in hashes.items()):
        raise RuntimeError("Unit validation failed or sources changed")
    units = [line for line in (out / "compile.log").read_text().splitlines() if " -c " in line and " -o " in line]
    if not units or any("-fsanitize=undefined" not in line for line in units):
        raise RuntimeError("All translation units must enable UBSan")
    report.update(target=args.target, source_sha256=hashes, binary_sha256=digest(binary),
                  compile_command=command, run_command=[str(binary)], undefined_behavior_sanitizer=True,
                  sanitized_translation_units=len(units),
                  verilator_version=subprocess.check_output([args.verilator, "--version"], text=True).strip())
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("source_sha256", "compile_command")}))


if __name__ == "__main__":
    main()
