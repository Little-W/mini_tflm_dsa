#!/usr/bin/env python3
"""证明实际快速命中的并行标签资格、填充冲突和完整缓存状态。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex

from run import PARAMETERS, PORTS, NAMES, execute, response_model, prove_caches
from run_valid_mask import model as valid_model
from support import check_sources, digest, prepare_inputs


RAW_PORTS = PORTS.replace(
    "input logic [WAYS-1:0] valid_lookup,",
    "input logic [WAYS-1:0] lookup_valid_unmasked,\n"
    "input logic [1:0] fill_state,\n"
    "input logic [WI-1:0] fill_way,\n"
    "input logic [SI-1:0] fill_set,")
RAW_NAMES = [name for name in NAMES if name != "valid_lookup"] + [
    "lookup_valid_unmasked", "fill_state", "fill_way", "fill_set"]


def make_model(label, source):
    body = response_model(label, source, payload_when_valid=True).replace(PORTS, RAW_PORTS)
    marker = "localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;"
    mask = valid_model(label + "_mask", source)
    expression = mask[mask.index("    for (genvar read_port"):mask.rindex("endmodule")]
    setup = """
localparam logic [1:0] F_IDLE=0;
logic [WAYS-1:0] valid_lookup;
for (genvar metadata_way=0; metadata_way<WAYS; metadata_way++) begin:g_valid_model
    logic [5:0] valid_read_value, valid_active;
    logic [5:0][SI-1:0] valid_match_address;
    assign valid_read_value={6{lookup_valid_unmasked[metadata_way]}};
    for(genvar port=0;port<6;port++) begin:g_read
        assign valid_match_address[port]=lookup_snapshot_set;
    end
""" + expression + "\nassign valid_lookup[metadata_way]=valid_active[0];\nend\n"
    return body.replace(marker, marker + setup)


def prove_responses(out, paths):
    text = "\n".join(make_model(label, path.read_text()) for label, path in paths.items())
    text += f"module comparison #({PARAMETERS})(\n{RAW_PORTS},output logic equivalent);\n"
    text += "logic [READ_WIDTH+3:0] expected,actual;\n"
    connections = ",".join(f".{name}({name})" for name in RAW_NAMES)
    for label, result in (("reference", "expected"), ("current", "actual")):
        text += (f"{label} #(.WAYS(WAYS),.READ_WIDTH(READ_WIDTH),.DEMAND_DEPTH(DEMAND_DEPTH),"
                 f".LB(LB),.SI(SI)) u_{label}({connections},.observed({result}));\n")
    text += "assign equivalent=expected==actual;\nendmodule\n"
    source = out / "response_comparison.sv"
    source.write_text(text)
    profiles = [(1,32,1,4,1), (2,64,1,4,7), (2,64,1,7,4),
                (2,64,4,4,7), (2,64,4,7,4), (3,64,1,5,5),
                (4,128,1,5,7), (3,64,8,5,7), (4,128,8,5,7),
                (2,64,1,4,16), (2,64,1,7,32)]
    results = []
    for ways, width, depth, lb, si in profiles:
        name = f"response_w{ways}_r{width}_d{depth}_l{lb}_s{si}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text(
            f"read_slang --top comparison -GWAYS={ways} -GREAD_WIDTH={width} "
            f"-GDEMAND_DEPTH={depth} -GLB={lb} -GSI={si} " + shlex.quote(str(source)) +
            "\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        execute(script, log, "SUCCESS!")
        results.append(dict(WAYS=ways, READ_WIDTH=width, DEMAND_DEPTH=depth,
                            LB=lb, SI=si, passed=True, log_sha256=digest(log)))
        print("FAST_LOOKUP_RESPONSE_PASS", name, flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", default=["2:1:1:16", "2:2:1:16", "4:2:4:16",
                                                          "2:2:1:128", "16:2:1:128"])
    args = parser.parse_args()
    out = args.out.resolve()
    _, paths, helpers, manifest = prepare_inputs(out, args.reference, args.candidate)
    report = dict(passed=False, inputs=manifest, input_assumptions=[],
                  response_profiles=prove_responses(out, paths), complete_cache_profiles=[])
    for value in args.profiles:
        sets, ways, depth, line_bytes = map(int, value.split(":"))
        report["complete_cache_profiles"] += prove_caches(
            out, paths, helpers, [f"{sets}:{ways}:{depth}"],
            read_width=64, line_bytes=line_bytes, payload_when_valid=True)
    check_sources(manifest)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(out / "summary.json")


if __name__ == "__main__":
    main()
