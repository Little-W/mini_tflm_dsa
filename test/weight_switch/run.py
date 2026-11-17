#!/usr/bin/env python3
"""Verify complete NPU output and measure row-pipelined weight switching."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SIZE = 16


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_npu(root: Path):
    specification = importlib.util.spec_from_file_location(
        "weight_switch_npu", root / "test/conv_npu/run.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def regenerate_reference(npu, directory, *, bias, per_channel, input_offset=0):
    path = directory / "config.mem"
    cfg = [int(word, 16) for word in path.read_text().split()]
    image = npu.load_sparse(directory / "init.mem")
    cfg[16] = cfg[16] if bias else 0
    cfg[21] = input_offset & 0xffffffff
    if not per_channel:
        cfg[13] = 0
        cfg[24] = 0x40000000
        cfg[25] = (-12 if cfg[28] else (-21 if cfg[12] else -10)) & 0xffffffff
    accumulators = npu.gemm_accumulators(cfg, image)
    expected = bytearray(image)
    for index, accumulator in enumerate(accumulators):
        column = index % cfg[5]
        if cfg[13]:
            multiplier = int.from_bytes(image[cfg[24]+column*4:cfg[24]+column*4+4],
                                        "little", signed=True)
            shift = int.from_bytes(image[cfg[25]+column*4:cfg[25]+column*4+4],
                                   "little", signed=True)
        else:
            multiplier, shift = npu.signed32(cfg[24]), npu.signed32(cfg[25])
        scaled = (npu.nmsis_nn_requantize_s64(accumulator, multiplier, shift) if cfg[28]
                  else npu.cmsis_nn_requantize(accumulator, multiplier, shift))
        value = max(npu.signed32(cfg[26]), min(npu.signed32(cfg[27]),
                    scaled + npu.signed32(cfg[23])))
        width = 2 if cfg[28] else 1
        address = cfg[17] + (index // cfg[5]) * cfg[20] + column * width
        expected[address:address+width] = value.to_bytes(width, "little", signed=True)
    npu.accumulator_mem(directory / "acc.mem", accumulators)
    npu.sparse_mem(directory / "golden.mem", expected)
    path.write_text("".join(f"{word:08x}\n" for word in cfg))
    return cfg, accumulators


def pack_operand(npu, directory, operand):
    path = directory / "config.mem"
    cfg = [int(word, 16) for word in path.read_text().split()]
    lhs = operand == "lhs"
    base, rows = (cfg[14], cfg[3]) if lhs else (cfg[15], cfg[5])
    stride, width = (cfg[18], 2 if cfg[12] else 1) if lhs else (cfg[19], 1)
    reduction_tiles = (cfg[4] + SIZE - 1) // SIZE
    packed = bytearray([0x5a] * (((rows+SIZE-1)//SIZE) * reduction_tiles * SIZE*SIZE*width))
    image = npu.load_sparse(directory / "init.mem")
    for row in range(rows):
        for red in range(cfg[4]):
            source = base + row*stride + red*width
            target = (((row//SIZE)*reduction_tiles + red//SIZE)*SIZE*SIZE +
                      (row % SIZE)*SIZE + red % SIZE)*width
            packed[target:target+width] = image[source:source+width]
    for name in ("init.mem", "golden.mem"):
        image = npu.load_sparse(directory / name)
        image[base:base+len(packed)] = packed
        npu.sparse_mem(directory / name, image)
    cfg[29] |= 1 if lhs else 2
    path.write_text("".join(f"{word:08x}\n" for word in cfg))


def generate(npu, out, profile, selected):
    out.mkdir(parents=True, exist_ok=True)
    maximum_r = 4 * profile["shared_bank_bytes"] // 512
    output_banks = max(32, maximum_r)
    specs = [
        dict(name="stalled_short17", rows=17, red=16, cols=519, r=2, w=4, stress=True),
        dict(name="stalled_short33", rows=33, red=16, cols=519, r=4, w=4, stress=True),
        dict(name="one_row", rows=1, red=16, cols=128, r=1, w=4),
        dict(name="short_tail", rows=5, red=13, cols=83, r=1, w=3),
        dict(name="continuous_tiles", rows=16, red=16, cols=128, r=1, w=8),
        dict(name="row_tail", rows=21, red=16, cols=83, r=1, w=3),
        dict(name="unequal_groups", rows=37, red=16, cols=67, r=2, w=4),
        dict(name="packed_groups", rows=65, red=16, cols=131, r=4, w=8, packed=True),
        dict(name="capacity_rows", rows=SIZE*maximum_r+5, red=16, cols=67,
             r=maximum_r, w=4, banks=4),
        dict(name="coalesced_capacity", rows=257, red=16, cols=2*output_banks,
             r=16, w=output_banks//16, banks=4),
        dict(name="coalesced_below_capacity", rows=129, red=16, cols=64,
             r=8, w=2, banks=2),
        dict(name="bias", rows=37, red=16, cols=67, r=2, w=4, bias=True),
        dict(name="per_channel", rows=37, red=16, cols=67, r=2, w=4, per_channel=True),
        dict(name="bias_per_channel", rows=21, red=13, cols=83, r=1, w=3,
             bias=True, per_channel=True),
        dict(name="is_tail", rows=67, red=16, cols=37, r=2, w=4, mode=1,
             bias=True, per_channel=True),
        dict(name="wide_input", rows=37, red=16, cols=67, r=2, w=4, wide=True, banks=2),
        dict(name="wide_output", rows=37, red=16, cols=67, r=2, w=4,
             wide=True, out16=True, banks=2),
        dict(name="cross_k_ws", rows=69, red=35, cols=53, r=4, w=2,
             bias=True, per_channel=True),
        dict(name="cross_k_is", rows=53, red=35, cols=69, r=4, w=2, mode=1,
             bias=True, per_channel=True),
        dict(name="cross_k_short", rows=1, red=53, cols=67, r=1, w=4),
        dict(name="frame_single_k", rows=69, red=13, cols=83, r=4, w=5,
             frame=True, banks=2),
        dict(name="frame_multi_k", rows=81, red=35, cols=83, r=8, w=5,
             frame=True, banks=2, bias=True, per_channel=True, packed=True),
    ]
    if maximum_r >= 64:
        specs.append(dict(name="large_r32", rows=517, red=16, cols=64,
                          r=32, w=2, banks=2))
    if selected:
        unknown = set(selected) - {item["name"] for item in specs}
        if unknown:
            raise ValueError(f"Unknown cases: {sorted(unknown)}")
        specs = [item for item in specs if item["name"] in selected]
    cases = []
    for spec in specs:
        for raw in (True, False):
            name = spec["name"] + ("_raw" if raw else "_adaptive")
            directory = npu.precision_task(out, SIZE, name=name,
                rows=spec["rows"], columns=spec["cols"], reduction=spec["red"],
                dataflow=spec.get("mode", 0), lhs_s16=spec.get("wide", False),
                output_s16=spec.get("out16", False),
                memory_bases=(0x1003, 0x20003, 0x40000, 0x58003, 0x48000, 0x50000))
            cfg, accumulators = regenerate_reference(npu, directory,
                bias=spec.get("bias", False), per_channel=spec.get("per_channel", False),
                input_offset=7 if spec["name"] == "short_tail" else 0)
            r, w = spec["r"], spec["w"]
            stream_rows, stream_cols = (cfg[5], cfg[3]) if cfg[8] else (cfg[3], cfg[5])
            row_tiles, col_tiles = (stream_rows+15)//16, (stream_cols+15)//16
            cfg[6], cfg[7] = r, w
            cfg[30] = ((row_tiles+r-1)//r) | (((col_tiles+w-1)//w) << 16)
            cfg[31] = ((row_tiles-1) % r+1) | (((col_tiles-1) % w+1) << 16)
            cfg[61] = int(raw) | (6 if spec.get("frame") else 0)
            cfg[62] = spec.get("banks", 1)
            cfg[63] = int(spec.get("stress", False))
            (directory / "config.mem").write_text("".join(f"{word:08x}\n" for word in cfg))
            if spec.get("packed"):
                pack_operand(npu, directory, "lhs")
                pack_operand(npu, directory, "rhs")
            metadata = dict(name=name, shape=dict(m=cfg[3], k=cfg[4], n=cfg[5]),
                case=spec, force_raw=raw, ps_control=cfg[61], ia_banks=cfg[62],
                reference="direct integer matrix product, int32 wrap, and NMSIS integer requantization",
                int32_values=len(accumulators), acc_min=min(accumulators), acc_max=max(accumulators),
                memory_sha256={name: digest(directory / name) for name in
                    ("config.mem", "init.mem", "golden.mem", "required.mem", "acc.mem")})
            write_json(directory / "case.json", metadata)
            cases.append(directory)
    return cases


def memory_with_write_stalls(original, destination):
    source = original.read_text()
    declaration = """    logic [8:0] weight_switch_write_cycle;
    always @(posedge clk) begin
        if (!rst_n || new_job) weight_switch_write_cycle <= 0;
        else weight_switch_write_cycle <= weight_switch_write_cycle + 1'b1;
    end
    wire weight_switch_write_permitted = !tb_conv_npu.saved_cfg[63][0] ||
                                        weight_switch_write_cycle >= 9'd480;
