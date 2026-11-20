#!/usr/bin/env python3
"""证明实际 DMA 与窗口队列对描述符来源的互斥控制。"""
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
DMA = "rtl/npu/dma/axi_dual_block_dma.sv"
QUEUE = "rtl/npu/dma/conv_window_queue.sv"
PACKAGE = "rtl/npu/conv/conv_im2col_pkg.sv"
BOUNDARIES = {
    "axi_linear_block_dma": "rtl/npu/dma/axi_linear_block_dma.sv",
    "conv_im2col_frontend": "rtl/npu/conv/conv_im2col_frontend.sv",
    "conv_axi_read_guard": "rtl/npu/conv/conv_axi_read_guard.sv",
    "axi_write_page_guard": "rtl/npu/dma/axi_write_page_guard.sv",
    "conv_axi_read_mux": "rtl/npu/conv/conv_axi_read_mux.sv",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def code(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="437a8d81")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depths", nargs="+", type=int, default=[2, 3, 4, 7, 8])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / DMA).read_bytes()
    previous = read_rtl_source(args.reference + ":" + DMA, cwd=ROOT)
    restored = current.decode().replace("assign win_payload_select=win_busy;",
                                       "assign win_payload_select=win_busy && !conv_pending;", 1)
    if code(restored) != code(previous.decode()):
        raise RuntimeError("DMA changes outside the verified selector expression")
    if read_rtl_source(args.reference + ":" + QUEUE, cwd=ROOT) != (ROOT / QUEUE).read_bytes():
        raise RuntimeError("Queue source differs from the reference")
    body = current.decode().replace("    output logic wr_error\n", "    output logic wr_error,\n    output logic equivalent\n", 1)
    if "output logic equivalent" not in body:
        raise RuntimeError("DMA declaration not found")
    proof = """
    logic initialized = 1'b0;
    always_ff @(posedge clk) if (!rst_n) initialized <= 1'b1;
    // 任意外部返回和请求均可变化；归纳同时保持队列计数范围和来源互斥。
    assign equivalent = !initialized ||
        ((u_window_queue.count <= $clog2(WINDOW_OUTSTANDING+1)'(WINDOW_OUTSTANDING)) &&
         !(conv_pending && win_busy) &&
         (win_payload_select == (win_busy && !conv_pending)));
"""
    body = body[:body.rindex("endmodule")] + proof + "endmodule\n"
    sources = []
    hashes = {}
    for name in (PACKAGE, QUEUE):
        data = (ROOT / name).read_bytes()
        path = out / Path(name).name
        path.write_bytes(data)
        sources.append(path)
        hashes[name] = digest(data)
    path = out / "axi_dual_block_dma.sv"
    path.write_text(body)
    sources.append(path)
    hashes[DMA] = digest(current)
    boundary_hashes = {}
    for module, name in BOUNDARIES.items():
        data = (ROOT / name).read_text()
        path = out / (module + "_interface.sv")
        path.write_text(data[:data.index(");") + 2] + "\nendmodule\n")
        sources.append(path)
        boundary_hashes[name] = digest((ROOT / name).read_bytes())
    report = dict(reference_ref=args.reference, source_sha256=hashes,
                  reference_sha256={name: digest(read_rtl_source(args.reference + ":" + name, cwd=ROOT)) for name in hashes},
                  source_change="window payload selector",
                  initial_reset=True, inputs_constrained_after_reset=False,
                  interface_boundaries=boundary_hashes, cases=[])
    for depth in args.depths:
        folder = out / f"depth{depth}"
        folder.mkdir(exist_ok=True)
        script, log = folder / "run.ys", folder / "formal.log"
        formal_json = folder / "formal.json"
        script.write_text(
            "read_slang --top axi_dual_block_dma -D SYNTHESIS=1 "
            "-GSIZE=64 -GIM2COL_SIZE=16 -GBUS_WIDTH=64 -GCACHE_BLOCKS=64 "
            f"-GWINDOW_OUTSTANDING={depth} " + " ".join(shlex.quote(str(p)) for p in sources) + "\n" +
            "prep -top axi_dual_block_dma -flatten\nasync2sync\nmemory_map\n" +
            "setundef -undriven -anyseq\nopt_clean\nwrite_json " + shlex.quote(str(formal_json)) + "\n" +
            "sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 "
            "-show-inputs -show-outputs -maxsteps 8\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        content = log.read_text()
        if "Induction step proven: SUCCESS!" not in content:
            raise RuntimeError("Induction incomplete")
        cells = json.loads(formal_json.read_text())["modules"]["axi_dual_block_dma"]["cells"]
        arbitrary_bits = sum(len(cell["connections"]["Y"]) for cell in cells.values()
                             if cell["type"] == "$anyseq")
        if arbitrary_bits == 0:
            raise RuntimeError("Boundary outputs must remain arbitrary")
        item = dict(depth=depth, passed=True, log_sha256=digest(log.read_bytes()),
                    arbitrary_boundary_bits=arbitrary_bits, formal_json_sha256=digest(formal_json.read_bytes()),
                    induction_steps=int(re.findall(r"\[induction step (\d+)\]", content)[-1]))
        report["cases"].append(item)
        print(json.dumps(item), flush=True)
    if any(digest((ROOT / name).read_bytes()) != value for name, value in hashes.items()):
        raise RuntimeError("RTL changed during verification")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
