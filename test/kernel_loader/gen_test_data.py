#!/usr/bin/env python3
"""Generate kernel_loader test data and parameter header."""

from __future__ import annotations

import argparse
import os
import json
import random

SIZE = 4
DATA_WIDTH = 8
BUS_WIDTH = 32
BASE_ADDR = 0x100
SRAM_DEPTH = 1024


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


CASES = {
    "exact_1x1_r1_w1": dict(k=4, n=4, m=4, ia_reuse_num=1, w_reuse_num=1),
    "exact_2x2_r1_w2": dict(k=8, n=8, m=8, ia_reuse_num=1, w_reuse_num=2),
    "exact_4x4_r1_w2": dict(k=16, n=16, m=16, ia_reuse_num=1, w_reuse_num=2),
    "exact_4x4_r2_w2": dict(k=16, n=16, m=16, ia_reuse_num=2, w_reuse_num=2),
    "exact_4x4_r3_w1": dict(k=16, n=16, m=16, ia_reuse_num=3, w_reuse_num=1),
    "col_rem_r1_w2": dict(k=16, n=10, m=16, ia_reuse_num=1, w_reuse_num=2),
    "row_rem_r1_w2": dict(k=10, n=16, m=16, ia_reuse_num=1, w_reuse_num=2),
    "both_rem_r2_w3": dict(k=10, n=10, m=18, ia_reuse_num=2, w_reuse_num=3),
    "wide_r1_w4": dict(k=4, n=32, m=16, ia_reuse_num=1, w_reuse_num=4),
    "tall_r4_w1": dict(k=32, n=4, m=8, ia_reuse_num=4, w_reuse_num=1),
    "zp_offset_r1_w2": dict(k=12, n=12, m=12, ia_reuse_num=1, w_reuse_num=2, rhs_zp=-7),
    "unaligned_base_r1_w2": dict(k=8, n=8, m=8, ia_reuse_num=1, w_reuse_num=2, base_addr=0x102),
    "grant_bp_r2_w2": dict(k=16, n=16, m=16, ia_reuse_num=2, w_reuse_num=2,
                            grant_bp_en=1, grant_bp_cycles=4),
}


def write_init_mem(out_dir: str, rows: int, cols: int, base_addr: int) -> None:
    mem = [0] * SRAM_DEPTH
    bytes_per_elem = DATA_WIDTH // 8
    row_stride_b = cols * bytes_per_elem

    for r in range(rows):
        for c in range(cols):
            value = (r * cols + c + 1) & 0xFF
            if value >= 0x80:
                value -= 0x100
            byte_addr = base_addr + r * row_stride_b + c * bytes_per_elem
            word_idx = byte_addr // 4
            byte_off = byte_addr % 4
            mem[word_idx] |= (value & 0xFF) << (byte_off * 8)

    with open(os.path.join(out_dir, "init.mem"), "w", encoding="utf-8") as fp:
        for word in mem:
            fp.write(f"{word & 0xFFFFFFFF:08x}\n")