"""
    marker = '    initial random_wait = !$test$plusargs("NO_RANDOM_WAIT");'
    if source.count(marker) != 1:
        raise ValueError("The AXI memory declaration differs from the supported test interface")
    source = source.replace(marker, declaration + marker)
    for signal, ready in (("awready", "!wr_active && !bvalid"), ("wready", "wr_active")):
        old = f"assign {signal}=rst_n && {ready} &&"
        if source.count(old) != 1:
            raise ValueError(f"The AXI memory {signal} handshake differs from the supported interface")
        source = source.replace(old, f"assign {signal}=rst_n && {ready} && weight_switch_write_permitted &&")
    destination.write_text(source)


def build(npu, root, out, profile, verilator, jobs, lint_only):
    sources, includes, tracked = npu.source_files()
    observer = HERE / "observer.sv"
    out.mkdir(parents=True, exist_ok=True)
    memory = out / "axi_memory_with_write_stalls.sv"
    original_memory = root / "test/conv_npu/axi_memory.sv"
    memory_with_write_stalls(original_memory, memory)
    sources = [memory if source == original_memory else source for source in sources]
    sources.append(observer)
    rules = out / "compile_rules.mk"
    rules.write_text("%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n"
        "$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n"
        "$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n"
        "$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n")
    wave = "row_weight_select" in (root / "rtl/npu/compute/ws_systolic_array.sv").read_text()
    definitions = ["-DTB_SIZE=16", "-DGEMPACT_PS_COMPRESS=1",
        f"-DGEMMORA_PS_POOL_BYTES={profile['pool_bytes']}",
        f"-DTB_BUS_WIDTH={profile['bus_width']}",
        f"-DTB_SHARED_BANK_BYTES={profile['shared_bank_bytes']}",
        f"-DTB_SHARED_BANK_COUNT={profile['shared_bank_count']}",
        "-DTB_CONV_CACHE_SETS=128", "-DTB_CONV_CACHE_POLICY=2"]
    if wave:
        definitions.append("-DTB_WEIGHT_SELECT_WAVE=1")
    command = [verilator, "--lint-only" if lint_only else "--binary", "--timing", "--assert", "-sv",
        "--top-module", "tb_conv_npu", "-Wno-fatal", "--output-groups", "0",
        "--output-split", "10000", "--output-split-cfuncs", "1000",
        *[f"-I{path}" for path in includes], *definitions, "--Mdir", out/"obj", "-j", str(jobs),
        "-CFLAGS", "-std=c++20 -O1 --param ggc-min-expand=1 --param ggc-min-heapsize=1024",
        "-MAKEFLAGS", f"OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}", *sources]
    before = {str(path.relative_to(root)): digest(path) for path in tracked}
    test_hashes = {str(path.relative_to(HERE)): digest(path) for path in (Path(__file__), observer)}
    rc = npu.command(command, out / "compile.log", cwd=root, timeout=1200)
    after = {str(path.relative_to(root)): digest(path) for path in tracked}
    manifest = dict(profile=profile, returncode=rc, weight_select_wave=wave, lint_only=lint_only,
        command=list(map(str, command)), rtl_root=str(root), source_sha256=before,
        test_source_sha256=test_hashes, sources_unchanged_during_build=before == after,
        derived_source_sha256={memory.name: digest(memory)},
        size=SIZE, bus_width=profile["bus_width"], ps_compress=True, force_raw=False,
        pool_bytes=profile["pool_bytes"], shared_bank_bytes=profile["shared_bank_bytes"],
        shared_bank_count=profile["shared_bank_count"], cache_sets=128,
        cache_ways=2, cache_line_bytes=16, cache_policy=2)
    if (root / "source_commit.json").exists():
        identity = json.loads((root / "source_commit.json").read_text())
        manifest["source_identity"] = {name: identity[name] for name in ("commit", "tree")}
    else:
        manifest["source_identity"] = dict(working_tree=True, parent_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip())
    if rc == 0 and not lint_only:
        manifest["binary_sha256"] = digest(out / "obj/Vtb_conv_npu")
    write_json(out / "build.json", manifest)
    if rc or before != after:
        raise RuntimeError(f"Simulator compilation failed or a source changed: {out / 'compile.log'}")
    return manifest


def validate_sim(root, out, profile):
    manifest = json.loads((out / "build.json").read_text())
    if manifest["returncode"] or manifest["profile"] != profile or manifest["lint_only"]:
        raise ValueError("Simulator build and requested hardware differ")
    for name, expected in manifest["source_sha256"].items():
        if digest(root / name) != expected:
            raise ValueError(f"Simulator source changed: {name}")
    for name, expected in manifest["test_source_sha256"].items():
        if Path(name).suffix in (".sv", ".svh") and digest(HERE / name) != expected:
            raise ValueError(f"Test source changed: {name}")
    for name, expected in manifest["derived_source_sha256"].items():
        if digest(out / name) != expected:
            raise ValueError(f"Derived test source changed: {name}")
    if digest(out / "obj/Vtb_conv_npu") != manifest["binary_sha256"]:
        raise ValueError("Simulator executable differs from its manifest")
    return manifest


def fields(line):
    return {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", line)}


def run_suite(npu, sim, out, cases, wait_pattern, manifest):
    suite = out / f"{wait_pattern}.suite"
    suite.write_text("".join(" ".join(str(case/name) for name in
        ("config.mem", "init.mem", "golden.mem", "required.mem", "acc.mem")) + "\n" for case in cases))
    events = out / f"{wait_pattern}.events.txt"
    command = [sim/"obj/Vtb_conv_npu", f"+SUITE={suite}", "+NPU_UTIL_SUMMARY",
               f"+WEIGHT_SWITCH_EVENTS={events}"]
    if wait_pattern == "fixed":
        command.append("+NO_RANDOM_WAIT")
    log = out / f"{wait_pattern}.log"
    rc = npu.command(command, log, timeout=600)
    lines = log.read_text().splitlines()
    tasks = [fields(line) for line in lines if line.startswith("CONV_TASK_PASS ")]
    switches = [fields(line) for line in lines if line.startswith("WEIGHT_SWITCH_TASK ")]
    group_events = {}
    for line in events.read_text().splitlines():
        if line[:2] in ("S ", "I ", "L "):
            record = fields(line)
            group_events.setdefault(record["task"], {}).setdefault(line[0], {})[record["group"]] = record
    for switch in switches:
        records = group_events.get(switch["task"], {})
        starts = records.get("S", {})
        first_rows, last_rows = records.get("I", {}), records.get("L", {})
        switch["direct_groups"] = sum(row["direct"] for row in starts.values())
        switch["direct_signal_cycles"] = switch.pop("direct_cycles")
        gaps = [row["cycle"]-last_rows[group-1]["cycle"]
                for group, row in first_rows.items() if group-1 in last_rows]
        switch["last_input_to_next_first_cycles"] = dict(count=len(gaps),
            minimum=min(gaps) if gaps else None, maximum=max(gaps) if gaps else None,
            total=sum(gaps), histogram=[dict(cycles=value, count=count)
                for value, count in sorted(Counter(gaps).items())])
    ps = [fields(line) for line in lines if line.startswith("PS_STREAM_SUMMARY ")]
    checks = dict(exit_zero=rc == 0, completed=len(tasks) == len(cases),
        observed=len(switches) == len(cases),
        suite_completed=any(line.startswith(f"CONV_NPU_PASS tasks={len(cases)} ") for line in lines),
        ps_complete=len(ps) == 1 and ps[0]["writes"] == ps[0]["reads"] and ps[0]["discarded"] == 0)
    measurements = []
    for case, task, switch in zip(cases, tasks, switches):
        metadata = json.loads((case / "case.json").read_text())
        shape = metadata["shape"]
        measurements.append(dict(name=metadata["name"], shape=shape, case=metadata["case"],
            force_raw=metadata["force_raw"], memory_sha256=metadata["memory_sha256"],
            hardware=task, switching=switch))
        checks[metadata["name"]] = (task["int32_checks"] == shape["m"]*shape["n"] and
            task["cycles"] == switch["cycles"] and switch["input_rows"] == switch["output_rows"])
        spec = metadata["case"]
        guarded = (spec.get("bias") or spec.get("per_channel") or spec.get("mode") or
                   spec.get("out16") or spec.get("frame") or spec["red"] > SIZE or
                   spec["name"] == "coalesced_capacity" or
                   (spec["name"] == "capacity_rows" and spec["r"] >= 32))
        if guarded:
            checks[metadata["name"] + "_waits_for_dependencies"] = (
                switch["first_input_overlap"] == 0 and switch["direct_groups"] == 0)
    if manifest["weight_select_wave"]:
        required = {"continuous_tiles", "unequal_groups", "packed_groups", "coalesced_below_capacity"}
        if any(row["case"]["name"] in required for row in measurements):
            checks["active_weight_switch_measured"] = any(row["commits_with_rows"] for row in switches)
            checks["overlapping_input_groups_measured"] = any(row["first_input_overlap"] for row in switches)
            checks["mixed_row_selectors_measured"] = any(row["mixed_select_cycles"] for row in switches)
    else:
        checks["serial_input_groups_measured"] = all(row["first_input_overlap"] == 0 for row in switches)
        checks["serial_weight_commits_measured"] = all(row["commits_with_rows"] == 0 for row in switches)
    result = dict(wait_pattern=wait_pattern, passed=all(checks.values()), returncode=rc,
        checks=checks, command=list(map(str, command)), measurements=measurements,
        partial_sums=ps[0] if ps else {}, log_sha256=digest(log), events_sha256=digest(events))
    write_json(out / f"{wait_pattern}.json", result)
    print(f"WEIGHT_SWITCH_SUITE {wait_pattern} passed={result['passed']} cases={len(measurements)} "
          f"commit_overlap={sum(row['commits_with_rows'] for row in switches)} "
          f"input_overlap={sum(row['first_input_overlap'] for row in switches)}", flush=True)
    if not result["passed"]:
        print("\n".join(lines[-45:]), flush=True)
    return result


def compare(current, reference):
    if current["profile"] != reference["profile"]:
        raise ValueError("Cycle comparisons require identical hardware capacity and bus settings")
    previous = {(suite["wait_pattern"], row["name"]): row for suite in reference["suites"]
                for row in suite["measurements"]}
    rows = []
    for suite in current["suites"]:
        for row in suite["measurements"]:
            old = previous[(suite["wait_pattern"], row["name"])]
            if row["memory_sha256"] != old["memory_sha256"]:
                raise ValueError(f"Compared inputs or expected outputs differ: {row['name']}")
            before, after = old["hardware"]["cycles"], row["hardware"]["cycles"]
            rows.append(dict(wait_pattern=suite["wait_pattern"], name=row["name"],
                previous_cycles=before, current_cycles=after, saved_cycles=before-after,
                speedup=before/after, previous_switching=old["switching"], current_switching=row["switching"]))
    return dict(same_inputs=True, same_hardware=True, measurements=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rtl-root", type=Path, default=ROOT)
    parser.add_argument("--sim", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--bank-bytes", type=int, choices=(2048, 4096, 8192), default=2048)
    parser.add_argument("--bank-count", type=int, choices=(6, 7, 8, 9), default=7)
    parser.add_argument("--bus-width", type=int, choices=(32, 64), default=64)
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--wait-patterns", nargs="+", choices=("fixed", "random"), default=["fixed", "random"])
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--lint-only", action="store_true")
    parser.add_argument("--keep-objects", action="store_true")
    args = parser.parse_args()
    root, out = args.rtl_root.resolve(), args.out.resolve()
    runner_hash = digest(Path(__file__))
    npu = import_npu(root)
    profile = dict(size=SIZE, bus_width=args.bus_width, shared_bank_bytes=args.bank_bytes,
        shared_bank_count=args.bank_count, pool_bytes=(args.bank_count-1)*args.bank_bytes,
        window_cache_bytes=4096, runtime_raw_and_adaptive=True)
    cases = generate(npu, out/"cases", profile, args.cases)
    if args.generate_only:
        write_json(out / "generated.json", dict(profile=profile, cases=list(map(str, cases))))
        print(f"WEIGHT_SWITCH_GENERATED cases={len(cases)}", flush=True)
        return 0
    sim = args.sim.resolve() if args.sim else out/"sim"
    if not args.sim:
        build(npu, root, sim, profile, args.verilator, args.jobs, args.lint_only)
    if args.lint_only:
        return 0
    manifest = validate_sim(root, sim, profile)
    suites = []
    for pattern in args.wait_patterns:
        suites.append(run_suite(npu, sim, out, cases, pattern, manifest))
        if not suites[-1]["passed"]:
            break
    summary = dict(passed=all(item["passed"] for item in suites) and len(suites) == len(args.wait_patterns),
        profile=profile, simulator_manifest=str(sim/"build.json"),
        binary_sha256=manifest["binary_sha256"], weight_select_wave=manifest["weight_select_wave"],
        source_sha256=manifest["source_sha256"],
        build_test_source_sha256=manifest["test_source_sha256"],
        test_source_sha256={name: digest(HERE/name) for name in manifest["test_source_sha256"]},
        runner_sha256=runner_hash,
        source_identity=manifest["source_identity"],
        expected_cases=len(args.wait_patterns)*len(cases),
        completed_cases=sum(len(suite["measurements"]) for suite in suites),
        int32_checks=sum(row["hardware"]["int32_checks"] for suite in suites for row in suite["measurements"]),
        suites=suites)
    if args.reference:
        summary["comparison"] = compare(summary, json.loads(args.reference.read_text()))
        summary["reference"] = str(args.reference.resolve())
    validate_sim(root, sim, profile)
    if runner_hash != digest(Path(__file__)):
        raise ValueError("The test runner changed during execution")
    write_json(out / "summary.json", summary)
    if not args.keep_objects and not args.sim:
        for path in (sim/"obj").iterdir():
            if path.name != "Vtb_conv_npu":
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
    print(f"WEIGHT_SWITCH_RESULT passed={summary['passed']} cases={summary['completed_cases']} "
          f"int32_checks={summary['int32_checks']}", flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
