#!/usr/bin/env python3
"""Build a Python-callable RTL snapshot and an independent --binary runner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import fcntl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WARNINGS = [
    "GENUNNAMED", "VARHIDDEN", "WIDTHEXPAND", "UNUSEDSIGNAL", "UNUSED",
    "UNUSEDGENVAR", "UNDRIVEN", "PINMISSING", "STMTDLY", "DECLFILENAME",
    "CASEINCOMPLETE", "EOFNEWLINE", "SYNCASYNCNET", "COMBDLY",
    "PINCONNECTEMPTY", "WIDTHTRUNC", "ASCRANGE", "INITIALDLY", "BLKSEQ",
    "MULTIDRIVEN", "LATCH",
]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def runtime_objects(output_root, cxx, include):
    """Cache only immutable, model-independent PIC Verilator runtime objects."""
    runtime=[include/name for name in ["verilated.cpp","verilated_dpi.cpp",
                                      "verilated_timing.cpp","verilated_threads.cpp"]]
    flags=["-std=c++20","-O2","-fPIC","-pthread",
           "-I"+str(include),"-I"+str(include/"vltstd")]
    identity={"compiler":str(Path(shutil.which(cxx) or cxx).resolve()),
              "compiler_version":subprocess.check_output([cxx,"--version"],text=True),
              "flags":flags,
              "dependencies":{str(p.relative_to(include)):digest(p)
                              for p in sorted(include.rglob("*"))
                              if p.is_file() and p.suffix in {".h",".hpp",".cpp"}}}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    cache=output_root/"runtime_cache"/key
    cache.mkdir(parents=True,exist_ok=True)
    objects=[cache/(p.stem+".o") for p in runtime]
    with (cache/"compile.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for src,obj in zip(runtime,objects):
            if not obj.exists():
                temporary=obj.with_suffix(".partial.o")
                subprocess.run([cxx,*flags,"-c",str(src),"-o",str(temporary)],check=True)
                temporary.replace(obj)
        identity["object_sha256"]={p.name:digest(p) for p in objects}
        (cache/"manifest.json").write_text(json.dumps(identity,indent=2)+"\n")
    return objects,{"cache_key":key,**identity}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--size", type=int, default=16)
    ap.add_argument("--cache", type=int, default=64)
    ap.add_argument("--ps", type=int, default=25)
    ap.add_argument("--mem-words", type=int, default=8388608,
                    help="External testbench RAM words only; does not alter NPU storage")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--cxx", default="g++-13" if shutil.which("g++-13") else "g++")
    ap.add_argument("--operand-cache",action="store_true")
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--ps-sector-codec",action="store_true")
    ap.add_argument("--ps-pool-bytes",type=int,default=327680)
    ap.add_argument("--force-raw",action="store_true")
    ap.add_argument("--panel-rows",type=int,default=32)
    ap.add_argument("--panel-cols",type=int,default=32)
    ap.add_argument("--pcr-ps",action="store_true")
    ap.add_argument("--pcr-enable",type=int,choices=[0,1],default=1)
    ap.add_argument("--pcr-fast-enable",type=int,choices=[0,1],default=1)
    ap.add_argument("--output-root",type=Path)
    args = ap.parse_args()
    for value in [args.size, args.cache]:
        if value < 2 or value & (value-1):
            ap.error("size and cache must be powers of two >= 2")
    if args.ps < 1:
        ap.error("ps must be positive")
    if not (1<=args.panel_rows<=32 and 1<=args.panel_cols<=32):
        ap.error("physical panel rows/cols must be 1..32")
    if args.ps_pool_bytes < 1024 or args.ps_pool_bytes % 256:
        ap.error("PS pool must be a multiple of 256 bytes and at least 1024 bytes")
    tag = f"s{args.size}_c{args.cache}_p{args.ps}_m{args.mem_words}"
    if args.operand_cache: tag += "_oc_v25_first_ar"
    tag += "_sector"+str(args.ps_pool_bytes) if args.ps_sector_codec else "_raw_v9"
    if args.force_raw:tag += "_force_raw"
    tag += f"_r{args.panel_rows}_w{args.panel_cols}"
    if args.pcr_ps:tag += f"_pcr{args.pcr_enable}_fast{args.pcr_fast_enable}"
    tag += "_measured"
    tag += "_i8"
    output_root=args.output_root.resolve() if args.output_root else HERE
    work = output_root / "build" / tag
    dest = output_root / "backends" / tag
    if (dest/"manifest.json").exists():
        ap.error(f"Refusing to overwrite a measured backend: {dest}")
    work.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    snapshot=dest/"source_snapshot"
    if snapshot.exists():shutil.rmtree(snapshot)
    shutil.copytree(ROOT/"rtl", snapshot/"rtl")
    shutil.copytree(ROOT/"test/pcr", snapshot/"test/pcr")
    snapshot_here=snapshot/"veri/pcr_model"
    shutil.copytree(HERE,snapshot_here,ignore=shutil.ignore_patterns("build","backends","__pycache__"))
    npu = snapshot / "rtl/npu"
    sources = sorted(npu.rglob("*.sv")) + sorted(npu.rglob("*.v"))
    sources += [snapshot / "rtl/common/pseudo_dual_port_ram.v", snapshot / "test/pcr/ddr_axi_mem_model.sv",
                snapshot / "test/pcr/tb_npu_top.sv", snapshot_here / "cycle_probe.sv"]
    flags = ["-DGEMPACT_PANEL_ENGINE",
        f"-DTB_OPERAND_CACHE_ENABLE={int(args.operand_cache)}", "--assert",
        "--timing", "-sv", "--top-module", "tb_npu_top", "-Wno-fatal",
        *[f"-Wno-{warning}" for warning in WARNINGS],
        f"-DTB_SIZE={args.size}", f"-DTB_IA_CACHE_BLOCKS={args.cache}",
        f"-DTB_PS_FRAME_COUNT={args.ps}", "-DTB_AXI_READ_OUTSTANDING=4",
        "-DTB_DATA_WIDTH=8", "-DTB_WEIGHT_WIDTH=8", "-DGEMMORA_INT8_PROFILE=1",
        f"-DTB_MEM_WORDS={args.mem_words}",
        f"-DGEMPACT_PANEL_MAX_R={args.panel_rows}",
        f"-DGEMPACT_PANEL_MAX_W={args.panel_cols}",
        "-I"+str(npu/"gempact"),
    ]
    if args.ps_sector_codec:
        flags += ["-DGEMMORA_PS_SECTOR_CODEC",f"-DGEMMORA_PS_POOL_BYTES={args.ps_pool_bytes}"]
    if args.force_raw:flags.append("-DGEMMORA_PS_FORCE_RAW")
    if args.pcr_ps:
        flags += ["-DGEMPACT_PCR_PS",f"-DGEMPACT_PCR_ENABLE={args.pcr_enable}",
                  f"-DGEMPACT_PCR_FAST_ENABLE={args.pcr_fast_enable}"]
    flags.append("-DPS_CODEC_MEASURE")
    env = dict(os.environ, CXX=args.cxx)
    subprocess.run(["verilator", "--cc", "--prefix", "VNpuPython",
                    "--Mdir", str(work), "-CFLAGS", "-std=c++20 -fPIC -O2",
                    *flags, *map(str, sources)], env=env, check=True)
    subprocess.run(["make", "-C", str(work), "-f", "VNpuPython.mk",
                    f"-j{args.jobs}", "VNpuPython__ALL.a", f"CXX={args.cxx}",
                    "OPT_FAST=-O2", "OPT_SLOW=-O1", "CFG_CXXFLAGS_PCH_I=-include",
                    f"PYTHON3={sys.executable}"], env=env, check=True)
    text = subprocess.check_output(["verilator", "-V"], text=True)
    verilator_root = os.environ.get("VERILATOR_ROOT") or next(
        line.split("=", 1)[1].strip() for line in text.splitlines()
        if line.strip().startswith("VERILATOR_ROOT") and line.split("=",1)[1].strip()
    )
    inc = Path(verilator_root) / "include"
    runtime, runtime_manifest = runtime_objects(output_root,args.cxx,inc)
    lib = dest / "libnpu_model.so"
    subprocess.run([
        args.cxx, "-std=c++20", "-O2", "-fPIC", "-shared", "-pthread",
        "-static-libstdc++", "-static-libgcc", "-Wl,-Bsymbolic",
        f"-DMODEL_MEM_WORDS={args.mem_words}",
        "-I"+str(work), "-I"+str(inc), "-I"+str(inc/"vltstd"),
        str(snapshot_here/"backend.cpp"), str(snapshot_here/"capture.cpp"),
        *map(str,runtime), str(work/"VNpuPython__ALL.a"), "-o", str(lib),
    ], check=True)
    server = dest / "rtl_server"
    subprocess.run([
        args.cxx, "-std=c++20", "-O2", "-static", "-pthread",
        f"-DMODEL_SIZE={args.size}",
        f"-DMODEL_MEM_WORDS={args.mem_words}",
        "-I"+str(work), "-I"+str(inc), "-I"+str(inc/"vltstd"),
        str(snapshot_here/"backend.cpp"), str(snapshot_here/"capture.cpp"), str(snapshot_here/"server.cpp"),
        *map(str,runtime), str(work/"VNpuPython__ALL.a"), "-latomic",
        "-o", str(server),
    ], check=True)
    if args.reference:
        ref = work / "reference"
        subprocess.run([
            "verilator", "--binary", "--Mdir", str(ref), "-j", str(args.jobs),
            "-CFLAGS", "-std=c++20 -O2", "-LDFLAGS", "-static",
            "-MAKEFLAGS", f"CXX={args.cxx} CFG_CXXFLAGS_PCH_I=-include PYTHON3={sys.executable}",
            *flags, *map(str,sources), str(snapshot_here/"capture.cpp"),
            "-o", "rtl_reference",
        ], env=env, check=True)
        shutil.copy2(ref/"rtl_reference", dest/"rtl_reference")
    for binary in [lib,server,dest/"rtl_reference"]:
        if binary.exists():
            subprocess.run(["strip","--strip-unneeded",str(binary)],check=True)
    manifest = {
        "schema": 1, "operand_cache":bool(args.operand_cache), "configuration_abi": 2, "external_tiling_required": True, "size": args.size, "ia_cache_blocks": args.cache,
        "ps_frame_count": args.ps, "bus_width": 32, "read_outstanding": 4,
        "ps_sector_codec": bool(args.ps_sector_codec),
        "ps_physical_pool_bytes": args.ps_pool_bytes if args.ps_sector_codec else None,
        "ps_tile_directory_entries": args.panel_rows*args.panel_cols,
        "ps_mode_directory_bytes": args.panel_rows*args.panel_cols*(
            (213+3*((args.ps_pool_bytes//256-1).bit_length())) if args.pcr_ps
            else (5+(args.ps_pool_bytes//256-1).bit_length()))/8,
        "ps_free_list_bytes": ((args.ps_pool_bytes//256)*((args.ps_pool_bytes//256-1).bit_length()))/8,
        "ps_scratch_bytes_included_in_pool": 0,
        "ps_tile_write_buffers_bytes_outside_pool": 2048 if args.pcr_ps else 0,
        "memory_inventory_note": "These are selected payload/metadata fields, not the total state budget; use the XML inventory for all buffers, registers and control.",
        "operand_stream_cache_bytes": 2048*args.panel_rows,
        "operand_stationary_cache_bytes": 2048*args.panel_cols,
        "physical_panel_max_rows": args.panel_rows,
        "physical_panel_max_cols": args.panel_cols,
        "pcr_ps": args.pcr_ps,
        "pcr_enable": bool(args.pcr_enable) if args.pcr_ps else False,
        "pcr_fast_enable": bool(args.pcr_fast_enable) if args.pcr_ps else False,
        "c_tile_reorder_bytes": 512,
        "write_packet_queue_bytes": 64,
        "array_shadow_and_active_weight_bytes": 512,
        "storage_scope": "Logical arrays; post-route RAM macros and registers are reported separately",
        "force_raw":bool(args.force_raw),
        "memory_words": args.mem_words,
        "data_width": 8, "weight_width": 8, "input_profile":"INT8 only; WS and IS; INT32 accumulators", "clock_period_ps": 10000,
        "engine": "GEMPACT RTL, external tiling ABI 2 + parameterized testbench + DDR model",
        "hardware_configuration": "physically sized panels and shared PS page pool",
        "verilator_version": subprocess.check_output(["verilator","--version"],text=True).strip(),
        "runtime_platform": "Linux x86_64",
        "compiler": subprocess.check_output([args.cxx,"--version"],text=True).splitlines()[0],
        "verilator_runtime_build":runtime_manifest,
        "sources": {str(p.relative_to(snapshot)):digest(p) for p in sources+sorted(npu.rglob("*.svh"))},
        "adapter_sources": {p.name:digest(p) for p in [
            snapshot_here/"capture.hpp",snapshot_here/"capture.cpp",snapshot_here/"backend.cpp",
            snapshot_here/"server.cpp",snapshot_here/"build_measured_backend.py"]},
        "library_sha256": digest(lib),
        "server_sha256": digest(server),
        "reference_sha256": digest(dest/"rtl_reference") if (dest/"rtl_reference").exists() else None,
    }
    (dest/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(f"Built {dest}")

if __name__ == "__main__":
    main()
