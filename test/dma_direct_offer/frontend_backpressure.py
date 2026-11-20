#!/usr/bin/env python3
"""在前端未就绪周期改变描述符，比较公开输出和功能状态。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "test/conv_frontend"
SOURCE = ROOT / "rtl/npu/conv/conv_im2col_frontend.sv"


def append_fast_job(path):
    model = runpy.run_path(str(TEST_ROOT / "model/conv_model.py"))
    cfg = model["Config"](8, 8, 16, 1, 1, 8, 8, offset=37)
    values = [(index * 17) % 256 - 128 for index in range(cfg.h * cfg.w * cfg.cin)]
    tiles = [model["Tile"](0, 0, 1, index % 8) for index in range(64)]
    fields = [cfg.base, cfg.h, cfg.w, cfg.cin, cfg.group_c, cfg.go, cfg.kh, cfg.kw, cfg.oh, cfg.ow,
              cfg.sh, cfg.sw, cfg.dh, cfg.dw, cfg.pt, cfg.pl, cfg.offset, int(cfg.s16), 0, 0, len(tiles), cfg.nbytes]
    original = path.read_text().splitlines()
    original[0] = str(int(original[0]) + 1)
    original.append(" ".join(map(str, fields)))
    original.append(" ".join(f"{byte:02x}" for byte in model["Memory"](cfg, values).data))
    for tile in tiles:
        original.append(f"{tile.p0} {tile.q0} {tile.rows} {tile.slot}")
        original.extend(" ".join(map(str, row)) for row in model["direct_im2col"](cfg, values, tile, 16))
    path.write_text("\n".join(original) + "\n")


def inject(source, resident_context=False):
    match = re.search(r"conv_im2col_frontend\s+#\(.*?\)\s+dut\s*\(.*?\);", source, re.S)
    original = match.group(0)
    changed = original
    defaults = {"tile_valid": "tile_valid", "tile_p0": "tile_p0", "tile_q0": "tile_q0",
                "tile_rows": "tile_rows", "tile_cols": "0", "tile_slot": "tile_slot", "tile_group": "0"}
    random_values = {"tile_p0": "(noise[1] ? {27'd0,noise[6:2]} : noise)",
                     "tile_q0": "(noise[1] ? 32'd0 : ~noise)",
                     "tile_rows": "noise", "tile_cols": "noise>>8", "tile_slot": "noise>>16",
                     "tile_group": "(noise[1] ? 32'd0 : noise)"}
    if resident_context:
        random_values.update(tile_p0="(noise[1] ? dut.p0 : noise)",
                             tile_q0="(noise[1] ? dut.q0 : ~noise)",
                             tile_rows="(noise[1] ? 32'd1 : noise)")
    for name, default in defaults.items():
        explicit = re.search(r"\." + name + r"\s*\(([^)]*)\)", original)
        implicit = re.search(r"\." + name + r"(?=\s*[,\)])", original)
        old = explicit.group(1) if explicit else default
        if name == "tile_valid":
            expression = "(" + old + ") || !tile_ready"
        else:
            expression = f"tile_ready ? ({old}) : $bits(dut.{name})'({random_values[name]})"
        replacement = "." + name + "(" + expression + ")"
        if explicit:
            changed = re.sub(r"\." + name + r"\s*\([^)]*\)", replacement, changed)
        elif implicit:
            changed = re.sub(r"\." + name + r"(?=\s*[,\)])", replacement, changed)
        else:
            position = changed.rindex(");")
            changed = changed[:position].rstrip() + "," + replacement + "\n" + changed[position:]
    states = ("state", "configured", "error", "tile_error", "p0", "q0", "row_idx", "col_idx",
              "rows_q", "cols_q", "slot_q", "ix", "iy", "addr", "request_pending")
    check = "{" + ",".join("dut." + name for name in states) + "} !== {" + \
            ",".join("u_reference." + name for name in states) + "}"
    monitor = f"""
logic [31:0] noise=32'hcafef123;
integer blocked_offers=0,blocked_fast_contexts=0;
always @(negedge clk) noise <= {{noise[30:0],noise[31]^noise[21]^noise[1]^noise[0]}};
always @(posedge clk) begin
  if(rst_n && !tile_ready) begin
    blocked_offers=blocked_offers+1;
    if(dut.incoming_context) blocked_fast_contexts=blocked_fast_contexts+1;
  end
  #1;
  if(rst_n && ({check})) $fatal(1,"Unaccepted descriptor changed functional state");
