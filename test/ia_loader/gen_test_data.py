#!/usr/bin/env python3
"""
ia_loader 多 case 测试数据生成器
=================================
生成 SRAM 初始化文件 (init.mem)、参数头文件 (test_params.svh)、
以及 golden 参考文件 (golden.txt)。

支持三种运行模式：
  1. 预定义 case：   python3 gen_test_data.py --case <name>
  2. 自定义参数：     python3 gen_test_data.py --K 24 --N 10 --M 16 --R 2 --W 2
  3. 随机 case：      python3 gen_test_data.py --random [--seed 42] [--count 5]
  4. 全部预定义：     python3 gen_test_data.py --all
  5. 预定义+随机：    python3 gen_test_data.py --all --random --count 3

用法示例：
  # 单个 case（输出到 out/）
  python3 gen_test_data.py --case exact_2x2

  # 所有预定义 case（每个 case 一个子目录）
  python3 gen_test_data.py --all

  # 5 个随机 case
  python3 gen_test_data.py --random --seed 42 --count 5
"""

import argparse
import os
import random
import sys
import json

SIZE = 8  # SA 维度（硬件固定）
BASE_ADDR = 0x100
DEFAULT_USE_16BITS = 1
LHS_ZP = 0
SRAM_DEPTH = 4096  # words


def ceil_div(a, b):
    return (a + b - 1) // b


# ── 预定义 case ──────────────────────────────────────────────
PREDEFINED_CASES = {
    "exact_1x1":  dict(K=8,  N=8,  M=8,  R=1, W=1),   # 最小：单 tile
    "exact_2x2":  dict(K=16, N=16, M=16, R=2, W=2),   # 2×2 tile 精确对齐
    "col_rem":    dict(K=16, N=10, M=16, R=2, W=2),   # 列方向余量 (N%SIZE!=0)
    "row_rem":    dict(K=10, N=16, M=16, R=2, W=2),   # 行方向余量 (K%SIZE!=0)
    "both_rem":   dict(K=10, N=10, M=10, R=2, W=2),   # 行列均有余量
    "single_col": dict(K=16, N=5,  M=8,  R=2, W=1),   # 单列 tile (N<SIZE)
    "single_row": dict(K=5,  N=16, M=16, R=1, W=2),   # 单行 tile (K<SIZE)
    "large_r":    dict(K=32, N=16, M=16, R=4, W=2),   # R=4 多行复用
    "large":      dict(K=64, N=64, M=64, R=2, W=2),   # 多次 init group / L2 复用
    "large_w":    dict(K=16, N=16, M=32, R=2, W=4),   # W=4 多列复用
    "r1_w1":      dict(K=24, N=24, M=24, R=1, W=1),   # 无复用
    "wide":       dict(K=8,  N=32, M=16, R=1, W=2),   # 宽矩阵
    "tall":       dict(K=32, N=8,  M=16, R=4, W=1),   # 高矩阵
    "max_reuse":  dict(K=32, N=32, M=32, R=4, W=4),   # 最大复用
    "tiny":       dict(K=1,  N=1,  M=1,  R=1, W=1),   # 极端小：1×1 矩阵
    "one_row":    dict(K=1,  N=16, M=8,  R=1, W=1),   # 单行矩阵
    "one_col":    dict(K=16, N=1,  M=8,  R=2, W=1),   # 单列矩阵
    # use_16bits 验证特性（s8 路径）
    "exact_2x2_s8": dict(K=16, N=16, M=16, R=2, W=2, use_16bits=0),
    "col_rem_s8":   dict(K=16, N=10, M=16, R=2, W=2, use_16bits=0),
    # granted 反压：每次 req 后延迟若干拍再授权
    "grant_bp":     dict(K=16, N=16, M=16, R=2, W=2, grant_bp_en=1, grant_bp_cycles=6),
}


def random_params(rng):
    """生成随机合法参数。R, W 必须为 2 的幂。"""
    r_choices = [1, 2, 3, 4]
    w_choices = [1, 2, 3, 4]
    R = rng.choice(r_choices)
    W = rng.choice(w_choices)
    use_16bits = rng.choice([0, 1])
    K = rng.randint(1, 128)
    N = rng.randint(1, 128)
    M = rng.randint(1, 128)
    # 确保 SRAM 容得下
    for _ in range(100):
        row_stride = N * (2 if use_16bits else 1)
        if BASE_ADDR + K * row_stride <= SRAM_DEPTH * 4:
            break
        K = rng.randint(1, 128)
        N = rng.randint(1, 128)
    return dict(K=K, N=N, M=M, R=R, W=W, use_16bits=use_16bits)


