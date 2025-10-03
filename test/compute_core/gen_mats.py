#!/usr/bin/env python3
import numpy as np
import os

SIZE = 4
K = 16


def to_hex(val: int, bits: int) -> str:
    mask = (1 << bits) - 1
    return f"{(int(val) & mask):0{bits // 4}X}"


def main():
    np.random.seed(42)

    # A: 4x16 int16 (IA), B: 16x4 int8 (Weights)
    A = np.random.randint(-8, 8, size=(SIZE, K), dtype=np.int16)
    B = np.random.randint(-8, 8, size=(K, SIZE), dtype=np.int8)
    # Per-output-channel bias (int32)
    bias = np.random.randint(-64, 64, size=(SIZE,), dtype=np.int32)

    # Expected C = A @ B + bias (bias added per output channel)
    C = A.astype(np.int32) @ B.astype(np.int32)
    C += bias  # broadcast over rows, one bias per column

    # Write IA memory: row-major flatten by r (0..3), then k (0..15) -> A[r, k]
    with open("ia_mem.hex", "w") as f:
        for r in range(SIZE):
            for k in range(K):
                f.write(to_hex(int(A[r, k]), 16) + "\n")

    # Write Weights memory: flatten by col c (0..3), then k (0..15) -> B[k, c]
    with open("weight_mem.hex", "w") as f:
        for c in range(SIZE):
            for k in range(K):
                f.write(to_hex(int(B[k, c]), 8) + "\n")

    # Write Bias memory: one 32-bit per output channel c (0..3)
    with open("bias_mem.hex", "w") as f:
        for c in range(SIZE):
            f.write(to_hex(int(bias[c]), 32) + "\n")

    # Write expected outputs: row-major r(0..3), c(0..3), includes bias
    with open("expected_out.hex", "w") as f:
        for r in range(SIZE):
            for c in range(SIZE):
                f.write(to_hex(int(C[r, c]), 32) + "\n")

    # Human-readable dumps
    np.savetxt("A_4x16.txt", A, fmt="%d")
    np.savetxt("B_16x4.txt", B, fmt="%d")
    np.savetxt("C_expected_4x4.txt", C, fmt="%d")
    np.savetxt("bias_1x4.txt", bias, fmt="%d")

    # New: per 4x4 tile inputs and partial sums, plus per-tile mem inits and accumulated results
    tiles = K // SIZE
    os.makedirs("tiles", exist_ok=True)

    for t in range(tiles):
        k0 = t * SIZE
        a_tile = A[:, k0:k0 + SIZE]
        b_tile = B[k0:k0 + SIZE, :]
        p_tile = a_tile.astype(np.int32) @ b_tile.astype(np.int32)

        # Human-readable per-tile inputs and partial
        np.savetxt(f"tiles/tile_{t}_A_4x4.txt", a_tile, fmt="%d")
        np.savetxt(f"tiles/tile_{t}_B_4x4.txt", b_tile, fmt="%d")
        np.savetxt(f"tiles/tile_{t}_partial_4x4.txt", p_tile, fmt="%d")

        # Per-tile IA mem init (hex): row-major flatten by r (0..3), then kk (0..3) -> A[r, k0+kk]
        with open(f"tiles/tile_{t}_ia_mem.hex", "w") as f:
            for r in range(SIZE):
                for kk in range(SIZE):
                    f.write(to_hex(int(A[r, k0 + kk]), 16) + "\n")
        # Per-tile Weights mem init: flatten by col c (0..3), then kk (0..3) -> B[k0+kk, c]
        with open(f"tiles/tile_{t}_weight_mem.hex", "w") as f:
            for c in range(SIZE):
                for kk in range(SIZE):
                    f.write(to_hex(int(B[k0 + kk, c]), 8) + "\n")

    # Accumulated results after each tile (reference for partial_sum_calc_over)
    acc = np.zeros((SIZE, SIZE), dtype=np.int32)
    for t in range(tiles):
        k0 = t * SIZE
        a_tile = A[:, k0:k0 + SIZE]
        b_tile = B[k0:k0 + SIZE, :]
        acc += a_tile.astype(np.int32) @ b_tile.astype(np.int32)
        np.savetxt(f"tiles/acc_after_tile_{t}.txt", acc, fmt="%d")


if __name__ == "__main__":
    main()
