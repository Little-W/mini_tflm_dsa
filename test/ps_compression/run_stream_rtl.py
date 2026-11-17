#!/usr/bin/env python3
"""Compile and run the pipelined partial-sum codec RTL checks."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("codec",), default="codec")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--force-raw", action="store_true")
    parser.add_argument("--reuse-build", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    test = repo / "test/ps_compression"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    obj = out / "obj"
    obj.mkdir(exist_ok=True)
    top = "stream_" + args.target + "_tb"
    sources = [Path(__file__).resolve(), test / (top + ".sv"),
               test / ("stream_" + args.target + "_test.cpp"),
               test / "stream_test_vectors.hpp", test / "cpp_adaptive_codec.hpp",
               test / "cpp_row_codec.hpp", repo / "rtl/npu/gempact/ps_adaptive_codec.sv"]
    before = {str(path.relative_to(repo)): digest(path) for path in sources}
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
    cflags = ("-std=c++20 -O1 "
              "-fsanitize=undefined -fno-sanitize-recover=all -I" + str(test))
    if args.force_raw:
        cflags += " -DFORCE_RAW=1"
    command = [args.verilator, "--cc", "--exe", "--build", "-j", "1", "--assert",
               "-Wno-fatal", "--top-module", top, "--Mdir", str(obj),
               "--output-groups", "0", "--output-split", "10000", "--output-split-cfuncs", "1000",
               "-CFLAGS", cflags, "-LDFLAGS", "-fsanitize=undefined",
               "-MAKEFLAGS", f"CXX={args.compiler} OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}"]
    if args.force_raw:
        command.append("+define+GEMMORA_PS_FORCE_RAW")
    command.extend(str(path) for path in sources if path.suffix in (".sv", ".cpp"))
    binary = obj / ("V" + top)
    started = time.monotonic()
    if not args.reuse_build:
        with (out / "compile.log").open("w") as log:
            result = subprocess.run(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"RTL build failed; see {out / 'compile.log'}")
    else:
        prior = json.loads((out / "summary.json").read_text())
        if not prior.get("passed") or prior.get("source_sha256") != before:
            raise RuntimeError("Stored build does not match the current sources")
        if prior.get("force_raw") != args.force_raw or prior.get("binary_sha256") != digest(binary):
            raise RuntimeError("Stored build configuration or executable differs")
        command = prior["compile_command"]
    translation_units = [line for line in (out / "compile.log").read_text().splitlines()
                         if " -c " in line and " -o " in line]
    if not translation_units or any("-fsanitize=undefined" not in line or
                                    "-fno-sanitize-recover=all" not in line for line in translation_units):
        raise RuntimeError("Every compiled translation unit must enable UBSan")
    result = subprocess.run([str(binary)], cwd=repo, text=True, capture_output=True)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"RTL test failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if not payload.get("passed"):
        raise RuntimeError("RTL test did not report success")
    after = {str(path.relative_to(repo)): digest(path) for path in sources}
    if before != after:
        raise RuntimeError("Source files changed during validation")
    payload.update(target=args.target, force_raw=args.force_raw, source_sha256=before,
                   binary_sha256=digest(binary), compile_command=command, run_command=[str(binary)],
                   undefined_behavior_sanitizer=True,
                   sanitized_translation_units=len(translation_units),
                   compiler_version=subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0],
                   verilator_version=subprocess.check_output([args.verilator, "--version"], text=True).strip(),
                   elapsed_seconds=time.monotonic()-started)
    (out / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    for path in obj.iterdir():
        if path.suffix in (".o", ".d", ".gch"):
            path.unlink()
    print(json.dumps({key: value for key, value in payload.items()
                      if key not in ("source_sha256", "compile_command", "run_command")}))


if __name__ == "__main__":
    main()