def generate_case(params, out_dir, case_name):
    """为一个 case 生成 init.mem, test_params.svh, golden.txt, params.json。"""
    K, N, M, R, W = params["K"], params["N"], params["M"], params["R"], params["W"]
    use_16bits = int(params.get("use_16bits", DEFAULT_USE_16BITS))
    lhs_zp = int(params.get("lhs_zp", LHS_ZP))
    grant_bp_en = int(params.get("grant_bp_en", 0))
    grant_bp_cycles = int(params.get("grant_bp_cycles", 0))
    row_stride = N * (2 if use_16bits else 1)

    os.makedirs(out_dir, exist_ok=True)

    # ── IA 矩阵 ──
    ia_matrix = []
    for r in range(K):
        row = []
        for c in range(N):
            if use_16bits:
                val = (r * N + c + 1) & 0xFFFF
                if val > 32767:
                    val -= 65536
            else:
                val = (r * N + c + 1) & 0xFF
                if val > 127:
                    val -= 256
            row.append(val)
        ia_matrix.append(row)

    # ── SRAM init.mem ──
    elem_bytes = 2 if use_16bits else 1
    max_addr = BASE_ADDR + K * row_stride
    sram_words = max(max_addr // 4 + 1, 16)
    actual_sram_depth = min(max(sram_words + 16, 256), SRAM_DEPTH)

    mem = [0] * actual_sram_depth
    for r in range(K):
        for c in range(N):
            byte_addr = BASE_ADDR + r * row_stride + c * elem_bytes
            word_idx = byte_addr // 4
            byte_off = byte_addr % 4
            if word_idx >= len(mem):
                continue
            val = ia_matrix[r][c] & (0xFFFF if use_16bits else 0xFF)
            mem[word_idx] |= (val << (byte_off * 8))

    with open(os.path.join(out_dir, "init.mem"), 'w') as f:
        for w_val in mem:
            f.write(f"{w_val & 0xFFFFFFFF:08x}\n")

    # ── 派生参数 ──
    HTN = ceil_div(N, SIZE)
    VTN = ceil_div(K, SIZE)
    LRN = ceil_div(M, SIZE)
    G2 = ceil_div(VTN, R)
    G1 = HTN
    R_act = VTN % R if VTN % R != 0 else R

    # 计算总发送次数
    total_sends = 0
    for l2 in range(G2):
        r_cur = R_act if l2 == G2 - 1 else R
        total_sends += G1 * W * r_cur

    # ── test_params.svh ──
    with open(os.path.join(out_dir, "test_params.svh"), 'w') as f:
        f.write(f"// Auto-generated for case: {case_name}\n")
        f.write(f"// K={K} N={N} M={M} R={R} W={W} U16={use_16bits}\n")
        f.write(f"localparam int TC_K          = {K};\n")
        f.write(f"localparam int TC_N          = {N};\n")
        f.write(f"localparam int TC_M          = {M};\n")
        f.write(f"localparam int TC_R          = {R};\n")
        f.write(f"localparam int TC_W          = {W};\n")
        f.write(f"localparam int TC_BASE_ADDR  = 32'h{BASE_ADDR:08x};\n")
        f.write(f"localparam int TC_ROW_STRIDE = {row_stride};\n")
        f.write(f"localparam int TC_LHS_ZP     = {lhs_zp};\n")
        f.write(f"localparam int TC_USE_16BITS = {use_16bits};\n")
        f.write(f"localparam int TC_HTN        = {HTN};\n")
        f.write(f"localparam int TC_VTN        = {VTN};\n")
        f.write(f"localparam int TC_G2         = {G2};\n")
        f.write(f"localparam int TC_G1         = {G1};\n")
        f.write(f"localparam int TC_R_ACT      = {R_act};\n")
        f.write(f"localparam int TC_TOTAL_SENDS= {total_sends};\n")
        f.write(f"localparam int TC_SRAM_DEPTH = {actual_sram_depth};\n")
        f.write(f"localparam int TC_GRANT_BP_EN = {grant_bp_en};\n")
        f.write(f"localparam int TC_GRANT_BP_CYCLES = {grant_bp_cycles};\n")

    # ── golden.txt ──
    with open(os.path.join(out_dir, "golden.txt"), 'w') as f:
        f.write(f"# Case: {case_name}\n")
        f.write(f"# K={K} N={N} M={M} R={R} W={W} U16={use_16bits} SIZE={SIZE}\n")
        f.write(f"# HTN={HTN} VTN={VTN} G2={G2} G1={G1} R_act={R_act}\n\n")
        cnt = 0
        for l2 in range(G2):
            r_cur = R_act if l2 == G2 - 1 else R
            for l1 in range(G1):
                for w_rep in range(W):
                    for ia in range(r_cur):
                        tile_r = l2 * R + ia
                        tile_c = l1
                        vrows = K - tile_r * SIZE if tile_r == VTN - 1 else SIZE
                        is_first = int(l1 == 0)
                        is_calc_done = int(l1 == G1 - 1)
                        f.write(f"TILE {tile_r} {tile_c} vrows={vrows} "
                                f"is_first={is_first} calc_done={is_calc_done}\n")
                        for row in range(vrows):
                            vals = []
                            for col in range(SIZE):
                                mat_r = tile_r * SIZE + row
                                mat_c = tile_c * SIZE + col
                                if mat_r < K and mat_c < N:
                                    vals.append(ia_matrix[mat_r][mat_c] + lhs_zp)
                                else:
                                    vals.append(0)
                            f.write(f"  ROW {row}: {' '.join(f'{v:6d}' for v in vals)}\n")
                        cnt += 1
                        f.write("\n")
        f.write(f"# Total tiles sent: {cnt}\n")

    # ── params.json ──
    with open(os.path.join(out_dir, "params.json"), 'w') as f:
        json.dump(dict(case=case_name, K=K, N=N, M=M, R=R, W=W,
                       use_16bits=use_16bits, lhs_zp=lhs_zp,
                       HTN=HTN, VTN=VTN, G2=G2, G1=G1, R_act=R_act,
                       total_sends=total_sends, sram_depth=actual_sram_depth,
                       grant_bp_en=grant_bp_en, grant_bp_cycles=grant_bp_cycles),
                  f, indent=2)

    return total_sends


def main():
    parser = argparse.ArgumentParser(description="ia_loader 多 case 测试数据生成器")
    parser.add_argument("--case", type=str, help="预定义 case 名称")
    parser.add_argument("--list", action="store_true", help="列出所有预定义 case")
    parser.add_argument("--all", action="store_true", help="生成所有预定义 case")
    parser.add_argument("--random", action="store_true", help="生成随机 case")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument("--count", type=int, default=5, help="随机 case 数量")
    parser.add_argument("--K", type=int, default=None)
    parser.add_argument("--N", type=int, default=None)
    parser.add_argument("--M", type=int, default=None)
    parser.add_argument("--R", type=int, default=None)
    parser.add_argument("--W", type=int, default=None)
    parser.add_argument("--use_16bits", type=int, choices=[0, 1], default=None,
                        help="数据位宽模式：1=s16, 0=s8")
    parser.add_argument("--out_dir", type=str, default="out", help="输出根目录")
    args = parser.parse_args()

    if args.list:
        print("预定义 case 列表:")
        for name, p in PREDEFINED_CASES.items():
            u16 = int(p.get("use_16bits", DEFAULT_USE_16BITS))
            print(f"  {name:15s}  K={p['K']:3d} N={p['N']:3d} M={p['M']:3d} R={p['R']} W={p['W']} U16={u16}")
        return

    cases_to_run = []

    if args.all:
        for name, p in PREDEFINED_CASES.items():
            cases_to_run.append((name, p))

    if args.random:
        seed = args.seed if args.seed is not None else random.randint(0, 2**31)
        print(f"Random seed: {seed}")
        rng = random.Random(seed)
        for i in range(args.count):
            p = random_params(rng)
            name = f"rand_{seed}_{i}"
            cases_to_run.append((name, p))

    if not args.all and not args.random:
        if args.case:
            if args.case not in PREDEFINED_CASES:
                print(f"ERROR: Unknown case '{args.case}'")
                print(f"Available: {', '.join(PREDEFINED_CASES.keys())}")
                sys.exit(1)
            cases_to_run.append((args.case, PREDEFINED_CASES[args.case]))
        elif args.K is not None:
            p = dict(
                K=args.K,
                N=args.N if args.N else args.K,
                M=args.M if args.M else args.K,
                R=args.R if args.R else 1,
                W=args.W if args.W else 1,
                use_16bits=(args.use_16bits if args.use_16bits is not None else DEFAULT_USE_16BITS),
            )
            cases_to_run.append(("custom", p))
        else:
            # 默认：exact_2x2 单 case
            cases_to_run.append(("exact_2x2", PREDEFINED_CASES["exact_2x2"]))

    # 生成
    multi = len(cases_to_run) > 1
    results = []
    for name, params in cases_to_run:
        case_dir = os.path.join(args.out_dir, name) if multi else args.out_dir
        if args.use_16bits is not None:
            params = dict(params)
            params["use_16bits"] = args.use_16bits
        sends = generate_case(params, case_dir, name)
        results.append((name, params, sends))
        u16 = int(params.get("use_16bits", DEFAULT_USE_16BITS))
        print(f"  [{name:15s}] K={params['K']:3d} N={params['N']:3d} M={params['M']:3d} "
              f"R={params['R']} W={params['W']} U16={u16} → {sends:3d} sends → {case_dir}/")

    # 多 case 时生成 case_list.txt
    if multi:
        list_path = os.path.join(args.out_dir, "case_list.txt")
        with open(list_path, 'w') as f:
            for name, _, _ in results:
                f.write(f"{name}\n")
        print(f"\nCase list: {list_path} ({len(results)} cases)")
    else:
        print(f"Generated: {results[0][0]} ({results[0][2]} sends)")


if __name__ == "__main__":
    main()
