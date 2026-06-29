#!/usr/bin/env python3
"""
bias_loader 测试数据生成器
================================
生成 init.mem、test_params.svh 和 golden.txt。
"""

import argparse
import json
import os
import random
import sys

SIZE = 8
BASE_ADDR = 0x100
SRAM_DEPTH = 4096


def ceil_div(a, b):
    return (a + b - 1) // b


PREDEFINED_CASES = {
    "single": dict(M=5, last_loop=1),
    "exact_two": dict(M=16, last_loop=1),
    "tail": dict(M=10, last_loop=1),
    "wrap": dict(M=24, last_loop=0),
    "long_last": dict(M=20, last_loop=1),
    "grant_bp": dict(M=20, last_loop=1, grant_bp_en=1, grant_bp_cycles=4),
    "switch_bp": dict(M=24, last_loop=1, bp_target_req_idx=2, bp_target_req_cycles=6, check_valid_drop=1),
}


def generate_case(params, out_dir, case_name):
    m = params["M"]
    last_loop = int(params.get("last_loop", 1))
    grant_bp_en = int(params.get("grant_bp_en", 0))
    grant_bp_cycles = int(params.get("grant_bp_cycles", 0))
    bp_target_req_idx = int(params.get("bp_target_req_idx", 0))
    bp_target_req_cycles = int(params.get("bp_target_req_cycles", 0))
    check_valid_drop = int(params.get("check_valid_drop", 0))
    num_blocks = ceil_div(m, SIZE) if m else 0
    last_block_elems = SIZE if (m % SIZE == 0 and m != 0) else (m % SIZE)
    if m == 0:
        last_block_elems = 0
    seq_len = num_blocks if last_loop else (num_blocks + 1)

    os.makedirs(out_dir, exist_ok=True)

    bias = [i + 1 for i in range(m)]
    mem_words = max(ceil_div(BASE_ADDR + m * 4, 4) + 16, 256)
    mem_words = min(mem_words, SRAM_DEPTH)
    mem = [0] * mem_words
    for idx, value in enumerate(bias):
        byte_addr = BASE_ADDR + idx * 4
        word_idx = byte_addr // 4
        byte_off = byte_addr % 4
        if word_idx < mem_words:
            mem[word_idx] |= ((value & 0xFFFFFFFF) << (byte_off * 8))

    with open(os.path.join(out_dir, "init.mem"), "w", encoding="utf-8") as f:
        for value in mem:
            f.write(f"{value & 0xFFFFFFFF:08x}\n")

    with open(os.path.join(out_dir, "test_params.svh"), "w", encoding="utf-8") as f:
        f.write(f"// Auto-generated for case: {case_name}\n")
        f.write(f"localparam int TC_K = {m};\n")
        f.write(f"localparam int TC_M = {m};\n")
        f.write(f"localparam int TC_BASE_ADDR = 32'h{BASE_ADDR:08x};\n")
        f.write(f"localparam int TC_NUM_BLOCKS = {num_blocks};\n")
        f.write(f"localparam int TC_LAST_BLOCK_ELEMS = {last_block_elems};\n")
        f.write(f"localparam int TC_SEQ_LEN = {seq_len};\n")
        f.write(f"localparam int TC_LAST_LOOP = {last_loop};\n")
        f.write(f"localparam int TC_GRANT_BP_EN = {grant_bp_en};\n")
        f.write(f"localparam int TC_GRANT_BP_CYCLES = {grant_bp_cycles};\n")
        f.write(f"localparam int TC_BP_TARGET_REQ_IDX = {bp_target_req_idx};\n")
        f.write(f"localparam int TC_BP_TARGET_REQ_CYCLES = {bp_target_req_cycles};\n")
        f.write(f"localparam int TC_CHECK_VALID_DROP = {check_valid_drop};\n")
        f.write(f"localparam int TC_SRAM_DEPTH = {mem_words};\n")

    with open(os.path.join(out_dir, "golden.txt"), "w", encoding="utf-8") as f:
        f.write(f"# Case: {case_name}\n")
        f.write(f"# M={m} SIZE={SIZE} NUM_BLOCKS={num_blocks} LAST_ELEMS={last_block_elems}\n\n")
        for blk in range(num_blocks):
            elems = SIZE if blk + 1 < num_blocks else last_block_elems
            f.write(f"BLOCK {blk} elems={elems}\n")
            for i in range(SIZE):
                idx = blk * SIZE + i
                if idx < m:
                    f.write(f"  {bias[idx]}\n")
                else:
                    f.write("  0\n")
        f.write("\n")

    with open(os.path.join(out_dir, "params.json"), "w", encoding="utf-8") as f:
        json.dump(dict(case=case_name, M=m, last_loop=last_loop,
                       num_blocks=num_blocks, last_block_elems=last_block_elems,
                       seq_len=seq_len, grant_bp_en=grant_bp_en,
                       grant_bp_cycles=grant_bp_cycles,
                       bp_target_req_idx=bp_target_req_idx,
                       bp_target_req_cycles=bp_target_req_cycles,
                       check_valid_drop=check_valid_drop), f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="bias_loader 测试数据生成器")
    parser.add_argument("--case", type=str, help="预定义 case 名称")
    parser.add_argument("--list", action="store_true", help="列出所有预定义 case")
    parser.add_argument("--all", action="store_true", help="生成所有预定义 case")
    parser.add_argument("--random", action="store_true", help="生成随机 case")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--M", type=int, default=None)
    parser.add_argument("--last_loop", type=int, choices=[0, 1], default=None)
    parser.add_argument("--out_dir", type=str, default="out")
    args = parser.parse_args()

    if args.list:
        print("预定义 case 列表:")
        for name, p in PREDEFINED_CASES.items():
            print(f"  {name:12s}  M={p['M']:3d} last_loop={p.get('last_loop', 1)}")
        return

    cases = []
    if args.all:
        for name, params in PREDEFINED_CASES.items():
            cases.append((name, params))
    elif args.random:
        seed = args.seed if args.seed is not None else random.randint(0, 2**31)
        print(f"Random seed: {seed}")
        rng = random.Random(seed)
        for i in range(args.count):
            m = rng.randint(1, 48)
            last_loop = rng.choice([0, 1])
            cases.append((f"rand_{seed}_{i}", dict(M=m, last_loop=last_loop)))
    elif args.case:
        if args.case not in PREDEFINED_CASES:
            print(f"ERROR: unknown case '{args.case}'")
            print(f"Available: {', '.join(PREDEFINED_CASES.keys())}")
            sys.exit(1)
        cases.append((args.case, PREDEFINED_CASES[args.case]))
    elif args.M is not None:
        cases.append(("custom", dict(M=args.M, last_loop=1 if args.last_loop is None else args.last_loop)))
    else:
        cases.append(("single", PREDEFINED_CASES["single"]))

    multi = len(cases) > 1
    results = []
    for name, params in cases:
        case_dir = os.path.join(args.out_dir, name) if multi else args.out_dir
        generate_case(params, case_dir, name)
        results.append((name, params))
        print(f"  [{name:12s}] M={params['M']:3d} last_loop={params.get('last_loop', 1)} -> {case_dir}/")

    if multi:
        with open(os.path.join(args.out_dir, "case_list.txt"), "w", encoding="utf-8") as f:
            for name, _ in results:
                f.write(f"{name}\n")


if __name__ == "__main__":
    main()