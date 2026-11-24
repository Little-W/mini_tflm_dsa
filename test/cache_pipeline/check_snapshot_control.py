#!/usr/bin/env python3
"""比较快照更新后的请求接收、读取就绪与返回名额资格。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from check_response_selection import ROOT, SOURCE, assignment, digest, run
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
METADATA_SOURCE = Path("rtl/npu/dma/cache/conv_cache_metadata_way.sv")


def support(source: str) -> str:
    result = ""
    for name in ("conv_cache_request_qualification", "conv_cache_work_lookup",
                 "conv_cache_snapshot_response", "conv_cache_metadata_eligibility",
                 "conv_cache_metadata_rank_hit", "conv_cache_select_busy",
                 "conv_cache_lookup_hit", "conv_cache_demand_hit"):
        start = source.index("module " + name)
        result += source[start:source.index("endmodule", start)+len("endmodule")] + "\n"
    return result


def model(name: str, source: str, unit: str) -> tuple[str, int]:
    if unit == "fire":
        names = ("work_valid", "work_capacity_ready", "bypass_q", "lookup_snapshot_valid",
                 "work_snapshot_matches_q", "work_lookup_ready")
        start = source.index("  always_comb begin\n    work_snapshot_ready =")
        end = source.index("  assign request_push", start)
        body = source[start:end]
        declarations = "logic work_snapshot_ready,work_ready,req_fire;"
        observed = "req_fire"
    elif unit == "lookup":
        names = ("lookup_snapshot_valid", "bypass_q", "set_match", "work_word_matches_q",
                 "work_snapshot_matches_q")
        if "conv_cache_work_lookup u_work_lookup" in source:
            start = source.index("  conv_cache_work_lookup u_work_lookup")
            body = source[start:source.index("  );", start)+5]
        else:
            body = assignment(source, "work_lookup_ready")
        body = body.replace("lookup_snapshot_set == demand_fill_set", "set_match")
        declarations = "logic work_lookup_ready;"
        observed = "work_lookup_ready"
    elif unit == "demand_lookup":
        names = ("lookup_snapshot_valid", "set_match", "demand_word_matches_q")
        if "conv_cache_metadata_eligibility u_demand_lookup" in source:
            start = source.index("  conv_cache_metadata_eligibility u_demand_lookup")
            body = source[start:source.index("  );", start)+5]
        else:
            body = assignment(source, "demand_lookup_ready")
        body = body.replace("lookup_snapshot_set == (bypass_q ? demand_fill_set : demand_set)", "set_match")
        declarations = "logic demand_lookup_ready;"
        observed = "demand_lookup_ready"
    elif unit == "hit":
        names = ("bypass_q", "is_miss", "demand_filled", "demand_lookup_ready", "work_lookup_ready",
                 "work_hit0", "work_hit1", "demand_hit0", "demand_hit1")
        if "conv_cache_lookup_hit #(.p_ways(WAYS)) u_lookup_hit" in source:
            start = source.index("  conv_cache_lookup_hit #(.p_ways(WAYS)) u_lookup_hit")
            body = source[start:source.index("  );", start)+5]
        else:
            body = assignment(source, "lookup_hit")
        body = body.replace("fg_state == FG_MISS", "is_miss").replace("fg_state != FG_MISS", "!is_miss")
        declarations = """localparam integer WAYS=2;
  logic [WAYS-1:0] work_tag_hits,demand_tag_hits;
  logic lookup_hit;
  assign work_tag_hits={work_hit1,work_hit0};
  assign demand_tag_hits={demand_hit1,demand_hit0};
"""
        observed = "lookup_hit"
    elif unit in ("prefetch_busy", "demand_busy"):
        names = ("select_hint_busy", "req_fire", "select_request_set_match", "lookup_hit")
        signal = "select_prefetch_blocked" if unit == "prefetch_busy" else "select_demand_blocked"
        instance = "u_prefetch_busy" if unit == "prefetch_busy" else "u_demand_busy"
        marker = source.find(instance + " (")
        if marker >= 0:
            start = source.rfind("  conv_cache_select_busy", 0, marker)
            body = source[start:source.index("  );", start)+5]
        else:
            body = assignment(source, signal)
        declarations = "logic " + signal + ";"
        observed = signal
    elif unit == "rank":
        names = ("i_metadata_enable", "i_metadata_hit", "i_hit_selected", "i_windowed", "i_hint_valid")
        if "conv_cache_metadata_rank_hit u_rank_hit" in source:
            start = source.index("    conv_cache_metadata_rank_hit u_rank_hit")
            body = source[start:source.index("    );", start)+7]
            body += "\n" + assignment(source, "rank_source_i_hit_valid")
        else:
            body = assignment(source, "hit_update") + "\n" + assignment(source, "rank_source_i_hit_valid")
        declarations = "logic hit_update,rank_hit_update,rank_source_i_hit_valid;"
        observed = "rank_source_i_hit_valid"
    elif unit == "ready":
        names = ("cfg_allowed", "outstanding_count", "windowed_q", "rsp_ready",
                 "saved_response", "fast_control", "lookup_snapshot_valid",
                 "work_snapshot_matches_q", "work_range", "hit0", "hit1")
        if "begin : g_direct_request_ready" in source:
            start = source.index("    logic enabled, saved_ready, fast_ready;")
            body = source[start:source.index("  end else begin : g_queued_request_ready", start)]
        else:
            body = assignment(source, "req_ready")
        body = body.replace("configured && !clearing && !cfg_valid", "cfg_allowed")
        body = body.replace("(response_count != 0 || fg_state == FG_RESP)", "saved_response")
        body = body.replace("g_direct_response_lookup.fast_response_conditions[0]", "fast_control")
        declarations = """localparam integer WAYS=2,DQ_CW=1,DEMAND_DEPTH=1;
  logic [WAYS-1:0] work_tag_hits;
  logic req_ready,rsp_valid,consumed_response;
  assign work_tag_hits={hit1,hit0};
  assign rsp_valid=saved_response ||
      (fast_control && lookup_snapshot_valid && work_snapshot_matches_q && work_range && (|work_tag_hits));
  assign consumed_response=rsp_valid&&rsp_ready;
