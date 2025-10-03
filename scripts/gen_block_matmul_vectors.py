#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 4x16 (A) 与 16x4 (B) 的测试数据，tile_size=4。
- data/*.txt：可读矩阵与分块、部分和参考
- sim/mem/*.memh：仿真中用 $readmemh 读取的逐行打包数据
  weight_T.memh: 对应第 T 个 4x4 权重分块(来自 B 的行)
  ia_T.memh:     对应第 T 个 4x4 IA 分块(来自 A 的列块)
  oa_expected.memh: 最终 4x4 结果的每行打包
打包规则：每行4个16-bit有符号，按 [elem3 elem2 elem1 elem0] 高到低拼接，共64-bit，行为一行十六进制。
"""

import os
import random
from typing import List

BASE = "/home/etc/FPGA/tflm_ai_dsa"
DATA_DIR = os.path.join(BASE, "data")
MEM_DIR = os.path.join(BASE, "sim", "mem")

TILE = 4
M = 4   # 输出行数 / A 的行
N = 4   # 输出列数 / B 的列
K = 16  # 共享维度
ELEM_W = 16
KTILES = K // TILE

random.seed(2025)


def gen_matrix(rows: int, cols: int, lo: int = -3, hi: int = 3) -> List[List[int]]:
    return [[random.randint(lo, hi) for _ in range(cols)] for _ in range(rows)]


def matmul(A: List[List[int]], B: List[List[int]]) -> List[List[int]]:
    m, k = len(A), len(A[0])
    k2, n = len(B), len(B[0])
    assert k == k2
    C = [[0 for _ in range(n)] for _ in range(m)]
    for i in range(m):
        for p in range(k):
            a = A[i][p]
            bp = B[p]
            for j in range(n):
                C[i][j] += a * bp[j]
    return C


def write_txt(path: str, mat: List[List[int]]):
    with open(path, "w", encoding="utf-8") as f:
        for row in mat:
            f.write(" ".join(str(x) for x in row) + "\n")


def twos(value: int, bits: int) -> int:
    return value & ((1 << bits) - 1)


def pack_row_4x16b(row4: List[int]) -> str:
    assert len(row4) == 4
    parts = [twos(v, ELEM_W) for v in row4]
    # 高位在左：elem3 .. elem0
    word = 0
    for idx in range(4):
        word = (word << ELEM_W) | parts[3 - idx]
    return f"{word:016x}"


def write_memh_rows(path: str, rows: List[List[int]]):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(pack_row_4x16b(row) + "\n")


def slice_A_tile(A: List[List[int]], t: int) -> List[List[int]]:
    c0 = t * TILE
    return [r[c0:c0 + TILE] for r in A]


def slice_B_tile(B: List[List[int]], t: int) -> List[List[int]]:
    r0 = t * TILE
    return [B[r] for r in range(r0, r0 + TILE)]


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MEM_DIR, exist_ok=True)

    # 生成 A(4x16), B(16x4)
    A = gen_matrix(M, K)
    B = gen_matrix(K, N)

    # 期望结果 OA(4x4)
    OA = matmul(A, B)

    # 导出可读文本
    write_txt(os.path.join(DATA_DIR, "A_full.txt"), A)
    write_txt(os.path.join(DATA_DIR, "B_full.txt"), B)
    write_txt(os.path.join(DATA_DIR, "expected_OA.txt"), OA)

    # 按 K 维切分 4 个 tile，导出分块与部分和
    for t in range(KTILES):
        A_tile = slice_A_tile(A, t)            # 4x4
        B_tile = slice_B_tile(B, t)            # 4x4 (行为行)
        # 将 B_tile 转置成 4x4 列优矩阵以便计算部分和：A_tile(4x4) @ B_tile(4x4)
        # 这里 B_tile 已经是4行x4列的视图
        partial = matmul(A_tile, B_tile)

        write_txt(os.path.join(DATA_DIR, f"A_tile_{t}.txt"), A_tile)
        write_txt(os.path.join(DATA_DIR, f"B_tile_{t}.txt"), B_tile)
        write_txt(os.path.join(DATA_DIR, f"partial_{t}.txt"), partial)

        # .memh 逐行打包：
        # 权重来自 B_tile 的每一行
        write_memh_rows(os.path.join(MEM_DIR, f"weight_{t}.memh"), B_tile)
        # IA 来自 A_tile 的每一行
        write_memh_rows(os.path.join(MEM_DIR, f"ia_{t}.memh"), A_tile)

    # OA 结果行打包
    write_memh_rows(os.path.join(MEM_DIR, "oa_expected.memh"), OA)

    print("Test data generated:")
    print(f"  A: {M}x{K}, B: {K}x{N}, TILE={TILE}, KTILES={KTILES}")
    print(f"  Text: {DATA_DIR}")
    print(f"  Memh: {MEM_DIR}")


if __name__ == "__main__":
    main()
