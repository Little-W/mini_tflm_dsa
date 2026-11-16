"""WS/IS schedule cost model shared in definition with drivers/dsa_schedule.h."""
from __future__ import annotations


LIMIT64 = (1 << 64) - 1


def add(a, b):
    return min(LIMIT64, a + b)


def mul(a, b):
    return min(LIMIT64, a * b)


def ceildiv(a, b):
    return (a + b - 1) // b


def default_config(rows, depth, cols, size=16, ia_blocks=4, ps_frames=16, **options):
    config = dict(rows=rows, depth=depth, cols=cols, size=size, ia_blocks=ia_blocks,
                  ps_frames=ps_frames, ps_storage_rows=0, ps_pool_bytes=0, flow=2,
                  requested_r=0, requested_w=0, lhs_bytes=1, rhs_bytes=1, output_bytes=1,
                  lhs_stride=depth, rhs_stride=depth, output_stride=cols,
                  lhs_address=0, rhs_address=0, output_address=0, allow_is=1,
                  per_channel=0, has_bias=0, spatial=0, read_beat_cycles=2,
                  write_beat_cycles=1, read_request_cycles=1, write_request_cycles=3,
                  merge_contiguous_rows=1, lhs_tile_packed=0, rhs_tile_packed=0,
                  output_banks_s8=0, output_banks_s16=0)
    unknown = options.keys() - config.keys()
    if unknown:
        raise ValueError("Unknown schedule options: " + str(unknown))
    config.update(options)
    return config


def operand(c, rows, width, stride, address, merge, packed):
    size, depth = c["size"], c["depth"]
    if packed:
        kt, row_bytes = ceildiv(depth, size), size * width
        return rows * kt * row_bytes // 4, kt * ((rows // size) * ceildiv(size * row_bytes, 1024) + ceildiv((rows % size) * row_bytes, 1024))
    if merge and c["merge_contiguous_rows"] and depth <= size and stride == depth * width and size * depth * width <= 1024 and depth * width % 4 == 0 and address % 4 == 0:
        row_bytes = depth * width
        block_bytes = size * row_bytes
        tail_bytes = (rows % size) * row_bytes
        return add(mul(rows, row_bytes), 3) // 4, (rows // size) * ceildiv(block_bytes, 1024) + ceildiv(tail_bytes, 1024)
    full, tail = divmod(depth, size)
    words = 0
    for i in range(4):
        times = rows // 4 + (i < rows % 4)
        residue = (address + i * stride) % 4
        per_row = full * ceildiv(size * width + residue, 4)
        if tail:
            per_row += ceildiv(tail * width, 4) + int(residue != 0)
        words = add(words, mul(times, per_row))
    return words, rows * (full + bool(tail))


def contiguous_writes(address, byte_count, descriptor_bytes):
    if not byte_count:
        return 0
    requests = byte_count // descriptor_bytes
    if descriptor_bytes == 1024 and address % 4:
        return 2 * requests
    if address % descriptor_bytes:
        requests += (address + byte_count - 1) // 4096 - address // 4096
    return requests


def dense_write_bytes(group_bytes, row_bytes):
    return next((n for n in (1024, 512, 256) if group_bytes % n == 0), row_bytes)