"""
        observed = "req_ready"
    else:
        raise ValueError(unit)
    width = len(names)
    return f"""module {name}(input logic [{width-1}:0] stimulus,output logic observed);
  logic {','.join(names)};
  assign {{{','.join(names)}}}=stimulus;
  {declarations}
{body}
  assign observed={observed};
endmodule
""", width


def bench(width: int) -> str:
    return f"""module tb;
  localparam integer W={width};
  logic [W-1:0] stimulus;
  logic expected,actual;
  integer checks=0;
  reference u_reference(.*,.observed(expected));
  candidate u_candidate(.*,.observed(actual));
  function automatic logic value(input integer index);
    case(index)
      0:value=1'b0;
      1:value=1'b1;
      2:value=1'bx;
      3:value=1'bz;
    endcase
  endfunction
  initial begin
    for(integer controls=0;controls<(1<<(2*W));controls++) begin
      for(integer bit_index=0;bit_index<W;bit_index++)
        stimulus[bit_index]=value((controls>>(2*bit_index))&3);
      #1;
      if(expected!==actual)
        $fatal(1,"SNAPSHOT_CONTROL_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
      checks++;
    end
    $display("SNAPSHOT_CONTROL_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="f1910d02")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (root / SOURCE).read_text()
    metadata = (root / METADATA_SOURCE).read_text()
    original = ((args.reference_root.resolve() / SOURCE).read_text() if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, SOURCE, text=True))
    original_metadata = ((args.reference_root.resolve() / METADATA_SOURCE).read_text() if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, METADATA_SOURCE, text=True))
    profiles = []
    for unit in ("fire", "lookup", "demand_lookup", "hit", "prefetch_busy", "demand_busy", "rank", "ready"):
        folder = out / unit
        folder.mkdir(exist_ok=True)
        reference, width = model("reference", original_metadata if unit == "rank" else original, unit)
        candidate, current_width = model("candidate", metadata if unit == "rank" else current, unit)
        if width != current_width:
            raise RuntimeError("资格检查输入数量发生变化")
        modules = reference + candidate + support(current + "\n" + metadata)
        proof = folder / "comparison.sv"
        proof.write_text(modules + f"""module comparison(input logic [{width-1}:0] stimulus,output logic equivalent);
  logic expected,actual;
  reference u_reference(.*,.observed(expected));
  candidate u_candidate(.*,.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
        script, log = folder / "comparison.ys", folder / "comparison.log"
        script.write_text("read_slang --top comparison -DSYNTHESIS=1 " + shlex.quote(str(proof)) +
            "\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("快照控制的证明未完成")
        four = folder / "four_state.sv"
        four.write_text(modules + bench(width))
        run(["iverilog", "-g2012", "-s", "tb", "-o", folder / "four_state.vvp", four],
            folder / "four_state_compile.log", root)
        run(["vvp", folder / "four_state.vvp"], folder / "four_state.log", root)
        matched = re.search(r"SNAPSHOT_CONTROL_FOUR_STATE_PASS checks=(\d+)",
                            (folder / "four_state.log").read_text())
        if not matched or int(matched[1]) != 4**width:
            raise RuntimeError("快照控制的四态检查数量不符")
        profiles.append(dict(name=unit,passed=True,input_bits=width,four_state_cases=int(matched[1]),
            proof_sha256=digest(proof),sat_log_sha256=digest(log),
            four_state_log_sha256=digest(folder / "four_state.log")))
    if current != (root / SOURCE).read_text() or metadata != (root / METADATA_SOURCE).read_text():
        raise RuntimeError("快照控制检查期间生产源码发生变化")
    result = dict(passed=True,actual_rtl_expressions=True,external_operands_constrained=False,
        scope="请求接收和查询匹配的全部一位输入；返回名额检查包含自由状态译码结果",
        source_sha256=digest(root / SOURCE),reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        metadata_source_sha256=digest(root / METADATA_SOURCE),
        metadata_reference_sha256=hashlib.sha256(original_metadata.encode()).hexdigest(),profiles=profiles)
    (out / "summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
