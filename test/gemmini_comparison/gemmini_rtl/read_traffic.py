"""Read transactions for the pinned 16x16 INT8 Gemmini command paths.

Explicit mvin commands, including OS software grouping, retain their encoded
column counts. WS loop expansion uses the hardware DMA maximum independently
of the software header's MAX_BYTES constant.
"""
from functools import lru_cache


@lru_cache(maxsize=None)
def row_packets(address_mod_max, length, dma_max_bytes=64):
    if (not isinstance(dma_max_bytes, int) or dma_max_bytes < 4 or
            dma_max_bytes > 1024 or dma_max_bytes & (dma_max_bytes - 1)):
        raise ValueError("Hardware DMA maximum must be a power of two from 4 to 1024 bytes")
    if length < 0:
        raise ValueError("Read length must be nonnegative")
    transferred = requests = 0
    while length:
        choices = [(min(size - address_mod_max % size, length), size)
                   for size in (1 << power for power in range(2, dma_max_bytes.bit_length()))]
        useful, size = max(choices, key=lambda value: (value[0], -value[1]))
        transferred += size
        requests += 1
        address_mod_max = (address_mod_max + useful) % dma_max_bytes
        length -= useful
    return transferred, requests


def command_read_traffic(records, dma_max_bytes=64):
    """Expand WS hardware loops and explicitly encoded software loads."""
    row_packets(0, 0, dma_max_bytes)
    max_block_len = max(1, dma_max_bytes // 16)
    max_block_len_acc = max(1, dma_max_bytes // (16 * 4))
    total_bytes = total_requests = 0
    load_strides = [None] * 3
    load_shrink = [False] * 3
    bounds = addresses_ab = addresses_dc = strides_ab = strides_dc = None

    def load_rows(address, columns, rows, stride, width):
        nonlocal total_bytes, total_requests
        if address == 0:
            return
        for row in range(1 if stride == 0 else rows):
            transferred, requests = row_packets((address + row * stride) % dma_max_bytes,
                                                columns * width, dma_max_bytes)
            total_bytes += transferred
            total_requests += requests

    for record in records:
        if record.get("fence"):
            continue
        funct, rs1, rs2 = (record[key] for key in ("funct", "rs1", "rs2"))
        if funct == 0 and rs1 & 3 == 1:
            state = (rs1 >> 3) & 3
            load_strides[state] = rs2
            load_shrink[state] = bool(rs1 & 4)
        elif funct in (1, 2, 14):
            state = {2: 0, 1: 1, 14: 2}[funct]
            stride = load_strides[state]
            if stride is None:
                raise ValueError("Load without its official stride configuration")
            width = 4 if rs2 & (1 << 31) and not load_shrink[state] else 1
            load_rows(rs1, (rs2 >> 32) & 65535, (rs2 >> 48) & 65535, stride, width)
        elif funct == 9:
            bounds = tuple((rs2 >> shift) & 65535 for shift in (0, 16, 32)) + tuple(
                (rs1 >> shift) & 65535 for shift in (0, 16, 32))
        elif funct == 10:
            addresses_ab = rs1, rs2
        elif funct == 11:
            addresses_dc = rs1, rs2
        elif funct == 12:
            strides_ab = rs1, rs2
        elif funct == 13:
            strides_dc = rs1, rs2
        elif funct == 8:
            if rs2 & ~3 or rs2 == 3 or rs1 & 6:
                raise ValueError("Read model requires supported INT8 GEMM with INT32 bias")
            if any(value is None for value in (bounds, addresses_ab, addresses_dc, strides_ab, strides_dc)):
                raise ValueError("Incomplete official WS loop configuration")
            ni, nj, nk, pad_i, pad_j, pad_k = bounds
            a, b = addresses_ab
            d, _ = addresses_dc
            stride_a, stride_b = strides_ab
            stride_d, _ = strides_dc
            if a:
                transposed = bool(rs2 & 1)
                row_count, col_count = (nk, ni) if transposed else (ni, nk)
                row_pad, col_pad = (pad_k, pad_i) if transposed else (pad_i, pad_k)
                for column in range(0, col_count, min(col_count, max_block_len)):
                    blocks = min(col_count - column, max_block_len)
                    columns = blocks * 16 - (col_pad if column + blocks >= col_count else 0)
                    for row in range(row_count):
                        rows = 16 - (row_pad if row + 1 == row_count else 0)
                        load_rows(a + (row * stride_a + column) * 16, columns, rows, stride_a, 1)
            if b:
                transposed = bool(rs2 & 2)
                row_count, col_count = (nj, nk) if transposed else (nk, nj)
                col_pad = pad_k if transposed else pad_j
                # The pinned LoopMatmulLdB issues 16 physical rows per command.
                for row in range(row_count):
                    for column in range(0, col_count, min(col_count, max_block_len)):
                        blocks = min(col_count - column, max_block_len)
                        columns = blocks * 16 - (col_pad if column + blocks >= col_count else 0)
                        load_rows(b + (row * stride_b + column) * 16, columns, 16, stride_b, 1)
            if d:
                for j in range(0, nj, min(nj, max_block_len_acc)):
                    blocks = min(nj - j, max_block_len_acc)
                    columns = blocks * 16 - (pad_j if j + blocks >= nj else 0)
                    for i in range(ni):
                        rows = 16 - (pad_i if i + 1 == ni else 0)
                        load_rows(d + (i * stride_d + j) * 64, columns, rows, stride_d * 4, 4)
        elif funct in (15, 16, 17, 18, 19, 20, 21, 23, 24, 25):
            raise ValueError("Read model is restricted to ordinary GEMM command streams")
    return {"read_bytes": total_bytes, "read_requests": total_requests,
            "read_service_floor_cycles": total_bytes // 2 + total_requests}
