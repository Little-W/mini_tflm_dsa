#!/usr/bin/env python3
import argparse
import os
import struct

# 与tb一致
REGW = 32
WORD_BYTES = 4

LK, LN, LM = 4, 16, 16  # K×N @ N×M = K×M
LHS_BASE  = 0x0000_0000
RHS_BASE  = 0x0000_0400
BIAS_BASE = 0x0000_0800
DST_BASE  = 0x0000_0C00

LHS_ROW_STRIDE_B = LN * 2  # K×N, 16-bit, 每行 N 个元素
RHS_ROW_STRIDE_B = LM * 1  # N×M, 8-bit, 每行 M 个元素
DST_ROW_STRIDE_B = LM * 1  # K×M, 8-bit, 每行 M 个元素

ACT_MIN, ACT_MAX = -128, 127
LHS_ZP, RHS_ZP, DST_ZP = 0, 0, 0
QMUL, QSHIFT = 1, 0

# 小工具
def sign_clip(val, bits):
    mask = (1 << bits) - 1
    if val & (1 << (bits - 1)):
        return val | ~mask
    return val & mask

def sat_s8(v):
    return max(-128, min(127, v))

def pack_words_le(bytearr):
    # 以小端打包 4 字节为一行 hex word
    pad = (-len(bytearr)) % WORD_BYTES
    bytearr = bytearr + bytes([0]*pad)
    words = []
    for i in range(0, len(bytearr), WORD_BYTES):
        w = bytearr[i:i+WORD_BYTES]
        words.append(int.from_bytes(w, byteorder='little', signed=False))
    return words

def write_mem_hex(path, words, total_words=None):
    if total_words is None:
        total_words = len(words)
    with open(path, 'w') as f:
        for i in range(total_words):
            w = words[i] if i < len(words) else 0
            f.write(f"{w:08x}\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_dir", default="out")
    ap.add_argument("--mem_words", type=int, default=4096, help="导出mem镜像的总字数")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    # 构造 A (LK x LN, s16), B (LN x LM, s8 row-major), bias (LM, s32)
    # 给定简单数据：A[k,n] = k+n+1, B[n,m] = (m - n), bias[m] = m
    A = [[(k + n + 1) for n in range(LN)] for k in range(LK)]
    B = [[(m - n) for m in range(LM)] for n in range(LN)]
    bias = [m for m in range(LM)]

    # 准备字节镜像缓冲
    mem_size_bytes = args.mem_words * WORD_BYTES
    img_init = bytearray(mem_size_bytes)
    img_golden = bytearray(mem_size_bytes)

    # 放置 A (s16, K×N)
    for k in range(LK):
        base = LHS_BASE + k * LHS_ROW_STRIDE_B
        for n in range(LN):
            v = sign_clip(A[k][n], 16) & 0xFFFF
            off = base + 2*n
            img_init[off:off+2] = v.to_bytes(2, 'little', signed=False)
    # 放置 B (s8, N×M)
    for n in range(LN):
        base = RHS_BASE + n * RHS_ROW_STRIDE_B
        for m in range(LM):
            v = sign_clip(B[n][m], 8) & 0xFF
            off = base + m
            img_init[off] = v
    # 放置 bias (s32, M 个元素)
    for m in range(LM):
        v = sign_clip(bias[m], 32) & 0xFFFFFFFF
        off = BIAS_BASE + 4*m
        img_init[off:off+4] = v.to_bytes(4, 'little', signed=False)

    # golden 先拷贝 init
    img_golden[:] = img_init

    # 计算 C = A (K×N) @ B (N×M) => (K×M)
    for k in range(LK):
        for m in range(LM):
            acc = 0
            for n in range(LN):
                a = A[k][n] - LHS_ZP
                b = B[n][m] - RHS_ZP
                acc += int(a) * int(b)
            acc += bias[m]  # per-tensor bias
            # 量化（简化：*1 >>0）
            q = acc * QMUL
            if QSHIFT >= 0:
                q = q >> QSHIFT
            else:
                q = q << (-QSHIFT)
            # 加上 DST_ZP
            q += DST_ZP
            # 激活裁剪 + s8 饱和
            q = sat_s8(max(ACT_MIN, min(ACT_MAX, q)))
            # 写入 DST 为 s8 (K×M)
            base = DST_BASE + k * DST_ROW_STRIDE_B
            off = base + m
            img_golden[off] = q & 0xFF

    # 将字节镜像转为 word 列表并输出为 mem
    words_init = pack_words_le(bytes(img_init))
    words_gold = pack_words_le(bytes(img_golden))
    write_mem_hex(os.path.join(args.out_dir, "init.mem"), words_init, args.mem_words)
    write_mem_hex(os.path.join(args.out_dir, "golden.mem"), words_gold, args.mem_words)

    print(f"[gen_mem] Wrote {args.out_dir}/init.mem and golden.mem with {args.mem_words} words.")

if __name__ == "__main__":
    main()
