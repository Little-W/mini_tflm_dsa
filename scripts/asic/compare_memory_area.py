#!/usr/bin/env python3
"""使用统一工艺库和 150 MHz 约束比较两个完整 NPU 的实际 DC 面积与时序。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DATABASES = ("RAMTP128X16_tt_1p10v_1p10v_25c.db",
                    "RAMTP1024X16_tt_1p10v_1p10v_25c.db")
PARAMETERS = {
    "WEIGHT_WIDTH": 16, "DATA_WIDTH": 16, "SIZE": 16, "BUS_WIDTH": 64,
    "REG_WIDTH": 32, "ADDR_WIDTH": 19, "SHARED_BANK_BYTES": 8192,
    "SHARED_BANK_COUNT": 7, "IA_CACHE_BLOCKS": 4, "PS_FRAME_COUNT": 16,
    "IM2COL_CACHE_BYTES": 4096, "AXI_READ_OUTSTANDING": 4, "AXI_WRITE_OUTSTANDING": 4,
    "ENABLE_VECTOR_ENGINE": 1, "VECTOR_PE_COUNT": 16,
    "ENABLE_IS_MODE": 1, "ENABLE_PER_CHANNEL": 1,
}
DEFINES = "+define+GEMPACT_PS_COMPRESS+GEMMORA_PS_POOL_BYTES=49152+GEMMORA_PS_FORCE_RAW"
SCOPES = ("whole", "kernel", "bias", "requant", "requant_group", "product_amount")
AREA_FIELDS = ("total_cell_area", "standard_cell_area", "macro_area", "leaf_count",
               "RAMTP128X16", "RAMTP1024X16", "macro_capacity_bits")
REQUIRED_OUTPUTS = (
    "npu_top_elab.ddc", "npu_top_syn.ddc", "npu_top_syn.vg", "npu_top_syn.sdc",
    "npu_top_area.rpt", "npu_top_qor.rpt", "npu_top_timing.rpt", "npu_top_hold_timing.rpt",
    "npu_top_check_design_elab.rpt", "npu_top_check_design.rpt", "npu_top_check_timing.rpt",
    "npu_top_sram_instances.rpt", "npu_top_requant_storage.rpt", "npu_top_reference.rpt",
    "npu_top_design.rpt", "npu_top_constraints.rpt", "npu_top_summary.rpt", "memory_metrics.tsv",
)

# 面积来自已链接的实际库单元。每个范围内的叶单元只累计一次。
MEASURE_TCL = r'''
report_qor > ${PROJ_TEMP}/${DESIGN_TOP}_qor.rpt
report_area > ${PROJ_TEMP}/${DESIGN_TOP}_area.rpt
report_area -hierarchy >> ${PROJ_TEMP}/${DESIGN_TOP}_area.rpt
report_design > ${PROJ_TEMP}/${DESIGN_TOP}_design.rpt
report_reference > ${PROJ_TEMP}/${DESIGN_TOP}_reference.rpt
report_constraints -all_violators > ${PROJ_TEMP}/${DESIGN_TOP}_constraints.rpt
report_timing -delay_type max -nets -input -transition_time -capacitance -nworst 10 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_timing.rpt
report_timing -delay_type min -nets -input -transition_time -capacitance -nworst 10 \
    > ${PROJ_TEMP}/${DESIGN_TOP}_hold_timing.rpt
set report [open [file join $PROJ_TEMP memory_metrics.tsv] w]
puts $report "scope\tmetric\tvalue"
set hierarchy [get_cells -hierarchical -filter {is_hierarchical == true}]
array set selected {kernel {} bias {} requant {} requant_group {} product_amount {}}
foreach_in_collection cell $hierarchy {
    set name [get_object_name $cell]
    set ref [get_attribute $cell ref_name]
    if {[string match *kernel_loader_buffer* $ref]} {lappend selected(kernel) $name}
    if {[string match *bias_loader_buffer* $ref]} {lappend selected(bias) $name}
    if {[string match *vec_requant* $ref]} {lappend selected(requant) $name}
    if {[string match *requant_group_buffer* $ref]} {lappend selected(requant_group) $name}
    if {[string match *u_product_amount $name]} {lappend selected(product_amount) $name}
}
foreach scope {kernel bias requant requant_group product_amount} {
    set outer {}
    foreach name $selected($scope) {
        set nested 0
        foreach parent $selected($scope) {
            if {$name ne $parent && [string first "${parent}/" $name] == 0} {set nested 1; break}
        }
        if {!$nested} {lappend outer $name}
    }
    set selected($scope) $outer
    set expected [expr {$scope eq "product_amount" ? 2 : 1}]
    if {[llength $outer] != $expected} {error "Missing or ambiguous storage hierarchy: $scope"}
}
array set totals {}
foreach scope {whole kernel bias requant requant_group product_amount} {
    foreach field {total_cell_area standard_cell_area macro_area leaf_count RAMTP128X16 RAMTP1024X16 macro_capacity_bits} {
        set totals($scope,$field) 0
    }
}
set cache [dict create]
foreach_in_collection cell [get_cells -hierarchical -filter {is_hierarchical == false}] {
    set name [get_object_name $cell]
    set ref [get_attribute $cell ref_name]
    if {[regexp {^\*\*logic_[01zxZX]\*\*$} $ref]} {continue}
    if {![dict exists $cache $ref]} {
        set libcell [get_lib_cells -quiet */$ref]
        if {[sizeof_collection $libcell] != 1} {error "Missing or ambiguous mapped library cell: $ref"}
        dict set cache $ref [get_attribute $libcell area]
    }
    set area [dict get $cache $ref]
    if {![string is double -strict $area] || $area < 0} {error "Invalid mapped area for $ref"}
    set scopes {whole}
    foreach scope {kernel bias requant requant_group product_amount} {
        foreach parent $selected($scope) {
            if {[string first "${parent}/" $name] == 0} {lappend scopes $scope; break}
        }
    }
    set macro [expr {$ref eq "RAMTP128X16" || $ref eq "RAMTP1024X16"}]
    if {$macro && $area <= 0} {error "SRAM library area is missing for $ref"}
    foreach scope $scopes {
        incr totals($scope,leaf_count)
        set totals($scope,total_cell_area) [expr {$totals($scope,total_cell_area)+$area}]
        if {$macro} {
            incr totals($scope,$ref)
            incr totals($scope,macro_capacity_bits) [expr {$ref eq "RAMTP128X16" ? 2048 : 16384}]
            set totals($scope,macro_area) [expr {$totals($scope,macro_area)+$area}]
        } else {
            set totals($scope,standard_cell_area) [expr {$totals($scope,standard_cell_area)+$area}]
        }
    }
}
foreach scope {whole kernel bias requant requant_group product_amount} {
    if {$totals($scope,leaf_count) == 0} {error "No mapped cells in $scope"}
    foreach field {total_cell_area standard_cell_area macro_area leaf_count RAMTP128X16 RAMTP1024X16 macro_capacity_bits} {
        puts $report "$scope\t$field\t$totals($scope,$field)"
    }
}
foreach {delay field} {max setup_slack_ns min hold_slack_ns} {
    set paths [get_timing_paths -delay_type $delay -max_paths 1 -nworst 1]
    if {[sizeof_collection $paths] == 0} {error "No constrained $delay timing path"}
    set worst_slack ""
    foreach_in_collection path $paths {
        set slack [get_attribute $path slack]
        if {$worst_slack eq "" || $slack < $worst_slack} {set worst_slack $slack}
    }
    set measured_timing($field) $worst_slack
    puts $report "timing\t$field\t$worst_slack"
}
puts $report "timing\tclock_period_ns\t$CLK_PERIOD_NS"
close $report
set summary [open [file join $PROJ_TEMP npu_top_summary.rpt] w]
puts $summary "design: $DESIGN_TOP"
puts $summary "target_freq_mhz: $TARGET_FREQ_MHZ"
puts $summary "clock_period_ns: $CLK_PERIOD_NS"
puts $summary "compile_mode: $COMPILE_MODE"
puts $summary "parameters: $DESIGN_PARAMETERS"
puts $summary "worst_setup_slack_ns: $measured_timing(setup_slack_ns)"
puts $summary "worst_hold_slack_ns: $measured_timing(hold_slack_ns)"
puts $summary "setup_result: [expr {$measured_timing(setup_slack_ns) >= 0 ? {PASS} : {FAIL}}]"
puts $summary "hold_result: [expr {$measured_timing(hold_slack_ns) >= 0 ? {PASS} : {FAIL}}]"
close $summary
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def tcl_string(value):
    text = str(value)
    for before, after in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"),
                          ("[", "\\["), ("]", "\\]"), ("\n", "\\n"), ("\r", "\\r")):
        text = text.replace(before, after)
    return '"' + text + '"'


def input_paths(root):
    filelist = root / "asic/synthesis/filelists/npu_top.f"
    paths = {filelist, root / "asic/rtl/smic40_sram_1r1w.sv"}
    for line in filelist.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("+incdir+"):
            folder = (filelist.parent.parent / line[8:]).resolve()
            paths.update(path for path in folder.rglob("*") if path.suffix in (".vh", ".svh"))
        else:
            paths.add((filelist.parent.parent / line).resolve())
    return sorted(paths)


def copy_snapshot(root, destination):
    hashes = {}
    for source in input_paths(root):
        relative = source.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[str(relative)] = digest(target)
    if any(digest(root / name) != value for name, value in hashes.items()):
        raise RuntimeError("Source files changed while creating the snapshot")
    return hashes


def require_unchanged(folder, hashes):
    changed = [name for name, value in hashes.items()
               if not (folder / name).is_file() or digest(folder / name) != value]
    if changed:
        raise RuntimeError("Measured input files changed: " + ", ".join(changed))


def resolve_libraries(args):
    standard = list(args.std_db or [])
    if not standard:
        folder = Path(os.environ.get("STD_DB_PATH", "."))
        standard = [folder / name for name in shlex.split(os.environ.get("STD_DB_LIST", ""))]
    if args.libs:
        memory = [args.libs / name for name in MEMORY_DATABASES]
    else:
        folder = Path(os.environ.get("MEM_DB_PATH", "."))
        names = shlex.split(os.environ.get("MEM_DB_LIST", ""))
        memory = [folder / name for name in names]
    if not standard or not memory:
        if args.prepare_only:
            placeholder = args.out.resolve() / "required_libraries"
            standard = standard or [placeholder / "standard_cells.db"]
            memory = memory or [placeholder / name for name in MEMORY_DATABASES]
        else:
            raise RuntimeError("Required libraries: specify --std-db and --libs, or STD_DB_PATH/STD_DB_LIST and MEM_DB_PATH/MEM_DB_LIST")
    standard, memory = [p.resolve() for p in standard], [p.resolve() for p in memory]
    if set(path.name for path in memory) != set(MEMORY_DATABASES):
        raise RuntimeError("MEM_DB_LIST must contain the two TT RAMTP128X16/RAMTP1024X16 databases")
    missing = [str(path) for path in standard + memory if not path.is_file() or path.stat().st_size == 0]
    if missing and not args.prepare_only:
        raise RuntimeError("Required library files are unavailable: " + ", ".join(missing))
    return standard, memory, missing


def parse_reports(folder):
    metrics = {name: {} for name in (*SCOPES, "timing")}
    lines = (folder / "memory_metrics.tsv").read_text().splitlines()
    if not lines or lines[0] != "scope\tmetric\tvalue":
        raise RuntimeError("DC memory metrics header is missing")
    for line in lines[1:]:
        scope, field, value = line.split("\t")
        if scope not in metrics or field in metrics[scope]:
            raise RuntimeError("Unexpected or duplicate DC metric: " + line)
        number = float(value)
        if not math.isfinite(number):
            raise RuntimeError("DC reported a non-finite metric: " + line)
        metrics[scope][field] = number
    for scope in SCOPES:
        values = metrics[scope]
        if set(values) != set(AREA_FIELDS) or any(value < 0 for value in values.values()):
            raise RuntimeError("Incomplete mapped-area result for " + scope)
        if values["leaf_count"] <= 0 or values["total_cell_area"] <= 0:
            raise RuntimeError("Mapped cells or area are missing for " + scope)
        if not math.isclose(values["total_cell_area"], values["standard_cell_area"] + values["macro_area"],
                            rel_tol=1e-9, abs_tol=1e-6):
            raise RuntimeError("Standard-cell and macro areas do not sum to total cell area")
        for field in ("leaf_count", "RAMTP128X16", "RAMTP1024X16", "macro_capacity_bits"):
            if not values[field].is_integer():
                raise RuntimeError("DC reported a fractional cell count or capacity")
            values[field] = int(values[field])
        if values["macro_capacity_bits"] != values["RAMTP128X16"] * 2048 + values["RAMTP1024X16"] * 16384:
            raise RuntimeError("SRAM instance count and capacity differ")
        if values["macro_capacity_bits"] and values["macro_area"] <= 0:
            raise RuntimeError("Mapped SRAM area is missing")
    timing = metrics["timing"]
    if set(timing) != {"setup_slack_ns", "hold_slack_ns", "clock_period_ns"}:
        raise RuntimeError("Complete setup and hold timing results are required")
    if not math.isclose(timing["clock_period_ns"], 1000.0 / 150.0, rel_tol=1e-8):
        raise RuntimeError("DC clock period differs from the 150 MHz comparison")
    area = (folder / "npu_top_area.rpt").read_text()
    match = re.search(r"Total cell area:\s*([+\-\d.eE]+)", area)
    if not match or not math.isclose(float(match[1]), metrics["whole"]["total_cell_area"], rel_tol=1e-5, abs_tol=0.1):
        raise RuntimeError("Mapped leaf area differs from report_area")
    if metrics["whole"]["RAMTP128X16"] + metrics["whole"]["RAMTP1024X16"] == 0:
        raise RuntimeError("The complete NPU has no linked SRAM macros")
    metrics["timing"]["setup_met"] = timing["setup_slack_ns"] >= 0
    metrics["timing"]["hold_met"] = timing["hold_slack_ns"] >= 0
    return metrics


def prepare_case(args, name, source, out, flow, standard, memory, prepare_script):
    case = out / name
    case.mkdir()
    frozen = case / "snapshot"
    source_hashes = copy_snapshot(source, frozen)
    prepared = case / "prepared"
    command = [sys.executable, str(prepare_script), "--root", str(frozen), "--out", str(prepared)]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    (case / "prepare.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("DC source preparation failed: " + str(case / "prepare.log"))
    mode = int(name.rsplit("ia", 1)[1])
    parameters = dict(PARAMETERS, IA_COMPACT_ENABLE=mode)
    settings = {
        "PROJ_PATH": str(flow), "PROJ_ROOT": str(frozen), "PROJ_TEMP": str(case),
        "RTL_ROOT": str(frozen / "rtl"), "INC_ROOT": str(frozen / "include"),
        "DESIGN": "npu_top", "DESIGN_TOP": "npu_top",
        "DESIGN_FILELIST": str(prepared / "sources.f"),
        "DESIGN_SYN_SDC": str(flow / "constraints/npu_top.sdc"),
        "DESIGN_TARGET_FREQ_MHZ": "150", "DESIGN_MAX_CORES": str(args.max_cores),
        "DESIGN_COMPILE_MODE": args.compile_mode, "DESIGN_RTL_DEFINES": DEFINES,
        "DESIGN_PARAMETERS": ",".join(f"{key}={value}" for key, value in parameters.items()),
        "DESIGN_CHECKPOINT": "", "DESIGN_INCREMENTAL": "0", "DESIGN_REPORT_ONLY": "0",
        "DESIGN_ELAB_ONLY": "0", "DESIGN_FORCE_UNIQUIFY": "0", "INTERRUPT": "0",
        "STD_DB_PATH": "", "STD_DB_LIST": " ".join(tcl_string(path) for path in standard),
        "MEM_DB_PATH": "", "MEM_DB_LIST": " ".join(tcl_string(path) for path in memory),
        "SYN_STD_LIB_NAME": args.std_lib_name or standard[0].stem,
        "SYN_OPER_CONDITION": args.operating_condition,
    }
    # 统一比较只使用显式列出的库，避免继承其他工程的附加工艺角或 IO 库。
    settings.update({f"{name}_DB_{kind}": "" for name in ("AFE", "IO", "LPK", "SYNC") for kind in ("PATH", "LIST")})
    script = "\n".join(f"set ::env({key}) {tcl_string(value)}" for key, value in sorted(settings.items()))
    script += "\nset sh_continue_on_error false\n"
    for stage in ("1_common_setup", "2_dc_setup", "3_read_design"):
        script += "source -e -v " + tcl_string(flow / f"scripts/{stage}.tcl") + "\n"
    script += "source -e -v " + tcl_string(flow / "constraints/npu_top.sdc") + "\n"
    for stage in ("4_design_environment", "5_compile_design"):
        script += "source -e -v " + tcl_string(flow / f"scripts/{stage}.tcl") + "\n"
    script += MEASURE_TCL + '\nputs "MEMORY_AREA_COMPARISON_COMPLETE"\nexit\n'
    (case / "run.tcl").write_text(script)
    write_json(case / "environment.json", settings)
    frozen_hashes = {str(path.relative_to(case)): digest(path) for folder in (frozen, prepared)
                     for path in sorted(folder.rglob("*")) if path.is_file()}
    frozen_hashes["run.tcl"] = digest(case / "run.tcl")
    return {"name": name, "source_root": str(source), "output": str(case), "parameters": parameters,
            "source_sha256": source_hashes, "snapshot_sha256": frozen_hashes,
            "status": "prepared", "dc_executed": False}


def execute_case(args, case, executable, libraries, flow, flow_hashes, on_start):
    folder = Path(case["output"])
    require_unchanged(folder, case["snapshot_sha256"])
    require_unchanged(flow, flow_hashes)
    for path, expected in libraries.items():
        if digest(Path(path)) != expected:
            raise RuntimeError("A synthesis library changed: " + path)
    # 独立进程使用固定输入，标准输出写入文件，避免长综合占用终端输出缓冲。
    case.update(status="running", dc_executed=True)
    on_start()
    with (folder / "synthesis.log").open("w") as log:
        completed = subprocess.run([executable, "-f", str(folder / "run.tcl")], cwd=folder,
                                   stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
    text = (folder / "synthesis.log").read_text(errors="replace")
    if completed.returncode or re.search(r"^\s*(?:Error|Fatal):", text, re.M) or "MEMORY_AREA_COMPARISON_COMPLETE" not in text:
        raise RuntimeError("DC synthesis did not complete successfully: " + str(folder / "synthesis.log"))
    require_unchanged(folder, case["snapshot_sha256"])
    require_unchanged(flow, flow_hashes)
    for path, expected in libraries.items():
        if digest(Path(path)) != expected:
            raise RuntimeError("A synthesis library changed: " + path)
    missing = [name for name in REQUIRED_OUTPUTS
               if not (folder / name).is_file() or (folder / name).stat().st_size == 0]
    if missing:
        raise RuntimeError("Required DC outputs are missing or empty: " + ", ".join(missing))
    measurements = parse_reports(folder)
    reports = [path for pattern in ("*.rpt", "*.tsv", "*.vg", "*.ddc", "*.sdc", "synthesis.log")
               for path in folder.glob(pattern)]
    case.update(status="measured", dc_executed=True, measurements=measurements,
                report_sha256={path.name: digest(path) for path in sorted(set(reports))})
    write_json(folder / "measurement.json", case)


def comparison(cases):
    pairs = []
    indexed = {case["name"]: case["measurements"] for case in cases}
    for mode in (0, 1):
        before, after = indexed[f"reference_ia{mode}"], indexed[f"current_ia{mode}"]
        areas = {scope: {field + "_change": after[scope][field] - before[scope][field]
                         for field in ("total_cell_area", "standard_cell_area", "macro_area")}
                 for scope in SCOPES}
        pairs.append({"IA_COMPACT_ENABLE": mode, "areas": areas,
                      "setup_slack_change_ns": after["timing"]["setup_slack_ns"] - before["timing"]["setup_slack_ns"],
                      "hold_slack_change_ns": after["timing"]["hold_slack_ns"] - before["timing"]["hold_slack_ns"]})
    return pairs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--std-db", type=Path, action="append", help="标准单元 .db；可以重复传入")
    parser.add_argument("--libs", type=Path, help="包含两个 TT SRAM .db 的目录")
    parser.add_argument("--std-lib-name", default=os.environ.get("SYN_STD_LIB_NAME"))
    parser.add_argument("--operating-condition", default=os.environ.get("SYN_OPER_CONDITION", "tt_v1p1_25c"))
    parser.add_argument("--dc-shell", default=os.environ.get("DC_SHELL", "dc_shell"))
    parser.add_argument("--compile-mode", choices=("quick", "standard", "ultra"), default="ultra")
    parser.add_argument("--max-cores", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=14400, help="每次 DC 综合的秒数上限")
    parser.add_argument("--prepare-only", action="store_true", help="只保存输入与命令，不产生面积或时序结果")
    args = parser.parse_args(argv)
    if args.max_cores < 1 or args.timeout <= 0:
        parser.error("Core count and timeout must be positive")
    out, current, reference = args.out.resolve(), args.source_root.resolve(), args.reference_root.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Use an empty output directory")
    executable = shutil.which(args.dc_shell)
    if not executable and not args.prepare_only:
        parser.error("Required tool dc_shell is unavailable")
    manifest, active_case = None, None
    try:
        standard, memory, missing = resolve_libraries(args)
        out.mkdir(parents=True, exist_ok=True)
        flow = out / "flow"
        for name in ("scripts", "constraints"):
            shutil.copytree(current / "asic/synthesis" / name, flow / name)
        prepare_script = flow / "prepare_dc_sources.py"
        shutil.copy2(Path(__file__).with_name("prepare_dc_sources.py"), prepare_script)
        flow_hashes = {str(path.relative_to(flow)): digest(path) for path in sorted(flow.rglob("*")) if path.is_file()}
        libraries = {str(path): digest(path) for path in standard + memory if path.is_file()}
        cases = [prepare_case(args, f"{name}_ia{mode}", source, out, flow, standard, memory, prepare_script)
                 for name, source in (("reference", reference), ("current", current)) for mode in (0, 1)]
        manifest = {"status": "prepared", "dc_executed": False, "frequency_mhz": 150,
                    "compile_mode": args.compile_mode, "max_cores": args.max_cores,
                    "library_sha256": libraries, "missing_libraries": missing,
                    "flow_source_root": str(current), "flow_sha256": flow_hashes,
                    "entry_script_sha256": digest(Path(__file__)), "cases": cases}
        for name in ("reference", "current"):
            modes = [case for case in cases if case["name"].startswith(name + "_")]
            if modes[0]["source_sha256"] != modes[1]["source_sha256"]:
                raise RuntimeError("IA modes have different source snapshots for " + name)
        write_json(out / "comparison.json", manifest)
        if args.prepare_only:
            print(json.dumps({"status": "prepared", "dc_executed": False, "cases": len(cases), "out": str(out)}))
            return 0
        version = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=30)
        if version.returncode:
            raise RuntimeError("dc_shell -version failed")
        manifest["tool_version"] = (version.stdout + version.stderr).strip()
        def on_start():
            manifest.update(status="running", dc_executed=True, active_case=active_case["name"])
            write_json(out / "comparison.json", manifest)

        for case in cases:
            active_case = case
            execute_case(args, case, executable, libraries, flow, flow_hashes, on_start)
            write_json(out / "comparison.json", manifest)
            print(json.dumps({"case": case["name"], "status": case["status"]}), flush=True)
        manifest.pop("active_case", None)
        manifest.update(status="measured", dc_executed=True, differences=comparison(cases))
        write_json(out / "comparison.json", manifest)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        if manifest is not None:
            if active_case is not None:
                active_case.update(status="failed", failure_reason=str(error))
                write_json(Path(active_case["output"]) / "measurement.json", active_case)
            manifest.pop("active_case", None)
            manifest.update(status="failed", dc_executed=any(case["dc_executed"] for case in manifest["cases"]),
                            failed_case=active_case["name"] if active_case is not None else None,
                            failure_reason=str(error))
            write_json(out / "comparison.json", manifest)
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
