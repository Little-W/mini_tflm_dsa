#!/usr/bin/env python3
"""Declared-storage and operation audit of the current geometry cache RTL.

Counts are logical source bits and expression sites, not mapped area, timing,
memory macro allocation or power.  Production RTL is read only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = ["rtl/npu/dma/cache/conv_read_cache.sv", "rtl/npu/dma/cache/conv_next_use_predictor.sv",
           "rtl/npu/conv/conv_im2col_frontend.sv", "rtl/npu/dma/cache/conv_sdp_ram.sv",
           "rtl/npu/conv/conv_axi_span_reader.sv", "rtl/npu/loaders/ia_loader_ctrl.sv"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def predictor_registers(source):
    groups = [
        ("latched geometry", 16, "kh_q kw_q oh_q ow_q cg_q dh_q dw_q ph_q pw_q"),
        ("latched shift amounts", 6, "block_shift_q h_shift_q w_shift_q"),
        ("latched schedule spans", 32, "groups_q block_rows_q group_span_q block_span_q"),
        ("current fragment and phase", 32, "y_q x_q channel_q current_pb_q current_local_q current_group_q"),
        ("tap counters", 16, "ky_q kx_q"),
        ("best and output rank", 32, "best_q next_rank"),
        ("control flags", 1, "enabled busy done"),
    ]
    expected = {name for _, _, names in groups for name in names.split()}
    sequential = source.split("always_ff", 1)[1].split("`ifdef", 1)[0]
    actual = set(re.findall(r"\b(\w+)\s*<=", sequential))
    if actual != expected:
        raise AssertionError(("predictor register inventory changed", sorted(actual ^ expected)))
    return [{"group": label, "names": names.split(), "width_each": width,
             "bits": width * len(names.split())} for label, width, names in groups]


def capacity_row(capacity):
    ways, line = 2, 16
    sets = capacity // (ways * line)
    si, tag = (sets - 1).bit_length(), 28 - (sets - 1).bit_length()
    lines = ways * sets
    components = {"data": capacity * 8, "tags": lines * tag, "valids": lines,
                  "lru": sets, "next_use": lines * 32,
                  "transient_data": 16 * 8, "transient_tag": 28, "transient_valid": 1}
    total = sum(components.values())
    # Cache register declarations outside the memory arrays/transient, including
    # read latches, counters and response registers.  ram.rd_data/span registers
    # are in submodules and intentionally excluded from this cache-local count.
    cache_control = 338 + 2 * tag + 3 * si
    new_cache_control = 103 + si
    new_shared = new_cache_control + 581 + 98 + 32
    return {"main_data_bytes": capacity, "ways": ways, "line_bytes": line,
            "sets": sets, "lines": lines, "set_index_bits": si, "tag_bits_per_line": tag,
            "component_bits": components, "component_bytes_equivalent": {k: v / 8 for k, v in components.items()},
            "array_and_transient_total_bits": total,
            "array_and_transient_bytes_equivalent": total / 8,
            "array_and_transient_rounded_up_bytes": (total + 7) // 8,
            "baseline_lru_array_bits": components["data"] + components["tags"] + components["valids"] + components["lru"],
            "new_policy_array_and_transient_bits": components["next_use"] + 157,
            "cache_local_control_bits_including_baseline": cache_control,
            "policy_cache_control_extra_bits": new_cache_control,
            "new_predictor_frontend_scheduler_control_bits": 581 + 98 + 32,
            "new_shared_control_bits_total": new_shared,
            "policy_total_declared_extra_storage_bits": components["next_use"] + 157 + new_shared}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/conv_replacement/cost/cost.json')
    args = parser.parse_args()
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    hashes = {name: digest(ROOT / name) for name in SOURCES}
    predictor = (ROOT / SOURCES[1]).read_text()
    cache = (ROOT / SOURCES[0]).read_text()
    frontend = (ROOT / SOURCES[2]).read_text()
    # Fail rather than silently apply the inventory to a different structure.
    for snippet in ["logic [31:0] next_use [0:WAYS-1][0:SETS-1]",
                    "logic [27:0] transient_tag", "logic [31:0] transient_words [4]",
                    "logic transient_valid", "logic lru [0:SETS-1]",
                    "parameter int TAGW=32-LB-SI"]:
        if snippet not in cache:
            raise AssertionError(("cache inventory changed", snippet))
    if "logic [31:0] pred_rank, group_q, groups_q" not in frontend:
        raise AssertionError("frontend shared register inventory changed")
    register_groups = predictor_registers(predictor)
    clean = re.sub(r"//[^\n]*|/\*.*?\*/", "", predictor, flags=re.S)
    if clean.count("*") != 15:
        raise AssertionError("predictor multiply expression inventory changed")
    report = {
        "scope": "Static declaration and expression audit, CACHE_POLICY=1/2, SIZE=LINE_BYTES=16, WAYS=2; not mapped area/Fmax/power",
        "increment_reference": "LRU accounting without next-use prediction; no historical source or synthesis input is loaded",
        "source_sha256": hashes,
        "storage_unit": "logical bits; byte equivalent is bits/8; no SRAM/BRAM/LUTRAM allocation rounding",
        "capacity_rows": [capacity_row(c) for c in [512, 1024, 2048]],
        "predictor_register_groups": register_groups,
        "predictor_declared_sequential_bits": sum(g["bits"] for g in register_groups),
        "new_frontend_sequential_bits": {
            "group_q": 32, "groups_q": 32, "line_hint_rank": 32,
            "geometry_tile": 1, "line_hint_valid": 1,
        },
        "new_scheduler_sequential_bits": {"tl_group": 32},
        "new_cache_control_components": {
            "next_q": "2*32 bits", "hint_q": "32 bits", "pending_set": "log2(SETS) bits",
            "pending_way": "1 bit", "flags": "6 bits: geometry_q, request_geometry_q, first_q, allocation_q, hint_seen, hint_pending",
        },
        "predictor_multiply_expression_sites": {
            "configuration": ["output_h*output_w", "kernel_h*kernel_w", "taps*group_c",
                              "qtiles*block_rows", "groups*group_span", "blocks*block_span"],
            "each_tap": ["ky*dilation_h", "kx*dilation_w", "oy*output_w", "ky*kernel_w",
                         "(ky*kernel_w+kx)*group_c", "qtile*block_rows", "pblock*block_span",
                         "candidate_group*group_span"],
            "request_start": ["current_qtile*block_rows"],
            "total": 15,
            "width_interpretation": "Most expressions are cast to 64-bit intermediates. Sources include 16/32-bit registers, constant upper zeros and runtime guards. Expression count is not a count of physical 64x64 multipliers; no mapped sharing or width reduction was obtained.",
        },
        "major_shift_compare_structure": {
            "dynamic_right_shift_sites": 5,
            "right_shift_sites": ["configuration block count", "tap oy", "tap ox", "tap pblock", "request current_pblock"],
            "dynamic_left_shift_mask_sites": 2,
            "mask_sites": ["horizontal divisibility mask", "vertical divisibility mask"],
            "constant_shifts": "line/channel divide by 16 and R*16 are wiring shifts, not general dividers",
            "predictor_comparisons": "signed coordinate checks; 64-bit divisibility masks, bounds, pblock/local/group comparisons; 32-bit best-rank comparison; 16-bit tap termination",
            "cache_comparisons": "two TAGW-bit hit equalities, one 32-bit resident-rank comparison, one 32-bit incoming-rank comparison, INF equalities, 28-bit transient-tag equality",
            "cache_xor_mapping": "log2(SETS) XOR bits, no additional stored tag bits",
            "transient_mux": "four 32-bit words with byte write enables and a 4:1 read selection",
        },
        "important_limits": [
            "next_use stores one next-event rank per resident cache line; no remaining-count table is implemented",
            "the same shared tap datapath repeats for up to 25 taps, but this RTL does not explicitly time-share all 15 multiplication sites onto one multiplier",
            "tag/valid/LRU/next arrays are logical arrays; physical macro inference and port packing are unmeasured",
            "cache-local fixed controls exclude existing conv_axi_span_reader registers and conv_sdp_ram output register",
            "shared-control totals list policy additions only; existing frontend coordinate/divider/tile/IA/PE/register-file state is excluded",
            "unified block-DMA command, owner and Conv descriptor registers are outside this cache-policy accounting",
            "CACHE_POLICY=0 omits the predictor generate branch; constant false geometry paths should permit pruning next/transient state, but that optimization was not verified by synthesis",
        ],
    }
    report["synthesis_performed"] = False
    for name, before in hashes.items():
        if digest(ROOT / name) != before:
            raise AssertionError(("production source changed during audit", name))
    report["audit_source_sha256"] = digest(Path(__file__))
    output.write_text(json.dumps(report, indent=2) + "\n")
    for row in report["capacity_rows"]:
        print("DECLARED_COST", row["main_data_bytes"], "data bytes;",
              row["array_and_transient_total_bits"], "array/transient bits;",
              row["new_shared_control_bits_total"], "new shared control bits")
    print("DECLARED_COST_AUDIT_COMPLETE", output)


if __name__ == "__main__":
    main()
