#!/usr/bin/env python3
"""Check saved-K frame scheduling through the shared NPU and im2col path."""
import argparse
import importlib.util
import json
from pathlib import Path

from run_shared_npu import validated_binary

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("conv_npu_run", ROOT / "test/conv_npu/run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def configure(directory, r, w, control=0):
    path = directory / "config.mem"
    cfg = [int(word, 16) for word in path.read_text().split()]
    sr, sc = (cfg[5], cfg[3]) if cfg[8] else (cfg[3], cfg[5])
    tr, tc = (sr + 15) // 16, (sc + 15) // 16
    cfg[6], cfg[7] = r, w
    cfg[30] = ((tr + r - 1) // r) | (((tc + w - 1) // w) << 16)
    cfg[31] = ((tr - 1) % r + 1) | (((tc - 1) % w + 1) << 16)
    cfg[61] = control
    path.write_text("".join(f"{value:08x}\n" for value in cfg))
    metadata_path = directory / "case.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.update(requested_r=r, requested_w=w, ps_control=control)
    metadata["tiling"] = dict(ia_reuse=r, w_reuse=w,
        row_groups=cfg[30] & 65535, col_groups=cfg[30] >> 16,
        row_tail_tiles=cfg[31] & 65535, col_tail_tiles=cfg[31] >> 16)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return directory


def set_boundary_bias(directory, enabled=True):
    """Exercise final INT32 addition and the S16 output conversion."""
    cfg = [int(word, 16) for word in (directory / "config.mem").read_text().split()]
    image = runner.load_sparse(directory / "init.mem")
    values = (-2147483648, 2147483647, -8388608, 8388607, -65536, 65535, -1, 0)
    if enabled:
        for channel in range(cfg[5]):
            start = cfg[16] + 4 * channel
            image[start:start + 4] = (values[channel % len(values)] & 0xffffffff).to_bytes(4, "little")
    else:
        cfg[16] = 0
    accumulators = runner.gemm_accumulators(cfg, image)
    golden = bytearray(image)
    width = 2 if cfg[28] else 1
    for index, value in enumerate(accumulators):
        channel = index % cfg[5]
        multiplier = int.from_bytes(image[cfg[24] + 4 * channel:cfg[24] + 4 * channel + 4],
                                    "little", signed=True) if cfg[13] else runner.signed32(cfg[24])
        shift = int.from_bytes(image[cfg[25] + 4 * channel:cfg[25] + 4 * channel + 4],
                              "little", signed=True) if cfg[13] else runner.signed32(cfg[25])
        scaled = (runner.nmsis_nn_requantize_s64(value, multiplier, shift) if cfg[28]
                  else runner.cmsis_nn_requantize(value, multiplier, shift))
        quantized = max(runner.signed32(cfg[26]), min(runner.signed32(cfg[27]),
                        scaled + runner.signed32(cfg[23])))
        address = cfg[17] + (index // cfg[5]) * cfg[20] + channel * width
        golden[address:address + width] = quantized.to_bytes(width, "little", signed=True)
    runner.sparse_mem(directory / "init.mem", image)
    runner.sparse_mem(directory / "golden.mem", golden)
    runner.accumulator_mem(directory / "acc.mem", accumulators)
    (directory / "config.mem").write_text("".join(f"{value:08x}\n" for value in cfg))
    metadata_path = directory / "case.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.update(bias_values=list(values) if enabled else [],
                    acc_min=min(accumulators), acc_max=max(accumulators))
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return directory


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    tasks = []
    profiles = [
        ("raw_ws_s8", 0, False, False, 65, 37, 19, 4, 1),
        ("raw_ws_s16", 0, True, False, 35, 37, 29, 2, 2),
        ("frame_ws_s8", 0, False, False, 35, 37, 69, 4, 2),
        ("frame_is_s8", 1, False, False, 69, 37, 35, 4, 2),
        ("frame_ws_s16", 0, True, False, 29, 37, 81, 2, 4),
        ("frame_is_s16", 1, True, False, 81, 37, 55, 4, 3),
        ("frame_output_s16", 0, True, True, 29, 37, 81, 2, 4),
        ("frame_raw_w3", 0, False, False, 29, 37, 65, 1, 3),
    ]
    for name, mode, wide, out16, rows, red, cols, r, w in profiles:
        directory = runner.precision_task(out, 16, name=name, dataflow=mode,
            lhs_s16=wide, output_s16=out16, rows=rows, reduction=red, columns=cols)
        tasks.append(configure(directory, r, w))
    for name, mode, rows, cols, r, w, control in (
        ("raw_frame_group_ws", 0, 61, 65, 2, 1, 3),
        ("raw_frame_group_is", 1, 33, 65, 4, 1, 3),
        ("raw_frame_pressure", 0, 61, 65, 4, 4, 3),
        ("frame_slice32_is", 1, 81, 55, 4, 3, 10),
    ):
        directory = runner.precision_task(out, 16, name=name, dataflow=mode,
            lhs_s16=False, rows=rows, reduction=37, columns=cols)
        tasks.append(configure(directory, r, w, control))
    reference = runner.make_reference(out)
    for mode, r, w in ((0, 4, 2), (1, 4, 3)):
        directory = runner.task(out, 16, reference, name=f"frame_conv_{mode}",
            h=7, w=7, c=3, kh=3, kw=3, co=65, dataflow=mode)
        tasks.append(configure(directory, r, w))
    directory = runner.task(out, 16, reference, name="raw_frame_conv_ws",
        h=7, w=7, c=3, kh=3, kw=3, co=65, dataflow=0)
    tasks.append(configure(directory, 2, 1, 3))
    for name, wide, out16, rows, red, cols, r, w, control, enabled in (
        ("bias_boundary_ws_long", False, False, 65, 37, 81, 4, 2, 1, True),
        ("bias_boundary_ws_frame", False, False, 61, 65, 65, 4, 4, 14, True),
        ("bias_boundary_s16_long", True, False, 35, 37, 81, 2, 4, 1, True),
        ("bias_boundary_s16_output", True, True, 31, 37, 49, 2, 3, 15, True),
        ("bias_boundary_single_k", False, False, 35, 16, 49, 4, 4, 1, True),
        ("bias_absent_ws_frame", False, False, 61, 65, 65, 4, 4, 14, False),
    ):
        directory = runner.precision_task(out, 16, name=name, dataflow=0,
            lhs_s16=wide, output_s16=out16, rows=rows, reduction=red, columns=cols)
        tasks.append(set_boundary_bias(configure(directory, r, w, control), enabled))
    for mode in (0, 1):
        rows, columns = (33, 65) if mode == 0 else (65, 33)
        directory = runner.precision_task(out, 16, name=f"bias_boundary_auto_{mode}", dataflow=mode,
            lhs_s16=False, rows=rows, reduction=65, columns=columns)
        tasks.append(set_boundary_bias(configure(directory, 4, 4)))
    return tasks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/frame_integration")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--pool-bytes", type=int, default=12288)
    args = parser.parse_args()
    out = args.out.resolve()
    tasks = generate(out / "cases")
    if args.binary:
        binary = validated_binary(args.binary.resolve().parent.parent)
        if binary != args.binary.resolve() or args.pool_bytes != 12288:
            parser.error("--binary requires the 14 KiB shared-memory simulator and a 12288-byte initial PS pool")
    else:
        binary = runner.build(out / "npu", 16, "verilator", args.jobs,
                              ps_compress=True, pool_bytes=args.pool_bytes)
    results = []
    for random_wait in (False, True):
        result = runner.run_suite(binary, out, "random" if random_wait else "fixed",
                                  tasks, no_random=not random_wait)
        results.append(result)
        if not result["passed"]:
            break
    summary = dict(passed=all(result["passed"] for result in results),
                   expected_cases=2 * len(tasks),
                   completed_cases=sum(len(result["measurements"]) for result in results),
                   int32_checks=sum(row["int32_checks"] for result in results
                                    for row in result["measurements"]), suites=results)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("FRAME_NPU_RESULT", summary["passed"], summary["completed_cases"],
          summary["int32_checks"], flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
