#!/usr/bin/env python3
"""对全部输入证明前端描述符的接收事件和接收字段相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/axi_dual_block_dma.sv")
PORTS = ("tile_valid", "tile_p0", "tile_q0", "tile_rows", "tile_cols", "tile_slot", "tile_group")


def assignment(source, name):
    match = re.search(r"\bassign\s+" + name + r"\s*=\s*(.*?);", source, re.S)
    if match is None:
        raise RuntimeError("Missing assignment: " + name)
    return match.group(1)


def connection(source, name):
    match = re.search(r"\." + name + r"\s*\(", source)
    if match is None:
        raise RuntimeError("Missing connection: " + name)
    start = match.end()
    depth = 1
    for index in range(start, len(source)):
        depth += (source[index] == "(") - (source[index] == ")")
        if depth == 0:
            return source[start:index]
    raise RuntimeError("Incomplete connection: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="151b87d5")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", f"{args.reference_ref}:{SOURCE}"], cwd=ROOT, text=True)
    queue = (ROOT / "rtl/npu/dma/conv_window_queue.sv").read_text()
    expected = reference.replace(
        "    logic accept_read, accept_linear, accept_image, image_start_ready, direct_issue;\n",
        "    logic accept_read, accept_linear, accept_image, image_start_ready, direct_issue;\n"
        "    logic direct_offer, win_payload_select;\n")
    start = current.index("    // 描述符先提供有效标志和字段，就绪信号只参与接收事件。\n")
    end = current.index("    assign rd_error", start)
    expected = re.sub(r"    assign direct_issue\s*=.*?;\n", current[start:end], expected, count=1, flags=re.S)
    for port in PORTS:
        expected = expected.replace("." + port + "(" + connection(reference, port) + ")",
                                    "." + port + "(" + connection(current, port) + ")")
    if expected != current:
        raise RuntimeError("Uncovered changes in DMA source")
    definitions = []
    for name in ("rd_busy", "rd_finish_beat", "image_start_ready", "accept_image", "win_cols_valid"):
        definitions.append(f"wire {name} = {assignment(current, name)};")
    definitions.extend([
        "wire direct_issue_reference = " + assignment(reference, "direct_issue") + ";",
        "wire direct_offer = " + assignment(current, "direct_offer") + ";",
        "wire direct_issue_current = " + assignment(current, "direct_issue") + ";",
        "wire win_payload_select = " + assignment(current, "win_payload_select") + ";",
        "wire window_enable = " + connection(current[current.index("conv_window_queue #"):], "enable") + ";",
    ])
    validity = assignment(queue, "frontend_valid")
    substitutions = {"enable": "window_enable", "configure": "window_configure", "failed": "window_failed",
                     "frontend_error": "fe_error", "active": "window_active", "retire": "window_retire",
                     "count": "window_count"}
    for old, new in substitutions.items():
        validity = re.sub(r"\b" + old + r"\b", new, validity)
    definitions.append("wire win_frontend_valid = " + validity + ";")
    widths = {"tile_valid": "", "tile_p0": "[31:0]", "tile_q0": "[31:0]",
              "tile_rows": "[CONV_RW-1:0]", "tile_cols": "[CONV_RW-1:0]",
              "tile_slot": "[SLOT_W-1:0]", "tile_group": "[31:0]"}
    for port in PORTS:
        for label, source in (("reference", reference), ("current", current)):
            expression = re.sub(r"\bdirect_issue\b", "direct_issue_" + label, connection(source, port))
            definitions.append(f"wire {widths[port]} {label}_{port} = {expression};")
    payload = [port for port in PORTS if port != "tile_valid"]
    model = f"""module descriptor_proof #(
parameter integer IM2COL_SIZE=16, SLOT_W=6, CONV_SUPPORTED=1,
parameter integer REG_WIDTH=32, CONV_RW=$clog2(IM2COL_SIZE+1), COUNT_W=3
) (
input logic rd_start,abort,rd_im2col,conv_cfg_valid,job_conv,linear_finish,conv_done_r,
input logic linear_busy,conv_active,fe_busy,guard_idle,mux_idle,conv_pending,fe_error,fe_tile_ready,
input logic window_active,window_retire,window_configure,window_failed,
input logic [COUNT_W-1:0] window_count,
input logic [31:0] rd_rows_to_read,rd_valid_cols,rd_p0,rd_q0,rd_group,
input logic [31:0] win_frontend_p0,win_frontend_q0,win_frontend_cols,p0_q,q0_q,group_q,
input logic [CONV_RW-1:0] rows_q,cols_q,
input logic [SLOT_W-1:0] rd_slot_id,slot_q,
output logic equivalent
);
wire win_busy = window_count != 0;
{chr(10).join(definitions)}
wire accepted_reference=reference_tile_valid && fe_tile_ready;
wire accepted_current=current_tile_valid && fe_tile_ready;
assign equivalent=direct_issue_reference==direct_issue_current &&
 accepted_reference==accepted_current &&
 (!accepted_current || {{{','.join('reference_'+port for port in payload)}}} ==
                       {{{','.join('current_'+port for port in payload)}}});
endmodule
"""
    model_path = out / "descriptor_proof.sv"
    model_path.write_text(model)
    reports = []
    for size, slots, supported in ((4, 2, 1), (16, 6, 1), (64, 6, 1), (16, 6, 0)):
        folder = out / f"size{size}_slot{slots}_supported{supported}"
        folder.mkdir(exist_ok=True)
        script = folder / "prove.ys"
        script.write_text(f"read_slang --top descriptor_proof -GIM2COL_SIZE={size} -GSLOT_W={slots} "
                          f"-GCONV_SUPPORTED={supported} {shlex.quote(str(model_path))}\n"
                          "prep -top descriptor_proof -flatten\nsat -verify -prove equivalent 1\n")
        log_path = folder / "formal.log"
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Descriptor proof incomplete")
        reports.append(dict(size=size, slot_width=slots, supported=bool(supported), passed=True,
                            log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest()))
    summary = dict(passed=True, reference_ref=args.reference_ref, inputs_constrained=False,
                   property="All descriptor acceptance events and accepted fields; direct_issue preserved",
                   source_sha256=hashlib.sha256(current.encode()).hexdigest(),
                   reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                   queue_sha256=hashlib.sha256(queue.encode()).hexdigest(),
                   model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(), profiles=reports)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
