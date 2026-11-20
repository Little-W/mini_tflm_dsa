#!/usr/bin/env python3
"""通过实际 NPU 连接测量前端状态到 IA 写端口的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
import open_fpga_synth
from netlist_metrics import connected_paths, register_origins, resources

SOURCE = "rtl/npu/loaders/ia_loader_cache_mgr.sv"
BOUNDARIES = ("vector_engine", "compute_core", "vec_requant", "vec_s8_to_fifo", "vec_s16_to_fifo",
              "oa_writer", "ia_ps_shared_ram", "ia_ps_channel_ram")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="47e51eff")
    parser.add_argument("--cases", nargs="+", choices=("reference", "current"),
                        default=("reference", "current"))
    parser.add_argument("--lock-file", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import fcntl
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        results = {}
        for label in args.cases:
            folder = out / label
            folder.mkdir(exist_ok=True)
            snapshot = folder / "sources"
            source_paths, source_hashes = [], {}
            case = open_fpga_synth.CASES["npu_top"]
            for name in case["sources"]:
                data = ((ROOT / name).read_bytes() if label == "current" and name == SOURCE else
                        read_rtl_source(args.reference + ":" + name, cwd=ROOT))
                path = snapshot / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                source_paths.append(path)
                source_hashes[name] = hashlib.sha256(data).hexdigest()
            import pyosys
            primitive_options, primitive_info = open_fpga_synth.primitive_models(
                folder, [str(path) for path in source_paths], Path(pyosys.__file__).parent / "share/xilinx")
            mapped, pre_lut, script = folder / "mapped.json", folder / "pre_lut.il", folder / "run.ys"
            script.write_text("read_slang --keep-hierarchy --top npu_top -I " +
                shlex.quote(str(ROOT / "include")) + " -I " +
                shlex.quote(str(ROOT / "rtl/npu/ps_compact")) + " " + primitive_options + " " +
                " ".join(map(shlex.quote, case["options"])) + " " +
                " ".join(shlex.quote(str(path)) for path in source_paths) + "\n" +
                "read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
                "read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n" +
                "blackbox " + " ".join(name + "*" for name in BOUNDARIES) + "\n" +
                "hierarchy -check -top npu_top\n" +
                "synth_xilinx -top npu_top -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n" +
                "write_rtlil " + shlex.quote(str(pre_lut)) + "\n" +
                "synth_xilinx -top npu_top -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n" +
                "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
            with (folder / "synthesis.log").open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            module = json.loads(mapped.read_text())["modules"]["npu_top"]
            usage = resources(module["cells"])
            for name, origin in register_origins(pre_lut).items():
                if name in module["cells"]:
                    module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
            removed = []
            for name, cell in list(module["cells"].items()):
                if cell["type"] == "$scopeinfo" or cell["type"].startswith(BOUNDARIES):
                    removed.append(dict(cell=name, type=cell["type"]))
                    del module["cells"][name]
            queries = {
                "frontend_state_to_ia_write_data": (r"u_frontend\.state(?: |$)", r"u_ia_loader\.u_cache_mgr\.ram_port_wr_data "),
                "frontend_state4_to_ia_write_data": (r"u_frontend\.state \[4\]$", r"u_ia_loader\.u_cache_mgr\.ram_port_wr_data "),
                "frontend_to_ia_write_data": (r"u_frontend\.", r"u_ia_loader\.u_cache_mgr\.ram_port_wr_data "),
                "frontend_to_ia_write_mask": (r"u_frontend\.", r"u_ia_loader\.u_cache_mgr\.ram_port_wr_mask "),
                "frontend_to_ia_write_en": (r"u_frontend\.", r"u_ia_loader\.u_cache_mgr\.ram_port_wr_en "),
            }
            paths = {}
            for name, (start, end) in queries.items():
                a, b = re.compile(start), re.compile(end)
                paths[name] = connected_paths(module, limit=4, group_limit=4,
                    root_filter=lambda n,c,p: bool(a.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                    sink_filter=lambda n,c,p: p == "D" and bool(b.search(
                        c.get("attributes", {}).get("fpga_register_origin", ""))))
                if not paths[name]["graph_complete"]:
                    raise RuntimeError("Actual NPU connectivity graph is incomplete")
            report = dict(reference_ref=args.reference, source_sha256=source_hashes,
                          isolated_changed_source=SOURCE, resources=usage, paths=paths,
                          interface_boundaries=removed, primitive_models=primitive_info,
                          mapped_sha256=digest(mapped), pre_lut_sha256=digest(pre_lut))
            (folder / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
            results[label] = report
            print(json.dumps(dict(case=label, logic_luts=usage["logic_lut_cells"],
                paths={name: item["longest_register_path_cells"] for name,item in paths.items()})), flush=True)
        (out / "summary.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
