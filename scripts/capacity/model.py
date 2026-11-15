"""Integer capacity search for the current 16-lane GEMPACT K64 panel engine.

The primary objective is the equal-weight geometric mean of normal-traversal
A+B read bytes, compared through its exact integer product. It is not a cycle
model. Nominal three-page admission assumes compact live PS records; arbitrary
data growth can still cause early completion. RAW32 retains the PCR hardware.
"""
from __future__ import annotations

import math

TILE = 16
PAGE_BYTES = 256
PANEL_BYTES_PER_TILE = 2048  # 2 ping-pong banks * 16 rows * K64 INT8 bytes
MAX_PANEL_TILES = 32
MAX_POOL_PAGES = 4095
SCOPES = ("logical-state", "buffer-ram")
REPRESENTATIONS = ("nominal3", "raw32")
MODEL_VERSION = "gempact-k64-declared-state-v1"


def ceil_div(x: int, y: int) -> int:
    return (x + y - 1) // y


def _integer(value, name, minimum=1, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        suffix = f"..{maximum}" if maximum is not None else " or greater"
        raise ValueError(f"{name} must be an integer in {minimum}{suffix}")
    return value


def _geometry(rmax, wmax, pages):
    _integer(rmax, "Rmax", 1, MAX_PANEL_TILES)
    _integer(wmax, "Wmax", 1, MAX_PANEL_TILES)
    _integer(pages, "PS pages", 4, MAX_POOL_PAGES)


def state_bits(rmax: int, wmax: int, pages: int) -> int:
    """Conservative declared state, including data, directories and AXI state.

    Derived from the elaborated PCR inventory, including the clock-gate latch.
    At the reviewed repository revision e8a7337 the current AXI wrapper is three
    bits smaller; retaining the paper expression is conservative by 0.375 B.
    This does not account for FPGA BRAM / ASIC macro rounding or host memory.
    """
    _geometry(rmax, wmax, pages)
    q = (pages - 1).bit_length()
    a = (4 * pages - 1).bit_length()
    s = ceil_div(pages, 256)
    u = max(1, (s - 1).bit_length())
    return (67668 + 16384 * (rmax + wmax) + (213 + 3 * q) * rmax * wmax
            + q * pages + 28 * q + 2048 * pages + 512 * s + 4 * u + 8 * a)


def buffer_ram_bytes(rmax: int, wmax: int, pages: int) -> int:
    """The three declared payload arrays only: A panel + B panel + PS/C pool."""
    _geometry(rmax, wmax, pages)
    return PANEL_BYTES_PER_TILE * (rmax + wmax) + PAGE_BYTES * pages


def allocation(rmax, wmax, pages, budget_bytes, scope="logical-state"):
    _integer(budget_bytes, "budget bytes")
    if scope not in SCOPES:
        raise ValueError(f"budget scope must be one of {SCOPES}")
    bits = state_bits(rmax, wmax, pages)
    ram = buffer_ram_bytes(rmax, wmax, pages)
    used = bits / 8 if scope == "logical-state" else ram
    return {
        "panel_max_r": rmax, "panel_max_w": wmax,
        "ps_pool_pages": pages, "ps_pool_bytes": pages * PAGE_BYTES,
        "a_panel_bytes": PANEL_BYTES_PER_TILE * rmax,
        "b_panel_bytes": PANEL_BYTES_PER_TILE * wmax,
        "buffer_ram_bytes": ram, "logical_state_bits": bits,
        "logical_state_bytes": bits / 8,
        "other_state_bits": bits - ram * 8,
        "budget_used_bytes": used, "unused_budget_bytes": budget_bytes - used,
    }


def _fits(rmax, wmax, pages, budget_bytes, scope):
    if scope == "logical-state":
        return state_bits(rmax, wmax, pages) <= 8 * budget_bytes
    return buffer_ram_bytes(rmax, wmax, pages) <= budget_bytes


def max_pages(rmax, wmax, budget_bytes, scope="logical-state"):
    _integer(budget_bytes, "budget bytes")
    if scope not in SCOPES:
        raise ValueError(f"budget scope must be one of {SCOPES}")
    _geometry(rmax, wmax, 4)
    low, high = 3, min(MAX_POOL_PAGES, budget_bytes // PAGE_BYTES)
    while low < high:
        mid = (low + high + 1) // 2
        if _fits(rmax, wmax, mid, budget_bytes, scope):
            low = mid
        else:
            high = mid - 1
    return low if low >= 4 else 0


def required_pages(r, w, representation="nominal3"):
    if representation not in REPRESENTATIONS:
        raise ValueError(f"representation must be one of {REPRESENTATIONS}")
    _integer(r, "R", 1, MAX_PANEL_TILES)
    _integer(w, "W", 1, MAX_PANEL_TILES)
    return 4 * r * w if representation == "raw32" else max(r * w + 3 * r, 3 * r * w + r)


def validate_workloads(workloads):
    if not isinstance(workloads, list) or not workloads:
        raise ValueError("workloads must be a nonempty list of {M, K, N} objects")
    result = []
    for task in workloads:
        if not isinstance(task, dict):
            raise ValueError("each workload must be an object with M, K and N")
        shape = {key: _integer(task.get(key), key) for key in ("M", "K", "N")}
        if any(ceil_div(value, TILE) * TILE >= 1 << 20 for value in shape.values()):
            raise ValueError("padded M/K/N must fit the RTL 20-bit dimensions")
        result.append(shape)
    return result


def _output_bursts(plan):
    # Compact row-major output. Unknown base alignment and 4 KiB splits can
    # increase the real AW count; this is a tie-break estimate, never cycles.
    result = 0
    rows = [(plan["R"], plan["row_groups"] - 1), (plan["row_tail_tiles"], 1)]
    cols = [(plan["W"], plan["column_groups"] - 1), (plan["column_tail_tiles"], 1)]
    for r, nr in rows:
        for w, nc in cols:
            if not nr or not nc:
                continue
            width = TILE * (r if plan["mode"] else w)
            height = TILE * (w if plan["mode"] else r)
            bursts = (ceil_div(width * height, 1024) if width == plan["padded_N"]
                      else height * ceil_div(width, 1024))
            result += nr * nc * bursts
    return result


def enumerate_plans(M, K, N, rmax=32, wmax=32, pages=4095,
                    representation="nominal3", mode=None, requested_r=0, requested_w=0):
    shape = validate_workloads([{"M": M, "K": K, "N": N}])[0]
    _geometry(rmax, wmax, pages)
    if representation not in REPRESENTATIONS:
        raise ValueError(f"representation must be one of {REPRESENTATIONS}")
    if mode is not None and (type(mode) is not int or mode not in (0, 1)):
        raise ValueError("mode must be None, WS=0, or IS=1")
    _integer(requested_r, "requested R", 0)
    _integer(requested_w, "requested W", 0)
    m, k, n = (ceil_div(shape[key], TILE) * TILE for key in ("M", "K", "N"))
    mt, kt, nt = m // TILE, k // TILE, n // TILE
    plans = []
    for flow in ((0, 1) if mode is None else (mode,)):
        tr, tc = (nt, mt) if flow else (mt, nt)
        for r in range(1, min(rmax, requested_r or rmax, tr) + 1):
            for w in range(1, min(wmax, requested_w or wmax, tc) + 1):
                need = required_pages(r, w, representation)
                if need > pages or r > tr or w > tc:
                    continue
                rg, cg = ceil_div(tr, r), ceil_div(tc, w)
                if max(rg, cg) > 65535:
                    continue
                groups = rg * cg
                tail = groups * r * w - tr * tc
                a_rounds, b_rounds = ceil_div(nt, r if flow else w), ceil_div(mt, w if flow else r)
                a_bytes, b_bytes = m * k * a_rounds, k * n * b_rounds
                p = {**shape, "padded_M": m, "padded_K": k, "padded_N": n,
                     "requires_padding": (M, K, N) != (m, k, n),
                     "mode": flow, "mode_name": "IS" if flow else "WS", "R": r, "W": w,
                     "row_groups": rg, "column_groups": cg,
                     "row_tail_tiles": tr - (rg - 1) * r,
                     "column_tail_tiles": tc - (cg - 1) * w,
                     "groups": groups, "tail_tile_slots": tail,
                     "required_pool_pages": need,
                     "ideal_operand_read_bytes": a_bytes + b_bytes,
                     "A_external_bytes": a_bytes, "B_external_bytes": b_bytes,
                     "A_load_rounds": a_rounds, "B_load_rounds": b_rounds,
                     "C_external_bytes": m * n, "column_frames": tc * rg * kt}
                p["estimated_output_bursts"] = _output_bursts(p)
                p["rank"] = [p["ideal_operand_read_bytes"], p["estimated_output_bursts"],
                             p["column_frames"], groups, tail, -(r * w), flow, -r, -w]
                plans.append(p)
    return sorted(plans, key=lambda p: p["rank"])


def plan_for_hardware(M, K, N, rmax, wmax, pages, representation="nominal3",
                      mode=None, requested_r=0, requested_w=0):
    """Best schedule for fixed hardware and optional fixed dataflow.

    requested_r/w are upper bounds (zero means automatic), not exact groups.
    The selected dimensions may shrink further to satisfy shape and PS limits.
    """
    plans = enumerate_plans(M, K, N, rmax, wmax, pages, representation,
                            mode, requested_r, requested_w)
    if not plans:
        raise ValueError("no legal activity group fits the selected hardware and PS policy")
    return plans[0]


def solve(workloads, budget_bytes, budget_scope="logical-state", representation="nominal3"):
    tasks = validate_workloads(workloads)
    _integer(budget_bytes, "budget bytes")
    if budget_scope not in SCOPES:
        raise ValueError(f"budget scope must be one of {SCOPES}")
    if representation not in REPRESENTATIONS:
        raise ValueError(f"representation must be one of {REPRESENTATIONS}")
    candidates = [enumerate_plans(**task, representation=representation) for task in tasks]
    options = []
    for r in range(1, MAX_PANEL_TILES + 1):
        for w in range(1, MAX_PANEL_TILES + 1):
            pages = max_pages(r, w, budget_bytes, budget_scope)
            if not pages:
                continue
            selected = []
            for plans in candidates:
                plan = next((p for p in plans if p["R"] <= r and p["W"] <= w
                             and p["required_pool_pages"] <= pages), None)
                if plan is None:
                    break
                selected.append(plan)
            if len(selected) != len(tasks):
                continue
            alloc = allocation(r, w, pages, budget_bytes, budget_scope)
            key = (math.prod(p["ideal_operand_read_bytes"] for p in selected),
                   sum(p["estimated_output_bursts"] for p in selected),
                   sum(p["column_frames"] for p in selected),
                   sum(p["groups"] for p in selected), alloc["logical_state_bits"], r, w)
            options.append((key, alloc, selected))
    if not options:
        raise ValueError(f"no feasible GEMPACT allocation fits {budget_bytes} B ({budget_scope})")
    options.sort(key=lambda x: x[0])
    key, alloc, plans = options[0]
    minimum_pages = max(p["required_pool_pages"] for p in plans)
    return {
        "schema_version": 1, "model_version": MODEL_VERSION,
        "budget": {"bytes": budget_bytes, "scope": budget_scope},
        "representation": representation, "workloads": tasks,
        "allocation": alloc, "plans": plans,
        "metrics": {
            "gmean_operand_read_bytes": math.exp(sum(math.log(p["ideal_operand_read_bytes"]) for p in plans) / len(plans)),
            "exact_operand_read_product_hex": format(key[0], "x"),
            "task_count": len(plans), "sum_estimated_output_bursts": key[1],
            "sum_column_frames": key[2], "sum_groups": key[3],
            "minimum_pages_for_selected_plans": minimum_pages,
        },
        "search": {"enumerated_geometries": MAX_PANEL_TILES ** 2,
                   "feasible_geometries": len(options),
                   "same_read_geometries": sum(o[0][0] == key[0] for o in options),
                   "rmax_range": [1, MAX_PANEL_TILES], "wmax_range": [1, MAX_PANEL_TILES],
                   "page_range": [4, MAX_POOL_PAGES],
                   "pool_rule": "maximum feasible pages for each panel geometry"},
        "objective": "Minimize the equal-weight geometric mean of normal-traversal A+B bytes; break ties by estimated output bursts, frames, groups, logical state, Rmax and Wmax.",
        "assumptions": [
            "One physical allocation is shared by every supplied task; per-task WS/IS and uniform R/W with tails may differ.",
            "Fixed 16x16 INT8 array, K64 ping-pong panels, exact INT32 PS, and the current PCR control family.",
            "nominal3 uses RW+3R<=P and 3RW+R<=P; record growth may still cause early completion and extra reads.",
            "raw32 uses 4RW<=P and retains the codec/controller state; application sets PS_FORCE_RAW=1.",
            "buffer-ram counts only declared A/B panel and PS/C payload; logical-state also charges directories, queues, pipelines, control and AXI state.",
            "Neither scope predicts ASIC SRAM macro or FPGA BRAM allocation granularity, physical area, or timing.",
            "Output burst estimates omit base-address-dependent splitting; lower reads or fewer frames do not prove lower cycles.",
            "Maximum-P enumeration is sufficient for the primary traffic optimum, not a minimum-state or cycle-optimal proof.",
            "Nonmultiples of 16 require caller-provided operand padding and output trimming; this solver does not transform tensors.",
            "Callers must validate tensor buffer extents, strides, nonoverlap, and 32-bit AXI addressability separately.",
        ],
    }
