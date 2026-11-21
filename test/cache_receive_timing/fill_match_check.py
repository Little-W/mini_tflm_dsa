#!/usr/bin/env python3
"""证明填充组号匹配状态、完整缓存存储与有效响应逐周期一致。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex

from run import execute, observed_cache, prove_response, restore_valid_storage_names
from support import ROOT, SOURCE, check_sources, digest, prepare_inputs


def observed_model(source, label):
    body = observed_cache(source, label, payload_when_valid=True)
    marker = "  output logic [READ_WIDTH-1:0] formal_saved_payload);"
    assert body.count(marker) == 1
    body = body.replace(marker, "  output logic [READ_WIDTH-1:0] formal_saved_payload,\n"
                        "  output logic formal_fill_match);")
    end = body.index("endmodule", body.index("module conv_windowed_cache"))
    if label == "current":
        relation = """
if (DEMAND_DEPTH == 1) begin:g_formal_fill_match
  assign formal_fill_match = g_saved_fill_match.lookup_fill_set_match_q;
end else begin:g_formal_current_fill_match
  assign formal_fill_match = fill_set == lookup_snapshot_set;
end
"""
    else:
        relation = "\nassign formal_fill_match = fill_set == lookup_snapshot_set;\n"
    return body[:end] + relation + body[end:]


def prove_cache(out, paths, helpers, profile):
    sets, ways, depth, line_bytes = map(int, profile.split(":"))
    name = f"s{sets}_w{ways}_d{depth}_l{line_bytes}"
    commands = []
    for label, path in paths.items():
        model = out / (label + "_observed.sv")
        model.write_text(observed_model(path.read_text(), label))
        commands += [
            "read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top conv_windowed_cache "
            f"-GSETS={sets} -GWAYS={ways} -GDEMAND_DEPTH={depth} -GLINE_BYTES={line_bytes} "
            "-GBUS_WIDTH=64 -GREAD_WIDTH=64 -Gp_defer_retire_shift=1 " +
            shlex.join(map(str, [model] + helpers)),
            "prep -top conv_windowed_cache -flatten", "memory_map", "async2sync", "opt_clean",
        ]
        if label == "current":
            commands += restore_valid_storage_names(sets, ways)
        commands += [f"rename conv_windowed_cache {label}", f"design -stash {label}"]
    commands += [
        "design -copy-from reference -as reference reference",
        "design -copy-from current -as current current",
        "equiv_make reference current equivalent", "hierarchy -top equivalent",
        "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 3", "equiv_status -assert",
    ]
    script, log = out / (name + ".ys"), out / (name + ".log")
    script.write_text("\n".join(commands) + "\n")
    execute(script, log, "Equivalence successfully proven")
    match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log.read_text())
    if match is None or int(match[2]):
        raise RuntimeError("缓存完整状态或匹配关系仍未证明")
    print("CACHE_FILL_MATCH_PASS", name, flush=True)
    return dict(SETS=sets, WAYS=ways, DEMAND_DEPTH=depth, LINE_BYTES=line_bytes,
                BUS_WIDTH=64, READ_WIDTH=64, passed=True,
                equivalent_bits=int(match[1]), log_sha256=digest(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=str(Path(__file__).resolve().parent / "fill_match_reference.sv"))
    parser.add_argument("--candidate", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", default=["2:1:1:16", "2:2:1:16", "4:2:4:16",
                                                          "2:2:1:128", "16:2:1:128"])
    args = parser.parse_args()
    out = args.out.resolve()
    _, paths, helpers, manifest = prepare_inputs(out, args.reference, args.candidate)
    report = dict(passed=False, inputs=manifest, input_assumptions=[],
                  relation="The saved match equals the complete current fill-set/snapshot-set comparison after each clock edge.",
                  response_profiles=prove_response(out, paths, payload_when_valid=True),
                  complete_cache_profiles=[])
    for profile in args.profiles:
        report["complete_cache_profiles"].append(prove_cache(out, paths, helpers, profile))
    check_sources(manifest)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(out / "summary.json")


if __name__ == "__main__":
    main()
