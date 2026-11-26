#!/usr/bin/env python3
"""对完整生产参数的写回模块进行相同选项的资源和组合路径测量。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/oa_writer.sv")
HELPER = Path("rtl/npu/writeback/oa_writer_compare.sv")
REFERENCE = "016d9854cf0524b04e7a59f6df13a47b630e686b"
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "reference.sv").write_text(read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    (out / "candidate.sv").write_bytes((ROOT / SOURCE).read_bytes())
    (out / "oa_writer_compare.sv").write_bytes((ROOT / HELPER).read_bytes())
    hashes = {str(path): digest(ROOT / path) for path in (SOURCE, HELPER)}
    parameters = dict(VLEN=16, BUS_WIDTH=64, COUNT_WIDTH=29, REG_WIDTH=32)
    options = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] + [f"-G{name}={value}" for name, value in parameters.items()]
    cases = {name: dict(top="oa_writer", sources=[str(out / (name + ".sv"))] +
                       ([str(out / "oa_writer_compare.sv")] if name == "candidate" else []),
                       options=options, configuration="完整生产参数输出写回控制")
             for name in ("reference", "candidate")}
    config = out / "cases.json"
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    with (out / "prepare.log").open("w") as stream:
        subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--case-config", config,
                        "--cases", *cases, "--out", out / "pre", "--through", "pre_lut"],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    def measure(name):
        cost = out / "cost" / name
        with (out / (name + "_map.log")).open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/remap_fpga_luts.py",
                            "--source", out / "pre" / name, "--out", cost, "--mode", "physical-cost",
                            "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
                            "--wire-delay-ps", "300", "--delay-target-ps", "6667",
                            "--discard-abc9-temporaries"], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        metrics = json.loads((cost / "metrics.json").read_text())
        return name, dict(resources=metrics["resources"],
                          longest_register_path_cells=metrics["paths"]["longest_register_path_cells"],
                          longest_paths=metrics["paths"]["register_to_register_paths"][:2],
                          mapped_json_sha256=digest(cost / "mapped.json"),
                          metrics_sha256=digest(cost / "metrics.json"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        measurements = dict(pool.map(measure, cases))
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("测量期间 RTL 内容发生变化")
    result = dict(reference=args.reference, source_sha256=hashes, parameters=parameters,
                  synthesis_defines=["SYNTHESIS=1", "XILINX_FPGA=1"],
                  mapping=dict(mode="physical-cost", max_lut_inputs=8, small_lut_area_cost=1,
                               wire_delay_ps=300, delay_target_ps=6667), cases=measurements)
    (out / "measurement.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({name: dict(lut=value["resources"]["lut_sites_nominal_before_packing"],
                                dsp=value["resources"]["dsp48e1"],
                                depth=value["longest_register_path_cells"])
                      for name, value in measurements.items()}), flush=True)


if __name__ == "__main__":
    main()
