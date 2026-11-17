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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0,str(ROOT))
from scripts.capacity.config import axi_data_width, selected_config
WARNINGS = [
    "GENUNNAMED", "VARHIDDEN", "WIDTHEXPAND", "UNUSEDSIGNAL", "UNUSED",
    "UNUSEDGENVAR", "UNDRIVEN", "PINMISSING", "STMTDLY", "DECLFILENAME",
    "CASEINCOMPLETE", "EOFNEWLINE", "PROCASSINIT", "SYNCASYNCNET", "COMBDLY",
    "PINCONNECTEMPTY", "WIDTHTRUNC", "ASCRANGE", "INITIALDLY", "BLKSEQ",
    "MULTIDRIVEN", "LATCH",
]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--size", type=int)
    ap.add_argument("--cache", type=int)
    ap.add_argument("--ps", type=int)
    ap.add_argument("--bus-width", type=int, choices=(32,64))
    ap.add_argument("--shared-bank-bytes", type=int, choices=(1024,2048,4096))
    ap.add_argument("--shared-bank-count", type=int, choices=(0,6,7,8,9))
    ap.add_argument("--verilator", default=os.environ.get("VERILATOR","verilator"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--cxx", default="g++-13" if shutil.which("g++-13") else "g++")
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--output-root", type=Path)
    ap.add_argument("--mem-words", type=int, default=131072)
    ap.add_argument("--ps-compress", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--ps-pool-bytes", type=int)
    ap.add_argument("--force-raw", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--print-config", action="store_true")
    args = ap.parse_args()
    selected=selected_config(args.config)
    args.bus_width=axi_data_width(args.bus_width,args.config)
    for field,key in (("size","SIZE"),("cache","IA_CACHE_BLOCKS"),("ps","PS_FRAME_COUNT"),
                      ("shared_bank_bytes","SHARED_BANK_BYTES"),("shared_bank_count","SHARED_BANK_COUNT"),
                      ("ps_pool_bytes","PS_POOL_BYTES"),("ps_compress","PCR_ENGINE"),("force_raw","PS_FORCE_RAW")):
        if getattr(args,field) is None:
            setattr(args,field,selected[key])
    for value in [args.size, args.cache]:
        if value < 2 or value & (value-1):
            ap.error("size and cache must be powers of two >= 2")
    if args.ps < 1:
        ap.error("ps must be positive")
    if args.mem_words < 1 or args.jobs < 1:
        ap.error("memory words and compiler jobs must be positive")
    if args.ps_compress and (args.size != 16 or args.ps_pool_bytes < 64 or args.ps_pool_bytes % 64):
        ap.error("compressed PS requires SIZE=16 and a pool divisible by 64 bytes")
    if args.force_raw and not args.ps_compress:
        ap.error("force-raw requires ps-compress")
    shared_total=(args.shared_bank_count*args.shared_bank_bytes if args.shared_bank_count else
                  args.cache*args.size*args.size*2+args.ps_pool_bytes)
    shared_enabled=bool(args.ps_compress and args.size==16 and
        shared_total%args.shared_bank_bytes==0 and 6<=shared_total//args.shared_bank_bytes<=9)
    effective_pool=shared_total-args.shared_bank_bytes if shared_enabled else args.ps_pool_bytes
    tag = (f"s{args.size}_c{args.cache}_p{args.ps}_axi{args.bus_width}"
           f"_b{args.shared_bank_bytes}n{args.shared_bank_count}")
    if args.ps_compress:
        tag += f"_ps{effective_pool}_raw{int(args.force_raw)}"
    if args.mem_words != 131072:
        tag += f"_mem{args.mem_words}"
    parameters=dict(tag=tag,size=args.size,ia_cache_blocks=args.cache,ps_frame_count=args.ps,
        bus_width=args.bus_width,shared_bank_bytes=args.shared_bank_bytes,
        shared_bank_count=args.shared_bank_count,shared_enabled=shared_enabled,
        shared_physical_banks=shared_total//args.shared_bank_bytes if shared_enabled else 0,
        shared_total_bytes=shared_total if shared_enabled else 0,
        ps_compress=bool(args.ps_compress),ps_pool_bytes=effective_pool if args.ps_compress else 0,
        legacy_ps_pool_bytes=args.ps_pool_bytes,force_raw=bool(args.force_raw),mem_words=args.mem_words)
    if args.print_config:
        print(json.dumps(parameters,indent=2));return
    output_root = args.output_root.resolve() if args.output_root else HERE
    work = output_root / "build" / tag
    dest = output_root / "backends" / tag
    work.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    npu = ROOT / "rtl/npu"
    packages = [npu / "conv/conv_im2col_pkg.sv", npu / "conv/vector_engine_pkg.sv"]
    sources = packages + [p for p in sorted(npu.rglob("*.sv")) if p not in packages] + sorted(npu.rglob("*.v"))
    sources += [ROOT / "rtl/common/pseudo_dual_port_ram.v"]
    sources += [ROOT / "test/dep_modules/ddr_axi_mem_model.sv",
                ROOT / "test/npu_top/tb_npu_top.sv", HERE / "cycle_probe.sv"]
    tracked = sources + sorted(npu.rglob("*.svh"))
    before = {str(p.relative_to(ROOT)): digest(p) for p in tracked}
    flags = [
        "--timing", "--assert", "-sv", "--top-module", "tb_npu_top", "-Wno-fatal",
        f"-I{npu / 'ps_compact'}",
        *[f"-Wno-{warning}" for warning in WARNINGS],
        f"-DTB_SIZE={args.size}", f"-DTB_IA_CACHE_BLOCKS={args.cache}",
        f"-DTB_BUS_WIDTH={args.bus_width}",f"-DTB_SHARED_BANK_BYTES={args.shared_bank_bytes}",
        f"-DTB_SHARED_BANK_COUNT={args.shared_bank_count}",
        f"-DTB_PS_FRAME_COUNT={args.ps}", "-DTB_AXI_READ_OUTSTANDING=4",
        "-DTB_DATA_WIDTH=16", "-DTB_WEIGHT_WIDTH=16",
        f"-DTB_MEM_WORDS={args.mem_words}",
    ]
    if args.ps_compress:
        flags += ["-DGEMPACT_PS_COMPRESS", f"-DGEMMORA_PS_POOL_BYTES={args.ps_pool_bytes}"]
    if args.force_raw:
        flags += ["-DGEMMORA_PS_FORCE_RAW"]
    rules = work / "compile_rules.mk"
    rules.write_text("\n".join([
        "%.o: %.cpp", "\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<",
        "$(VK_OBJS_FAST): %.o: %.cpp", "\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<",
        "$(VK_OBJS_SLOW): %.o: %.cpp", "\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<", ""]))
    env = dict(os.environ, CXX=args.cxx)
    subprocess.run([args.verilator, "--cc", "--prefix", "VNpuPython",
                    "--Mdir", str(work), "--output-groups", "0", "--output-split", "10000",
                    "-CFLAGS", "-std=c++20 -fPIC -O1 --param ggc-min-expand=1 --param ggc-min-heapsize=1024",
                    *flags, *map(str, sources)], env=env, check=True)
    subprocess.run(["make", "-C", str(work), "-f", "VNpuPython.mk",
                    f"-j{args.jobs}", "VNpuPython__ALL.a", f"CXX={args.cxx}",
                    "OPT_FAST=-O1", "OPT_SLOW=-O0", "VM_DEFAULT_RULES=0", "-f", str(rules)], env=env, check=True)
    text = subprocess.check_output([args.verilator, "-V"], text=True)
    verilator_roots = [
        line.split("=", 1)[1].strip() for line in text.splitlines()
        if line.strip().startswith("VERILATOR_ROOT") and line.split("=",1)[1].strip()
    ]
    inc = Path(verilator_roots[-1]) / "include"
    if not (inc/"verilated.h").is_file():
        raise RuntimeError(f"Verilator runtime headers are unavailable: {inc}")
    runtime = [inc / name for name in [
        "verilated.cpp", "verilated_dpi.cpp", "verilated_timing.cpp",
        "verilated_threads.cpp",
    ]]
    lib = dest / "libnpu_model.so"
    subprocess.run([
        args.cxx, "-std=c++20", "-O2", "-fPIC", "-shared", "-pthread",
        "-static-libstdc++", "-static-libgcc", "-Wl,-Bsymbolic",
        "-I"+str(work), "-I"+str(inc), "-I"+str(inc/"vltstd"),
        str(HERE/"backend.cpp"), str(HERE/"capture.cpp"),
        *map(str,runtime), str(work/"VNpuPython__ALL.a"), "-o", str(lib),
    ], check=True)
    server = dest / "rtl_server"
    subprocess.run([
        args.cxx, "-std=c++20", "-O2", "-static", "-pthread",
        f"-DMODEL_SIZE={args.size}",
        "-I"+str(work), "-I"+str(inc), "-I"+str(inc/"vltstd"),
        str(HERE/"backend.cpp"), str(HERE/"capture.cpp"), str(HERE/"server.cpp"),
        *map(str,runtime), str(work/"VNpuPython__ALL.a"), "-latomic",
        "-o", str(server),
    ], check=True)
    if args.reference:
        ref = work / "reference"
        subprocess.run([
            args.verilator, "--binary", "--Mdir", str(ref), "-j", str(args.jobs),
            "-CFLAGS", "-O2", "-LDFLAGS", "-static",
            "-MAKEFLAGS", f"CXX={args.cxx}",
            *flags, *map(str,sources), str(HERE/"capture.cpp"),
            "-o", "rtl_reference",
        ], env=env, check=True)
        shutil.copy2(ref/"rtl_reference", dest/"rtl_reference")
    for binary in [lib,server,dest/"rtl_reference"]:
        if binary.exists():
            subprocess.run(["strip","--strip-unneeded",str(binary)],check=True)
    manifest = {
        **parameters,"schema": 2, "configuration_abi": 2, "external_tiling_required": True,
        "read_outstanding": 4,"scalar_width":64,
        "data_width": 16, "weight_width": 16, "clock_period_ps": 10000,
        "engine": "shared GEMM array with WS, IS and INT16 operands",
        "verilator_version": subprocess.check_output([args.verilator,"--version"],text=True).strip(),
        "runtime_platform": "Linux x86_64",
        "compiler": subprocess.check_output([args.cxx,"--version"],text=True).splitlines()[0],
        "sources": before,
        "adapter_sources": {p.name:digest(p) for p in [
            HERE/"capture.hpp",HERE/"capture.cpp",HERE/"backend.cpp",
            HERE/"server.cpp",HERE/"runtime.py",HERE/"build_backend.py"]},
        "library_sha256": digest(lib),
        "server_sha256": digest(server),
        "reference_sha256": digest(dest/"rtl_reference") if (dest/"rtl_reference").exists() else None,
    }
    if before != {str(p.relative_to(ROOT)): digest(p) for p in tracked}:
        raise RuntimeError("RTL sources changed during backend compilation")
    (dest/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(f"Built {dest}")

if __name__ == "__main__":
    main()
