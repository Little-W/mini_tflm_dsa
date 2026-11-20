#!/usr/bin/env python3
"""综合实际窗口队列、DMA 描述符选择与前端，统计跨模块寄存器路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins, resources
import open_fpga_synth

TOP = "axi_dual_block_dma"
BOUNDARIES = ("axi_linear_block_dma", "conv_read_cache", "conv_next_use_predictor",
              "conv_axi_read_guard", "axi_write_page_guard", "conv_axi_read_mux")
SOURCES = ("rtl/npu/conv/conv_im2col_pkg.sv", "rtl/npu/dma/axi_dual_block_dma.sv",
           "rtl/npu/dma/conv_window_queue.sv", "rtl/npu/conv/conv_im2col_frontend.sv",
           "rtl/npu/dma/axi_linear_block_dma.sv", "rtl/npu/dma/cache/conv_read_cache.sv",
           "rtl/npu/dma/cache/conv_next_use_predictor.sv", "rtl/npu/conv/conv_axi_read_guard.sv",
           "rtl/npu/dma/axi_write_page_guard.sv", "rtl/npu/conv/conv_axi_read_mux.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="16913ce0")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=("reference", "current"), default=["reference", "current"])
    parser.add_argument("--include-cache", action="store_true", help="同时映射完整读取缓存及其存储")
    parser.add_argument("--include-predictor", action="store_true", help="同时映射完整下一次访问预测器")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    included = ({"conv_read_cache"} if args.include_cache else set()) | \
               ({"conv_next_use_predictor"} if args.include_predictor else set())
    boundary_modules = tuple(name for name in BOUNDARIES if name not in included)
    source_names = SOURCES + (("rtl/npu/dma/cache/conv_sdp_ram.sv", "rtl/npu/conv/conv_axi_span_reader.sv")
                              if args.include_cache else ())
    cases = {}
    for label in args.cases:
        folder = out / label
        snapshot = folder / "sources"
        snapshot.mkdir(parents=True, exist_ok=True)
        sources, hashes = [], {}
        for name in source_names:
            data = (subprocess.check_output(["git", "show", f"{args.reference}:{name}"], cwd=ROOT)
                    if label == "reference" else (ROOT / name).read_bytes())
            hashes[name] = hashlib.sha256(data).hexdigest()
            path = snapshot / Path(name).name
            path.write_bytes(data)
            if path.stem in boundary_modules:
                header_end = data.decode().index(");") + 2
                path = snapshot / (path.stem + "_interface.sv")
                path.write_text(data.decode()[:header_end] + "\nendmodule\n")
            sources.append(path)
        helpers = [ROOT / name for name in ("rtl/common/onehot_check.sv", "rtl/common/add_equal.sv",
                                            "rtl/common/add3_equal.sv", "rtl/common/REGFILE.v")]
        sources.extend(helpers)
        for path in helpers:
            hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        import pyosys
        primitive_options, primitive_manifest = open_fpga_synth.primitive_models(
            folder, [str(path) for path in helpers], Path(pyosys.__file__).parent / "share/xilinx")
        mapped, pre_lut, script = folder / "mapped.json", folder / "pre_lut.il", folder / "run.ys"
        script.write_text(f"read_slang --keep-hierarchy --top {TOP} -D XILINX_FPGA -D SYNTHESIS=1 " +
            "-GSIZE=64 -GIM2COL_SIZE=16 -GBUS_WIDTH=64 -GCACHE_BLOCKS=64 -GCONV_CACHE_SETS=128 " +
            primitive_options + " " + " ".join(shlex.quote(str(p)) for p in sources) + "\n" +
            "read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
            "blackbox " + " ".join(name + "*" for name in boundary_modules) + "\n" +
            f"hierarchy -check -top {TOP}\n" +
            f"synth_xilinx -top {TOP} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n" +
            "write_rtlil " + shlex.quote(str(pre_lut)) + "\n" +
            f"synth_xilinx -top {TOP} -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n" +
            "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
        log_path = folder / "synthesis.log"
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        module = json.loads(mapped.read_text())["modules"][TOP]
        usage = resources(module["cells"])
        for name, origin in register_origins(pre_lut).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        boundaries = []
        for name, cell in list(module["cells"].items()):
            if cell["type"] == "$scopeinfo":
                assert not cell["connections"]
                del module["cells"][name]
            elif cell["type"].startswith(boundary_modules):
                boundaries.append(dict(cell=name, type=cell["type"]))
                del module["cells"][name]
        paths = connected_paths(module, limit=30, group_limit=30)
        if not paths["graph_complete"]:
            raise RuntimeError("Incomplete queue/frontend register graph")
        item = dict(scope=("Actual queue, DMA descriptor selection, complete frontend and complete cache" if args.include_cache else
                           "Actual queue, DMA descriptor selection and complete frontend; six surrounding modules are interface boundaries"),
                    cache_included=args.include_cache,
                    predictor_included=args.include_predictor,
                    reference_ref=args.reference, configuration=dict(SIZE=64, IM2COL_SIZE=16, BUS_WIDTH=64,
                    CACHE_BLOCKS=64, CONV_CACHE_SETS=128, LANES=4), source_sha256=hashes,
                    resources=usage, paths=paths, interface_boundaries=boundaries,
                    primitive_models=primitive_manifest,
                    maximum_resident_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                    mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest(),
                    pre_lut_sha256=hashlib.sha256(pre_lut.read_bytes()).hexdigest())
        (folder / "summary.json").write_text(json.dumps(item, indent=2) + "\n")
        cases[label] = item
        print(json.dumps(dict(case=label, resources=usage,
             longest_register_path_cells=paths["longest_register_path_cells"],
             maximum_resident_kib=item["maximum_resident_kib"])), flush=True)
    (out / "summary.json").write_text(json.dumps(cases, indent=2) + "\n")


if __name__ == "__main__":
    main()
