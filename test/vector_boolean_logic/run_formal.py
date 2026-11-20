#!/usr/bin/env python3
"""验证向量前缀、舍入、地址与写回的组合逻辑及寄存周期。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
ENGINE = Path("rtl/npu/conv/vector_engine.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(source):
    return re.sub(r"\s+", "", re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S))


def module(source, name):
    return re.search(r"^module " + name + r"\b.*?^endmodule", source, re.M | re.S)[0]


def execute(folder, commands):
    folder.mkdir(parents=True, exist_ok=True)
    script, log = folder / "run.ys", folder / "formal.log"
    script.write_text("\n".join(commands) + "\n")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)
    text = log.read_text()
    if "Equivalence successfully proven" not in text and "SUCCESS!" not in text:
        raise RuntimeError(f"形式检查未完成：{log}")
    return {"passed": True, "script_sha256": digest(script.read_bytes()),
            "log_sha256": digest(log.read_bytes())}


def compare(folder, top, reference, current, models, options=""):
    commands = []
    for label, source in (("reference", reference), ("current", current)):
        sources = " ".join(shlex.quote(str(p)) for p in (source, models))
        commands += [f"read_slang --top {top} -D SYNTHESIS=1 -D XILINX_FPGA=1 "
                     f"-D YOSYS=1 -D VERIFIC=1 {options} {sources}",
                     f"prep -top {top} -flatten", "memory_map", "async2sync", "opt -full",
                     f"rename {top} {label}", f"design -stash {label}"]
    commands += ["design -copy-from reference -as reference reference",
                 "design -copy-from current -as current current",
                 "equiv_make reference current comparison", "hierarchy -top comparison",
                 "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2",
                 "equiv_status -assert"]
    return execute(folder, commands)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="653477ed")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip()
    paths = [ENGINE, Path("rtl/npu/conv/vector_round_shift.sv"),
             Path("rtl/npu/conv/vector_writeback.sv")]
    references, currents, source_hashes = {}, {}, {}
    for path in paths:
        references[path] = read_rtl_source(f"{revision}:{path}", cwd=ROOT, text=True)
        currents[path] = (ROOT / path).read_text()
        source_hashes[str(path)] = digest(currents[path].encode())
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    library_source = library.read_text()
    models = out / "models.sv"
    models.write_text("\n\n".join(re.sub(r"\bspecify\b.*?\bendspecify\b", "", module(library_source, name), flags=re.S)
                                for name in ("LUT6", "LUT6_2", "DSP48E1")) + "\n")
    report = {"reference_commit": revision, "source_sha256": source_hashes,
              "inputs_constrained": False, "primitive_library_sha256": digest(library.read_bytes()), "checks": []}
    offset_tools = runpy.run_path(str(ROOT / "test/vector_offset_clamp/run.py"))
    current_parts = offset_tools["extract"](currents[ENGINE])
    reference_parts = offset_tools["extract"](references[ENGINE])
    restored = currents[ENGINE]
    for current, reference in zip(current_parts, reference_parts):
        restored = restored.replace(current, reference, 1)
    restored = restored.replace(module(currents[ENGINE], "vector_read_address_add"),
                                module(references[ENGINE], "vector_read_address_add"), 1)
    if normalized(restored) != normalized(references[ENGINE]):
        raise RuntimeError("向量引擎存在未包含在本检查中的修改")
    proof = out / "offset.sv"
    proof.write_text(offset_tools["unit"]("current_offset", current_parts) +
                     offset_tools["unit"]("reference_offset", reference_parts) + """
module offset_proof(input logic signed [63:0] q_rounded,
input vector_engine_pkg::vector_engine_cfg_t c, output logic equivalent);
logic [33:0] current_observed, reference_observed;
current_offset u_current(.*,.observed(current_observed));
reference_offset u_reference(.*,.observed(reference_observed));
assign equivalent = current_observed == reference_observed;
endmodule
""")
    packages = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/npu/conv/vector_engine_pkg.sv"]
    sources = " ".join(shlex.quote(str(p)) for p in (*packages, proof, models))
    item = execute(out / "offset", [f"read_slang --top offset_proof -D SYNTHESIS=1 -D XILINX_FPGA=1 -D YOSYS=1 -D VERIFIC=1 {sources}",
                   "prep -top offset_proof -flatten", "sat -verify -prove equivalent 1 -show-inputs -show-outputs"])
    item.update(module="output_offset", input_bits=160, output_bits=34)
    report["checks"].append(item)
    for top, path, profiles in (
        ("vector_round_shift", paths[1], ["-GREGISTER_MIDDLE=0", "-GREGISTER_MIDDLE=1"]),
        ("vector_writeback", paths[2], [f"-GTILE={tile} -GBUS_WIDTH={bus}" for tile, bus in ((8,32),(16,32),(16,64),(16,128),(32,64))]),
        ("vector_read_address_add", ENGINE, ["-Gp_use_dsp=0", "-Gp_use_dsp=1"]),
    ):
        reference, current = out / (top + "_reference.sv"), out / (top + "_current.sv")
        reference.write_text(module(references[path], top) + "\n")
        current.write_text(module(currents[path], top) + "\n")
        for index, options in enumerate(profiles):
            item = compare(out / f"{top}_{index}", top, reference, current, models, options)
            item.update(module=top, parameters=options)
            report["checks"].append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)
    if source_hashes != {str(path): digest((ROOT / path).read_bytes()) for path in paths}:
        raise RuntimeError("验证期间源码发生变化")
    report["passed"] = True
    report["engine_other_logic_unchanged"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}), flush=True)


if __name__ == "__main__":
    main()
