#!/usr/bin/env python3
"""Check C/Python schedule equivalence, resource limits and forced modes."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "veri/top_regression"))
from host_schedule import default_config, plan_schedule, schedules, plan_layout, operand, output_requests


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    lib = a.out / "schedule.so"
    subprocess.run(["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                    "-I", str(ROOT / "drivers"), str(Path(__file__).with_name("schedule_oracle.c")),
                    "-o", str(lib)], check=True)
    dll = ctypes.CDLL(str(lib))
    dll.schedule_oracle.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint64)]
    dll.schedule_oracle.restype = ctypes.c_int
    default = default_config(17, 31, 65, size=16, ia_blocks=8, ps_frames=16)
    raw = (ctypes.c_uint32 * len(default))()
    assert dll.schedule_defaults(raw, len(default)) == 1
    assert list(raw) == list(default.values())
    rng = random.Random(20261116)
    configs = []
    for ia, ps, storage in ((4, 16, 0), (8, 8, 0), (16, 4, 0), (8, 16, 767), (16, 16, 703)):
        for m, n, k in ((1, 64, 784), (17, 17, 17), (36, 128, 128), (144, 64, 64), (1024, 16, 144)):
            for flow in (0, 1, 2):
                configs.append(default_config(m, k, n, ia_blocks=ia, ps_frames=ps,
                    ps_storage_rows=storage, flow=flow, has_bias=1))
    for _ in range(1500):
        m, n, k = [rng.choice((1, 2, 7, 15, 16, 17, 31, 33, 65, 129, 255, 576, 1024, 65535)) for _ in range(3)]
        width = rng.choice((1, 2))
        configs.append(default_config(m, k, n, size=rng.choice((4, 8, 16)),
            ia_blocks=rng.choice((2, 4, 8, 16)), ps_frames=rng.choice((1, 2, 4, 8, 16)),
            ps_storage_rows=rng.choice((0, 32, 300, 703, 767)),
            flow=rng.randrange(3), requested_r=rng.choice((0, 1, 2, 3, 4, 8)),
            requested_w=rng.choice((0, 1, 2, 3, 4, 8, 16)), lhs_bytes=width,
            output_bytes=width, lhs_stride=k * width + rng.randrange(4),
            rhs_stride=k + rng.randrange(4), output_stride=n * width,
            lhs_address=rng.randrange(4), rhs_address=rng.randrange(4),
            output_address=rng.randrange(16) * 16, allow_is=rng.randrange(2),
            per_channel=rng.randrange(2), has_bias=rng.randrange(2), spatial=rng.randrange(2)))
    for m, n, k in ((1, 10, 64), (17, 17, 17), (36, 128, 128), (64, 64, 576), (144, 64, 64)):
        for lhs_packed, rhs_packed in ((0, 1), (1, 0), (1, 1)):
            for flow in (0, 1, 2):
                for width in (1, 2):
                    configs.append(default_config(m, k, n, ia_blocks=8, ps_frames=16,
                        ps_storage_rows=799, flow=flow, lhs_tile_packed=lhs_packed,
                        rhs_tile_packed=rhs_packed, lhs_bytes=width, rhs_bytes=width,
                        output_bytes=width, lhs_stride=k*width, rhs_stride=k*width,
                        output_banks_s8=32, output_banks_s16=4))
    output_merge_configs = []
    for r in (1, 2, 4, 8, 16):
        for lhs_width in (1, 2):
            for address, stride_extra, channel_tail, banks, output_width in (
                (4096, 0, 0, 32, 1), (4096 + 16, 0, 0, 32, 1),
                (4096, 16, 0, 32, 1), (4096, 0, -1, 32, 1),
                (4096, 0, 0, 1, 1), (4096, 0, 0, 32, 2)):
                n = 16 * r + channel_tail
                cfg = default_config(17, 17, n, ia_blocks=max(2, 2*r),
                    ps_frames=16, ps_storage_rows=799, flow=1, requested_r=r,
                    requested_w=1, lhs_bytes=lhs_width, lhs_stride=17*lhs_width,
                    output_bytes=output_width, output_address=address,
                    output_stride=n*output_width+stride_extra,
                    output_banks_s8=banks, output_banks_s16=16)
                output_merge_configs.append(cfg)
                configs.append(cfg)
    passed = invalid = 0
    for cfg in configs:
        data = (ctypes.c_uint32 * len(cfg))(*cfg.values())
        values = (ctypes.c_uint64 * 15)()
        rc = dll.schedule_oracle(data, len(cfg), values)
        try:
            result = plan_schedule(cfg)
        except ValueError:
            assert rc == 0, (cfg, rc)
            invalid += 1
            continue
        t = result["tiling"]
        expected = [result["dataflow_mode"], t["ia_reuse"], t["w_reuse"], t["row_groups"],
                    t["row_tail_tiles"], t["col_groups"], t["col_tail_tiles"], result["candidates"],
                    result["estimated_cycles"], result["read_words"], result["read_requests"],
                    result["write_words"], result["write_requests"], result["compute_cycles"], result["ps_payload_bytes"]]
        assert rc == 1 and list(values) == expected, (cfg, list(values), expected)
        for candidate in schedules(cfg):
            tile = candidate["tiling"]
            sr, sc = (cfg["cols"], cfg["rows"]) if candidate["dataflow_mode"] else (cfg["rows"], cfg["cols"])
            tr, tc = (sr + cfg["size"] - 1) // cfg["size"], (sc + cfg["size"] - 1) // cfg["size"]
            assert (tile["row_groups"] - 1) * tile["ia_reuse"] + tile["row_tail_tiles"] == tr
            assert (tile["col_groups"] - 1) * tile["w_reuse"] + tile["col_tail_tiles"] == tc
            if cfg["flow"] != 2:
                assert candidate["dataflow_mode"] == cfg["flow"]
            if cfg["ps_storage_rows"]:
                assert candidate["ps_payload_bytes"] <= cfg["ps_storage_rows"] * cfg["size"] * 4
        passed += 1
    for cfg in output_merge_configs:
        for candidate in schedules(cfg):
            r = candidate["tiling"]["ia_reuse"]
            merged = (r in (2, 4, 8, 16) and r <= cfg["output_banks_s8"] and
                      cfg["output_bytes"] == 1 and cfg["cols"] % (16*r) == 0 and
                      cfg["output_address"] % (16*r) == 0 and
                      cfg["output_stride"] % (16*r) == 0)
            columns_per_request = 16*r if merged else 16
            expected = cfg["rows"] * ((cfg["cols"]+columns_per_request-1)//columns_per_request)
            assert candidate["write_requests"] == expected, (cfg, candidate, expected)
    dll.write_requests_oracle.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t,
                                          ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    dll.write_requests_oracle.restype = ctypes.c_uint64
    output_burst_cases = 0
    for m, n, r, w, chunk in ((1, 256, 1, 16, 16), (2, 256, 1, 16, 2),
            (9, 256, 1, 16, 2), (15, 64, 1, 4, 2), (17, 64, 2, 4, 4),
            (36, 128, 4, 8, 8), (64, 64, 4, 4, 4), (65, 128, 4, 8, 8),
            (79, 256, 4, 16, 8), (128, 512, 4, 16, 8)):
        for address in (0, 1, 2, 3, 64, 128, 4093, 4095):
            cfg = default_config(m, 32, n, ia_blocks=8, ps_frames=16,
                                 output_address=address, output_banks_s8=32)
            expected = 0
            for row in range(0, m, 16*r):
                count = min(16*r, m-row)
                for col in range(0, n, 16*chunk):
                    if n == 16*chunk:
                        total = count*n
                        length = next((v for v in (1024, 512, 256) if total % v == 0), n)
                        descriptors = [(address+row*n+i, length) for i in range(0, total, length)]
                    else:
                        descriptors = [(address+(row+i)*n+col, 16*chunk) for i in range(count)]
                    for start, length in descriptors:
                        word_address = start & ~3
                        words = (start % 4 + length + 3)//4
                        while words:
                            beats = min(words, 256, (4096-word_address % 4096)//4)
                            assert beats > 0
                            expected += 1
                            words -= beats
                            word_address += beats*4
            raw_config = (ctypes.c_uint32 * len(cfg))(*cfg.values())
            assert output_requests(cfg, 0, r, w) == expected, (cfg, r, w, expected)
            assert dll.write_requests_oracle(raw_config, len(cfg), 0, r, w) == expected
            output_burst_cases += 1
    tail_read_cases = 0
    for width in (1, 2):
        for depth in (1, 3, 7, 9, 15, 17, 19, 27, 31):
            for residue in range(4):
                cfg = default_config(1, depth, 1)
                words, requests = operand(cfg, 1, width, depth*width, residue, False, False)
                full, tail = divmod(depth, 16)
                expected = full*(4*width + int(residue != 0))
                if tail:
                    expected += (tail*width+3)//4 + int(residue != 0)
                assert (words, requests) == (expected, full+int(tail != 0))
                tail_read_cases += 1
    config = default_config(784, 9, 8, ia_blocks=8, ps_frames=16,
                            ps_storage_rows=799, flow=1, has_bias=1)
    assert plan_schedule(config)["read_words"] == 3068
    dll.layout_oracle.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t,
                                 ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64)]
    dll.layout_oracle.restype = ctypes.c_int
    layout_cases = 0
    for cfg in configs:
        for may_pack in (0, 2, 3):
            data = (ctypes.c_uint32 * len(cfg))(*cfg.values())
            values = (ctypes.c_uint64 * 8)()
            rc = dll.layout_oracle(data, len(cfg), may_pack, values)
            try:
                result = plan_layout(cfg, may_pack)
            except ValueError:
                assert rc == 0
                continue
            expected = [result["layout_flags"], result["dataflow_mode"],
                        result["tiling"]["ia_reuse"], result["tiling"]["w_reuse"],
                        result["estimated_cycles"], result["read_words"], result["read_requests"], result["candidates"]]
            assert rc == 1 and list(values) == expected, (cfg, may_pack, list(values), expected)
            layout_cases += 1
    dll.packed_bytes_oracle.argtypes = [ctypes.c_uint32] * 3
    dll.packed_bytes_oracle.restype = ctypes.c_uint32
    dll.pack_oracle.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p] + [ctypes.c_uint32] * 4
    dll.pack_oracle.restype = ctypes.c_int
    packing_cases = 0
    for rows in (1, 7, 15, 16, 17, 31, 33):
        for depth in (1, 9, 15, 16, 17, 27, 32, 65):
            for width in (1, 2):
                for padding in (0, 3):
                    stride = depth * width + padding
                    source = bytes(rng.randrange(256) for _ in range(rows * stride))
                    expected_size = ((rows + 15) // 16) * ((depth + 15) // 16) * 256 * width
                    assert dll.packed_bytes_oracle(rows, depth, width) == expected_size
                    src = (ctypes.c_uint8 * len(source)).from_buffer_copy(source)
                    storage = (ctypes.c_uint8 * (expected_size + 32))(*([0xa5] * (expected_size + 32)))
                    out = ctypes.c_void_p(ctypes.addressof(storage) + 16)
                    assert dll.pack_oracle(out, expected_size, src, rows, depth, stride, width) == 1
                    expected = bytearray(expected_size)
                    for r in range(rows):
                        for k in range(depth):
                            index = (((r // 16) * ((depth + 15) // 16) + k // 16) * 256 + (r % 16) * 16 + k % 16) * width
                            expected[index:index+width] = source[r*stride+k*width:r*stride+(k+1)*width]
                    assert bytes(storage[16:-16]) == expected
                    assert bytes(storage[:16]) == bytes([0xa5] * 16) == bytes(storage[-16:])
                    assert bytes(src) == source
                    assert dll.pack_oracle(out, expected_size - 1, src, rows, depth, stride, width) == 0
                    assert dll.pack_oracle(src, expected_size, src, rows, depth, stride, width) == 0
                    packing_cases += 1
    for dimensions in ((0, 1, 1), (1, 0, 1), (1, 1, 3), (0xffffffff, 0xffffffff, 1), (65536, 65536, 1)):
        assert dll.packed_bytes_oracle(*dimensions) == 0
    result = dict(passed=True, configurations=len(configs), legal=passed, rejected=invalid,
                  output_burst_cases=output_burst_cases,
                  packing_cases=packing_cases, layout_cases=layout_cases,
                  output_merge_configurations=len(output_merge_configs),
                  tail_read_cases=tail_read_cases,
                  source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (ROOT / "drivers/dsa_schedule.h", ROOT / "drivers/dsa_matrix.h", ROOT / "veri/top_regression/host_schedule.py")})
    (a.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