def output_requests(c, mode, r, w):
    rows, cols, size = c["rows"], c["cols"], c["size"]
    banks = c["output_banks_s8"] or min(32, c["ps_frames"] * max(1, c["ia_blocks"] // 2))
    chunk = 1
    if (not mode and c["allow_is"] and size == 16 and c["output_bytes"] == 1 and
            r <= 16 and c["output_stride"] == cols):
        row_tiles = min(r, ceildiv(rows, 16))
        if 1 < rows < 16 and w >= 2 and cols >= 32 and banks >= 2:
            chunk = 2
        else:
            for x in (2, 4, 8, 16):
                if x <= w and row_tiles * x <= banks and cols >= 16 * x:
                    chunk = x
        if chunk >= 2 and cols % (16 * chunk) == 0:
            if cols == 16 * chunk:
                full_rows = rows // (16 * r) * (16 * r)
                full_bytes, tail_bytes = full_rows * cols, (rows - full_rows) * cols
                return (contiguous_writes(c["output_address"], full_bytes, dense_write_bytes(16*r*cols, cols)) +
                        contiguous_writes(c["output_address"] + full_bytes, tail_bytes, dense_write_bytes(tail_bytes, cols)))
            return contiguous_writes(c["output_address"], rows * cols, 16 * chunk)
        chunk = 1
    if (mode and size == 16 and c["output_bytes"] == 1 and r in (2, 4, 8, 16) and
            r <= banks and cols % (16*r) == 0 and c["output_address"] % (16*r) == 0 and
            c["output_stride"] % (16*r) == 0):
        chunk = r
    return rows * ceildiv(cols, size * chunk)


def schedules(c):
    if any(not isinstance(v, int) or v < 0 or v > 0xffffffff for v in c.values()):
        raise ValueError("Schedule fields must be unsigned 32-bit integers")
    if (min(c[x] for x in ("rows", "depth", "cols", "size", "ia_blocks", "ps_frames", "read_beat_cycles", "write_beat_cycles")) == 0 or
            c["size"] & (c["size"] - 1) or c["size"] > 256 or c["flow"] > 2 or
            any(c[x] not in (1, 2) for x in ("lhs_bytes", "rhs_bytes", "output_bytes")) or
            c["per_channel"] > 1 or c["has_bias"] > 1 or
            c["lhs_tile_packed"] > 1 or c["rhs_tile_packed"] > 1 or
            ((c["lhs_tile_packed"] or c["rhs_tile_packed"]) and c["size"] != 16) or
            (c["spatial"] and c["lhs_tile_packed"]) or (c["flow"] == 1 and not c["allow_is"])):
        raise ValueError("Invalid schedule configuration")
    rows, depth, cols, size = (c[x] for x in ("rows", "depth", "cols", "size"))
    rcap = max(1, c["ia_blocks"] // 2)
    wcap = c["ps_frames"]
    if c["requested_r"]:
        rcap = min(rcap, c["requested_r"])
    if c["requested_w"]:
        wcap = min(wcap, c["requested_w"])
    aw, ar = operand(c, rows, c["lhs_bytes"], c["lhs_stride"], c["lhs_address"], not c["spatial"], c["lhs_tile_packed"])
    bw, br = operand(c, cols, c["rhs_bytes"], c["rhs_stride"], c["rhs_address"], True, c["rhs_tile_packed"])
    for mode in (0, 1):
        if c["flow"] != 2 and c["flow"] != mode or mode and not c["allow_is"]:
            continue
        sr, sc = (cols, rows) if mode else (rows, cols)
        tr, tc, kt = ceildiv(sr, size), ceildiv(sc, size), ceildiv(depth, size)
        for r in [1 << i for i in range(16)] + [25]:
            if (r > rcap or r > tr and r // 2 >= tr or
                    c["output_bytes"] == 2 and c["output_banks_s16"] and r > c["output_banks_s16"]):
                continue
            for w in [1 << i for i in range(16)] + [25]:
                if w > wcap or w > tc and w // 2 >= tc:
                    continue
                rg, cg = ceildiv(tr, r), ceildiv(tc, w)
                if max(rg, cg) > 65535:
                    continue
                payload = 0 if depth <= size else (min(r, tr) * size + size - 1) * (min(w, tc) + 1) * size * 4
                if (c["ps_storage_rows"] and payload > c["ps_storage_rows"] * size * 4 or
                        c["ps_pool_bytes"] and payload > c["ps_pool_bytes"]):
                    continue
                ap, bp = (rg, cg) if mode else (cg, rg)
                pp = 1 if mode or cols <= size else rg
                tables = c["has_bias"] + 2 * c["per_channel"]
                read_words = add(add(mul(aw, ap), mul(bw, bp)), cols * pp * tables)
                read_requests = add(add(mul(ar, ap), mul(br, bp)), ceildiv(cols, 16) * pp * tables)
                write_words = rows * ceildiv(cols * c["output_bytes"], 4)
                write_requests = output_requests(c, mode, r, w)
                compute_cycles = add(mul(sr * tc, kt), mul(mul(rg * tc, kt), 2 * size + 2))
                read_cycles = add(mul(read_words, c["read_beat_cycles"]), mul(read_requests, c["read_request_cycles"]))
                write_cycles = add(mul(write_words, c["write_beat_cycles"]), mul(write_requests, c["write_request_cycles"]))
                yield dict(dataflow_mode=mode, tiling=dict(ia_reuse=r, w_reuse=w, row_groups=rg,
                    col_groups=cg, row_tail_tiles=tr - (rg - 1) * r, col_tail_tiles=tc - (cg - 1) * w),
                    estimated_cycles=max(read_cycles, write_cycles, compute_cycles), read_words=read_words,
                    read_requests=read_requests, write_words=write_words, write_requests=write_requests,
                    compute_cycles=compute_cycles, ps_payload_bytes=payload)


def schedule_key(candidate):
    return tuple(candidate[key] for key in ("estimated_cycles", "read_words", "read_requests",
        "compute_cycles", "write_requests", "ps_payload_bytes", "dataflow_mode"))


def plan_schedule(c):
    choices = list(schedules(c))
    if not choices:
        raise ValueError("No legal schedule fits the physical capacities")
    best = min(choices, key=schedule_key)
    return dict(best, candidates=len(choices))


def plan_layout(c, may_pack=3):
    if may_pack not in range(4):
        raise ValueError("Packing mask must use only lhs/rhs bits")
    required = c["lhs_tile_packed"] | (c["rhs_tile_packed"] << 1)
    choices = []
    for flags in range(4):
        if flags & required != required or flags & ~(may_pack | required):
            continue
        config = dict(c, lhs_tile_packed=flags & 1, rhs_tile_packed=(flags >> 1) & 1)
        if flags & 1:
            config["lhs_address"] = 0
        if flags & 2:
            config["rhs_address"] = 0
        try:
            candidate = plan_schedule(config)
        except ValueError:
            continue
        choices.append(dict(candidate, layout_flags=flags))
    if not choices:
        raise ValueError("No layout and schedule fits the physical capacities")
    best = min(choices, key=schedule_key)
    return dict(best, candidates=sum(x["candidates"] for x in choices))