def write_params(out_dir: str, case: str, k: int, n: int, m: int, ia_reuse_num: int, w_reuse_num: int,
                 rhs_zp: int, base_addr: int, grant_bp_en: int = 0, grant_bp_cycles: int = 0) -> None:
    # GEMM shape is (K x N) * (N x M).  The kernel/RHS matrix therefore has
    # N rows and M columns.  K only controls how many output-row groups consume
    # the same RHS stream.
    tile_rows = ceil_div(n, SIZE)
    tile_cols = ceil_div(m, SIZE)
    output_row_tiles = ceil_div(k, SIZE)
    l2_groups = ceil_div(tile_cols, w_reuse_num)
    repeat_total = ceil_div(output_row_tiles, ia_reuse_num)
    if repeat_total == 0:
        repeat_total = 1
    total_tiles = repeat_total * tile_rows * tile_cols

    with open(os.path.join(out_dir, "test_params.svh"), "w", encoding="utf-8") as fp:
        fp.write(f"// Auto-generated for {case}\n")
        fp.write(f"localparam int TC_K = {k};\n")
        fp.write(f"localparam int TC_N = {n};\n")
        fp.write(f"localparam int TC_M = {m};\n")
        fp.write(f"localparam int TC_IA_REUSE_NUM = {ia_reuse_num};\n")
        fp.write(f"localparam int TC_W_REUSE_NUM = {w_reuse_num};\n")
        fp.write(f"localparam int TC_TILE_ROWS = {tile_rows};\n")
        fp.write(f"localparam int TC_TILE_COLS = {tile_cols};\n")
        fp.write(f"localparam int TC_OUTPUT_ROW_TILES = {output_row_tiles};\n")
        fp.write(f"localparam int TC_REPEAT_TOTAL = {repeat_total};\n")
        fp.write(f"localparam int TC_L2_GROUPS = {l2_groups};\n")
        fp.write(f"localparam int TC_TOTAL_TILES = {total_tiles};\n")
        fp.write(f"localparam int TC_BASE_ADDR = 32'h{base_addr:08x};\n")
        fp.write(f"localparam int TC_ROW_STRIDE_B = {m};\n")
        fp.write(f"localparam int TC_RHS_ZP = {rhs_zp};\n")
        fp.write(f"localparam int TC_SRAM_DEPTH = {SRAM_DEPTH};\n")
        fp.write(f"localparam int TC_GRANT_BP_EN = {grant_bp_en};\n")
        fp.write(f"localparam int TC_GRANT_BP_CYCLES = {grant_bp_cycles};\n")

    with open(os.path.join(out_dir, "params.json"), "w", encoding="utf-8") as fp:
        json.dump({
            "case": case,
            "k": k,
            "n": n,
            "m": m,
            "ia_reuse_num": ia_reuse_num,
            "w_reuse_num": w_reuse_num,
            "rhs_zp": rhs_zp,
            "base_addr": base_addr,
            "grant_bp_en": grant_bp_en,
            "grant_bp_cycles": grant_bp_cycles,
            "tile_rows": tile_rows,
            "tile_cols": tile_cols,
            "output_row_tiles": output_row_tiles,
            "repeat_total": repeat_total,
            "l2_groups": l2_groups,
            "total_tiles": total_tiles,
        }, fp, indent=2)


def random_case(rng: random.Random) -> dict:
    return {
        "k": rng.choice([4, 5, 8, 10, 12, 16, 18, 24, 32]),
        "n": rng.choice([4, 5, 8, 10, 12, 16, 20, 24, 32]),
        "m": rng.choice([4, 8, 12, 16, 20, 24, 32]),
        "ia_reuse_num": rng.choice([1, 2, 3, 4]),
        "w_reuse_num": rng.choice([1, 2, 3, 4]),
        "rhs_zp": rng.choice([0, -7, -3, 5]),
        "base_addr": rng.choice([0x100, 0x102, 0x103, 0x104]),
    }


def generate_case(case_name: str, params: dict, out_dir: str) -> None:
    base_addr = int(params.get("base_addr", BASE_ADDR))
    rhs_zp = int(params.get("rhs_zp", 0))
    k = int(params["k"])
    n = int(params["n"])
    m = int(params["m"])
    ia_reuse_num = int(params["ia_reuse_num"])
    w_reuse_num = int(params["w_reuse_num"])
    grant_bp_en = int(params.get("grant_bp_en", 0))
    grant_bp_cycles = int(params.get("grant_bp_cycles", 0))

    os.makedirs(out_dir, exist_ok=True)
    write_init_mem(out_dir, n, m, base_addr)
    write_params(out_dir, case_name, k, n, m, ia_reuse_num, w_reuse_num, rhs_zp, base_addr,
                 grant_bp_en, grant_bp_cycles)
    print(f"Generated {case_name} into {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="exact_4x4_r2_w2")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--random", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--out_dir", default="out")
    args = parser.parse_args()

    if args.list:
        print("Available cases:")
        for name, params in CASES.items():
            print(f"  {name:20s} k={params['k']:3d} n={params['n']:3d} m={params['m']:3d} R={params['ia_reuse_num']} W={params['w_reuse_num']}")
        return

    if args.all:
        for name, params in CASES.items():
            generate_case(name, params, os.path.join(args.out_dir, name))
        return

    if args.random:
        rng = random.Random(args.seed)
        print(f"Random seed: {args.seed}")
        for idx in range(args.count):
            case_name = f"rand_{args.seed}_{idx}"
            params = random_case(rng)
            generate_case(case_name, params, os.path.join(args.out_dir, case_name))
        with open(os.path.join(args.out_dir, "case_list.txt"), "w", encoding="utf-8") as fp:
            for idx in range(args.count):
                fp.write(f"rand_{args.seed}_{idx}\n")
        return

    if args.case not in CASES:
        raise SystemExit(f"Unknown case: {args.case}")

    params = CASES[args.case]
    generate_case(args.case, params, args.out_dir)


if __name__ == "__main__":
    main()