end
final begin
  if(blocked_offers==0) $fatal(1,"No backpressure cycles observed");
  $display("FRONTEND_BACKPRESSURE_PASS blocked_offers=%0d blocked_fast_contexts=%0d",blocked_offers,blocked_fast_contexts);
end
"""
    return source[:match.start()] + changed + monitor + source[match.end():]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--cases", nargs="+", choices=("numeric", "window", "control"),
                        default=["numeric", "window", "control"])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location("compare_frontend", TEST_ROOT / "tools/compare_frontend.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    common = [Path(path) for path in runpy.run_path(str(TEST_ROOT / "tools/run_rtl.py"))["FILES"]
              if not str(path).startswith("tests/")]
    reference = out / "reference_frontend.sv"
    reference.write_text(SOURCE.read_text().replace("module conv_im2col_frontend", "module reference_conv_im2col_frontend", 1))
    reports = []
    for name, window in (("numeric", 0), ("window", 1), ("control", 0)):
        if name not in args.cases:
            continue
        folder = out / name
        folder.mkdir(exist_ok=True)
        control = name == "control"
        top = "tb_conv_control" if control else "tb_conv_im2col_frontend"
        original = (TEST_ROOT / "tests" / (top + ".sv")).read_text()
        if not control:
            original = helper.widen_memory(original)
        bench = folder / (top + ".sv")
        bench.write_text(inject(helper.compare_bench(original), resident_context=bool(window)))
        sources = [*common, reference, bench]
        hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        parameters = [] if control else ["-GSIZE=16", "-GLANES=4", "-GBUS_WIDTH=64", "-GCACHE_SETS=16",
                                          f"-GWINDOWED=1'b{window}", f"-GPREFETCH=1'b{window}"]
        command = [args.verilator, "--binary", "--timing", "--assert", "-DNPU_SIM_ASSERT", "-DCONV_ASSERT",
                   "-Wno-fatal", "--top-module", top, "--Mdir", str(folder / "obj"), "-j", "2",
                   "--output-groups", "0", "--output-split", "12000", "-CFLAGS", "-std=c++20 -O1",
                   "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E",
                   *parameters, *map(str, sources)]
        with (folder / "build.log").open("w") as log:
            subprocess.run(command, cwd=TEST_ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        helper.reviewed_warnings(folder / "build.log")
        command = [str(folder / "obj" / ("V" + top))]
        if not control:
            vectors = folder / "vectors.txt"
            subprocess.run([sys.executable, str(TEST_ROOT / "tests/gen_rtl_vectors.py"), "--size", "16",
                            "--out", str(vectors)], cwd=TEST_ROOT, check=True, capture_output=True)
            if window:
                append_fast_job(vectors)
            command.append("+VECTORS=" + str(vectors))
        run = subprocess.run(command, cwd=TEST_ROOT, capture_output=True, text=True, check=True)
        (folder / "run.log").write_text(run.stdout + run.stderr)
        marker = "RTL_CONTROL_PASS" if control else "RTL_FRONTEND_PASS"
        if not all(item in run.stdout for item in (marker, "FRONTEND_COMPARE_PASS", "FRONTEND_BACKPRESSURE_PASS")):
            raise RuntimeError("Incomplete backpressure test")
        if any(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != before for path, before in hashes.items()):
            raise RuntimeError("Sources changed during backpressure test")
        result = dict(case=name, passed=True, source_sha256=hashes,
            summary=[line for line in run.stdout.splitlines() if line.startswith(
                     ("RTL_FRONTEND_PASS", "RTL_CONTROL_PASS", "FRONTEND_COMPARE_PASS", "FRONTEND_BACKPRESSURE_PASS"))],
            log_sha256=hashlib.sha256((folder / "run.log").read_bytes()).hexdigest())
        if not control:
            result["vectors_sha256"] = hashlib.sha256(vectors.read_bytes()).hexdigest()
        if window and not re.search(r"blocked_fast_contexts=[1-9][0-9]*", run.stdout):
            raise RuntimeError("No fast descriptor context observed under backpressure")
        reports.append(result)
        print(json.dumps(dict(case=name, passed=True, summary=result["summary"])), flush=True)
        for path in (folder / "obj").iterdir():
            if path.suffix in (".o", ".gch"):
                path.unlink()
    report = dict(passed=True, public_outputs=19, functional_states=16, runs=reports)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
