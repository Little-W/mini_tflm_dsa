"""Host tiling and shared PS capacity planning for the single compute array."""
from pathlib import Path
import argparse
import json
import shutil

SUPPORTED = tuple(sorted({1 << i for i in range(16)} | {25}))


def floor_supported(value):
    if 25 <= value < 32:
        return 25
    return 1 << (max(1, value).bit_length() - 1)


def plan(rows, cols, size, cache, ps, requested_r=0, requested_w=0,
         is_mode=False, per_channel=False):
    if min(rows, cols, size, cache, ps) <= 0 or size & (size - 1):
        raise ValueError("positive dimensions/capacities and power-of-two array size required")
    if is_mode:
        rows, cols = cols, rows
    tr = (rows + size - 1) // size
    tc = (cols + size - 1) // size
    rcap = floor_supported(max(1, cache // 2))
    wcap = floor_supported(min(tc, ps))
    r = floor_supported(min(requested_r or rcap, rcap))
    w = floor_supported(min(requested_w or wcap, wcap))
    if is_mode and per_channel and r == 25:
        r = 16
    rg, rt = divmod(tr, r)
    cg, ct = divmod(tc, w)
    result = dict(ia_reuse=r, w_reuse=w, row_groups=rg + bool(rt),
                  row_tail_tiles=rt or r, col_groups=cg + bool(ct), col_tail_tiles=ct or w)
    if max(result.values()) > 65535:
        raise ValueError("tiling fields exceed the 16-bit counter range")
    return result


def payload_bound(size, r, w, stream_rows=None):
    active_rows = r * size if stream_rows is None else min(stream_rows, r * size)
    return active_rows * w * size * 4


def plan_capacity(rows, cols, size, cache, ps, requested_r=0, requested_w=0,
                  is_mode=False, per_channel=False, pool_bytes=0):
    values = [rows, cols, size, cache, ps, requested_r, requested_w, pool_bytes]
    if any(not isinstance(x, int) or x < 0 or x > 0xffffffff for x in values):
        raise ValueError("host tiling arguments must be unsigned 32-bit integers")
    cap = plan(rows, cols, size, cache, ps, requested_r, requested_w, is_mode, per_channel)
    if not pool_bytes:
        return cap, dict(policy="ordinary_ps_ram", payload_bound_bytes=0)
    if size != 16 or pool_bytes % 64:
        raise ValueError("compressed PS requires SIZE=16 and a positive multiple-of-64 pool")
    sr, sc = (cols, rows) if is_mode else (rows, cols)
    tr = (sr + size - 1) // size
    tc = (sc + size - 1) // size
    choices = []
    for r in SUPPORTED:
        if r > cap["ia_reuse"]:
            continue
        for w in SUPPORTED:
            if w > cap["w_reuse"]:
                continue
            try:
                candidate = plan(rows, cols, size, cache, ps, r, w, is_mode, per_channel)
            except ValueError:
                continue
            if (candidate["ia_reuse"], candidate["w_reuse"]) != (r, w):
                continue
            bound = payload_bound(size, r, w, sr)
            if bound > pool_bytes:
                continue
            cost = sr * ((tc + w - 1) // w) + sc * ((tr + r - 1) // r)
            choices.append(((cost, -r * w, bound), candidate))
    if not choices:
        raise ValueError("PS pool cannot hold the smallest complete workgroup")
    key, result = min(choices, key=lambda x: x[0])
    metadata = dict(policy="worst_case_INT32", pool_bytes=pool_bytes,
                    payload_bound_bytes=key[2], payload_margin_bytes=pool_bytes - key[2],
                    frame_rows=min(sr, result["ia_reuse"] * size),
                    max_record_bytes=64, stored_payload_frames=result["w_reuse"],
                    extra_directory_contexts=0,
                    requested_effective_r=cap["ia_reuse"], requested_effective_w=cap["w_reuse"],
                    selected_r=result["ia_reuse"], selected_w=result["w_reuse"],
                    changed=result != cap, input_cost_per_reduction_element=key[0],
                    directory_charged_separately=True)
    return result, metadata


def workload_cost(rows, reduction, cols, size, lhs_bytes, bus_bytes, is_mode, tiling):
    sr, sc = (cols, rows) if is_mode else (rows, cols)
    tc = (sc + size - 1) // size
    nk = (reduction + size - 1) // size
    a_rounds = tiling["row_groups"] if is_mode else tiling["col_groups"]
    b_rounds = tiling["col_groups"] if is_mode else tiling["row_groups"]
    read_bytes = rows * reduction * lhs_bytes * a_rounds + cols * reduction * b_rounds
    frames = tiling["row_groups"] * tc * nk
    stream = (sr + (size - 1) * tiling["row_groups"]) * tc * nk
    return dict(lhs_read_rounds=a_rounds, rhs_read_rounds=b_rounds,
                operand_read_bytes=read_bytes, frame_count=frames,
                array_stream_cycles=stream,
                service_estimate=max((read_bytes + bus_bytes - 1) // bus_bytes, stream) + frames)


def _describe(rows, reduction, cols, size, lhs_bytes, bus_bytes, mode, tiling):
    sr = cols if mode else rows
    return dict(tiling=tiling, is_mode=mode,
                frame_rows=min(sr, tiling["ia_reuse"] * size),
                payload_bound_bytes=0 if reduction <= size else payload_bound(
                    size, tiling["ia_reuse"], tiling["w_reuse"], sr),
                **workload_cost(rows, reduction, cols, size, lhs_bytes, bus_bytes, mode, tiling))


def _rank(p):
    return tuple(p[x] for x in ("service_estimate", "frame_count", "operand_read_bytes",
                                 "array_stream_cycles", "payload_bound_bytes")) + (
                                 p["tiling"]["ia_reuse"], p["tiling"]["w_reuse"])


def plan_dispatch(rows, reduction, cols, size, cache, ps, requested_r=0, requested_w=0,
                  mode=2, is_supported=True, per_channel=False, lhs_bytes=1,
                  bus_bytes=4, pool_bytes=0, adaptive=False):
    if reduction <= 0 or mode not in (0, 1, 2) or min(lhs_bytes, bus_bytes) <= 0:
        raise ValueError("invalid reduction, dataflow mode, or element/bus size")
    planning_pool = 0 if reduction <= size else pool_bytes
    if planning_pool and (size != 16 or planning_pool % 64):
        raise ValueError("compressed PS requires SIZE=16 and a multiple-of-64 pool")
    candidates = []
    for selected in (0, 1):
        if (mode != 2 and mode != selected) or (selected and not is_supported):
            continue
        try:
            cap = plan(rows, cols, size, cache, ps, requested_r, requested_w, selected, per_channel)
        except ValueError:
            continue
        choices = []
        for r in SUPPORTED:
            for w in SUPPORTED:
                if r > cap["ia_reuse"] or w > cap["w_reuse"]:
                    continue
                t = plan(rows, cols, size, cache, ps, r, w, selected, per_channel)
                if (t["ia_reuse"], t["w_reuse"]) != (r, w):
                    continue
                choices.append(_describe(rows, reduction, cols, size, lhs_bytes, bus_bytes, selected, t))
        safe_choices = [p for p in choices if not planning_pool or p["payload_bound_bytes"] <= planning_pool]
        if not safe_choices:
            continue
        safe = min(safe_choices, key=_rank)
        selected_plan = safe
        if adaptive and planning_pool:
            expanded = [p for p in choices if p["tiling"]["ia_reuse"] >= safe["tiling"]["ia_reuse"]
                        and p["tiling"]["w_reuse"] >= safe["tiling"]["w_reuse"]
                        and p["frame_rows"] * size * 4 <= planning_pool]
            selected_plan = min(expanded, key=_rank)
        result = dict(selected_plan, raw_safe=dict(safe["tiling"]),
                      adaptive_active=selected_plan["tiling"] != safe["tiling"],
                      capacity=dict(policy="no_intermediate_ps" if reduction <= size else
                                           "ordinary_ps_ram" if not pool_bytes else "worst_case_INT32",
                                    pool_bytes=pool_bytes, payload_bound_bytes=safe["payload_bound_bytes"]))
        candidates.append(result)
    if not candidates:
        raise ValueError("no supported dataflow fits the configured capacity")
    result = dict(min(candidates, key=_rank))
    result["candidates"] = [dict(mode=p["is_mode"], R=p["tiling"]["ia_reuse"], W=p["tiling"]["w_reuse"],
                                 raw_safe=p["raw_safe"], **{k: p[k] for k in
                          ("operand_read_bytes", "frame_count", "array_stream_cycles", "service_estimate")})
                            for p in candidates]
    return result


def apply_words(words, pool_bytes=0, adaptive=False, is_supported=True):
    if len(words) != 32 or any(x < 0 or x > 0xffffffff for x in words) or words[0] != 0x4e505531:
        raise ValueError("expected a 32-word NPU1 tensor descriptor")
    p = plan_dispatch(words[3], words[4], words[5], words[1], words[2], words[9],
                      words[6], words[7], words[8], is_supported and not words[28],
                      bool(words[13]), 2 if words[12] else 1, 4, pool_bytes, adaptive)
    t = p["tiling"]
    words = list(words)
    words[6], words[7], words[8] = t["ia_reuse"], t["w_reuse"], p["is_mode"]
    words[30] = t["row_groups"] | (t["col_groups"] << 16)
    words[31] = t["row_tail_tiles"] | (t["col_tail_tiles"] << 16)
    return words, {**t, **p}


def prepare_case(source, dest, pool_bytes=0):
    source, dest = Path(source), Path(dest)
    words = [int(x, 16) for x in (source / "config.mem").read_text().split()]
    words, p = apply_words(words, pool_bytes)
    dest.mkdir(parents=True, exist_ok=False)
    for name in ("init.mem", "golden.mem", "acc.mem"):
        if (source / name).exists():
            shutil.copy2(source / name, dest / name)
    (dest / "config.mem").write_text("".join(f"{x:08x}\n" for x in words))
    (dest / "host_tiling.json").write_text(json.dumps(p, indent=2) + "\n")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--pool-bytes", type=int, default=0,
                        help="compressed payload bytes; zero selects ordinary PS RAM")
    args = parser.parse_args()
    print(prepare_case(args.source, args.destination, args.pool_bytes))
