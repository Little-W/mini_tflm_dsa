#!/usr/bin/env python3
"""Exercise task-partitioned IA/PS RAM and the external-memory frame store."""
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
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--bank-bytes", type=int, choices=(1024,2048,4096), default=2048)
    parser.add_argument("--bank-count", type=int, choices=range(6,10), default=7)
    parser.add_argument("--force-raw", action="store_true")
    parser.add_argument("--reuse-build", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    test = Path(__file__).resolve().parent
    codec_test = root / "test/ps_compression"
    out = args.out.resolve()
    obj = out / "obj"
    obj.mkdir(parents=True, exist_ok=True)
    top = "shared_storage_tb"
    sources = [Path(__file__).resolve(), test / "shared_storage_tb.sv", test / "shared_storage_test.cpp",
               codec_test / "stream_test_vectors.hpp", codec_test / "cpp_adaptive_codec.hpp", codec_test / "cpp_row_codec.hpp",
               root / "rtl/npu/buffers/ia_ps_shared_ram.sv", root / "rtl/npu/gempact/ps_frame_store.sv",
               root / "rtl/npu/gempact/ps_adaptive_codec.sv"]
    before = {str(path.relative_to(root)): digest(path) for path in sources}
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
              "-fsanitize=undefined -fno-sanitize-recover=all -I" + str(codec_test))
    cflags += f" -DTEST_BANK_BYTES={args.bank_bytes} -DTEST_BANK_COUNT={args.bank_count}"
    if args.force_raw:
        cflags += " -DFORCE_RAW=1"
    command = [args.verilator, "--cc", "--exe", "--build", "-j", "1", "--assert", "-Wno-fatal",
               "--top-module", top, f"-GBANK_BYTES={args.bank_bytes}", f"-GBANK_COUNT={args.bank_count}", "--Mdir", str(obj), "--output-groups", "0", "--output-split", "10000",
               "--output-split-cfuncs", "1000", "-CFLAGS", cflags, "-LDFLAGS", "-fsanitize=undefined",
               "-MAKEFLAGS", f"CXX={args.compiler} OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}"]
    if args.force_raw:
        command.append("+define+GEMMORA_PS_FORCE_RAW")
    command.extend(str(path) for path in sources if path.suffix in (".sv", ".cpp"))
    binary = obj / ("V" + top)
    started = time.monotonic()
    if not args.reuse_build:
        with (out / "compile.log").open("w") as log:
            result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"RTL compilation failed; see {out / 'compile.log'}")
    else:
        prior = json.loads((out / "summary.json").read_text())
        if not prior.get("passed") or prior.get("source_sha256") != before:
            raise RuntimeError("Saved build differs from current sources")
        if (prior.get("force_raw") != args.force_raw or prior.get("binary_sha256") != digest(binary) or
                prior["parameters"]["BANK_BYTES"] != args.bank_bytes or
                prior["parameters"]["BANK_COUNT"] != args.bank_count):
            raise RuntimeError("Saved binary or mode differs")
        command = prior["compile_command"]
    translation_units = [line for line in (out / "compile.log").read_text().splitlines()
                         if " -c " in line and " -o " in line]
    if not translation_units or any("-fsanitize=undefined" not in line or "-fno-sanitize-recover=all" not in line
                                    for line in translation_units):
        raise RuntimeError("Every compiled C++ translation unit must enable UBSan")
    result = subprocess.run([str(binary)], cwd=root, text=True, capture_output=True)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"RTL test failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if not payload.get("passed"):
        raise RuntimeError("RTL test did not report success")
    if before != {str(path.relative_to(root)): digest(path) for path in sources}:
        raise RuntimeError("Sources changed during validation")
    payload.update(force_raw=args.force_raw, source_sha256=before, binary_sha256=digest(binary),
                   compile_command=command, run_command=[str(binary)], undefined_behavior_sanitizer=True,
                   sanitized_translation_units=len(translation_units), elapsed_seconds=time.monotonic()-started,
                   parameters=dict(TOTAL_BYTES=args.bank_bytes*args.bank_count, BANK_BYTES=args.bank_bytes,
                                   BANK_COUNT=args.bank_count, EXTERNAL_RAM=1,
                                   MAX_FRAME_ROWS=args.bank_bytes//8, FRAME_COUNT=16, DIRECTORY_ROWS=1024,
                                   PS_POOL_MAX_BYTES=args.bank_bytes*(args.bank_count-1), DECODE_FIFO_ROWS=8),
                   compiler_version=subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0],
                   verilator_version=subprocess.check_output([args.verilator, "--version"], text=True).strip())
    (out / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    for path in obj.iterdir():
        if path.suffix in (".o", ".d", ".gch"):
            path.unlink()
    print(json.dumps({key: value for key, value in payload.items()
                      if key not in ("source_sha256", "compile_command", "run_command")}))


if __name__ == "__main__":
    main()
