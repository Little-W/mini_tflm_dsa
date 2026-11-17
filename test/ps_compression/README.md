# Unified PS compression and shared memory tests

These tests exercise the PS store and frame scheduler inside the common NPU
execution path. The complete-model profile has a 16×16 array, seven 2 KiB IA/PS banks,
16 frame descriptors, a 1024-row PS directory, a 4 KiB DMA window cache, and
8 vector PEs. IA and PS access disjoint allocations through independent
interfaces. RAW32 and adaptive modes use the same physical memories.
The initial allocation is 2 KiB for IA and 12 KiB for PS. Each matrix operator
can select one, two, or four IA banks; the remaining banks hold PS data.

## Module and NPU tests

```bash
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator
make shared-memory-structure YOSYS=/path/to/yosys
```

The structure test requires Yosys with `read_slang`. It checks the inferred
synchronous read/write ports, bank dimensions, external PS directory and
FIFO, and external IA delay registers.

The functional suites cover lossless INT32 row coding, frame replacement,
per-bank admission, protected-frame completion, saved K progress, concurrent
IA/PS traffic, compact S8 and S16 data, AXI abort, WS/IS, tails, and invalid
configuration recovery. C++ module tests enable undefined-behavior checks.
The NPU test compares every final INT32 accumulator and output value with
an independently computed result.

The shared NPU suite runs 48 cases. Its directed test configuration uses a
1 KiB im2col cache; the complete-model simulator uses the 4 KiB cache described
above. The packed and frame integration suites reuse the shared NPU executable:

```bash
python3 test/ps_compression/run_shared_npu.py \
  --out build/unified_validation/shared_npu \
  --verilator /path/to/verilator --jobs 3

python3 test/ps_compression/run_packed_shared.py \
  --sim build/unified_validation/shared_npu/sim \
  --out build/unified_validation/packed_shared

python3 test/ps_compression/frame_npu_test.py \
  --binary build/unified_validation/shared_npu/sim/obj/Vtb_conv_npu \
  --out build/unified_validation/frame_npu
```

Packed tests cover LHS, RHS, and both operands, global K strides, partial
tiles, Conv weights, and random AXI waiting. The frame tests include extreme
bias values, absent bias, S16 input/output, single reduction tiles, and final-K
bias addition. Packed and frame integration run 32 and 46 cases respectively,
including fixed and randomized AXI timing.

## Complete model comparison

Use the prepared models and references described in
[`test/model_benchmark`](../model_benchmark/README.md). A RISC-V RV32IM C/C++
toolchain and the pinned PicoRV32 source are required.

```bash
export PICORV32_ROOT=/path/to/picorv32
python3 test/ps_compression/run_soc.py \
  --out build/unified_validation/soc \
  --prepared /path/to/prepared \
  --gcc /path/to/riscv-none-elf-gcc \
  --verilator /path/to/verilator \
  --pool-bytes 12288 --dataflow 2 \
  --samples 0 1 --kind both --jobs 3 --run-jobs 3
```

This runs MNIST CNN, MobileNetV1 VWW, DS-CNN KWS and ResNet-8, with two inputs,
two storage policies and two measurement types: 32 independent SoC runs.
Within each RAW/adaptive pair, the RTL executable and firmware ELF are
identical. A runtime flag calls `dsa_set_ps_force_raw()` before model
allocation and Prepare. Both policies can select IA allocation and WS/IS;
RAW forces uncompressed PS, while adaptive can also select a RAW schedule.

Each run validates final outputs and checks that the model and input bytes
remain unchanged. Trace runs also compare every operator
output with the prepared nearest-even references. PS event checking compares
retained rows and their replay, and validates allocation/retirement order.
The reports require zero task restarts and zero hardware errors.

## Cycle definitions

| Measurement | Interval |
|---|---|
| `initialization_cycles` | Model setup, AllocateTensors/Prepare, weight packing, planning, and input copy |
| `planning_cycles` | Driver cache lookup and parameter scoring, measured by `rdcycle` during initialization |
| Complete inference | CPU `rdcycle` immediately around `Invoke()`, including submission and waiting |
| Conv/Dense hardware cycles | NPU task start to task completion |
| Conv/Dense CPU intervals | Trace operator start to end, including CPU preparation and MMIO |

Pointwise Conv remains in the Conv category when it uses a physical GEMM
command. Dense corresponds to graph `FULLY_CONNECTED` operators. Trace
output collection occurs after the operator-end marker. Performance runs
have tracing disabled.

Speedup is the sum of RAW cycles divided by the sum of adaptive cycles for
matching inputs. The report lists the 1.2× target separately from numerical
correctness. Initialization is reported separately from steady inference.

`--latency` applies the same fixed RAM delay to both policies. `--resume`
checks model/input identity, executable hashes, measurement kind, source
identity, and RAM delay before reusing a result.
Firmware changes trigger a firmware rebuild. After RTL changes, rebuild the
simulator by running without `--resume`.

## Result files

- `soc_summary.json`: complete run records, output comparisons, cycle totals,
  selected hardware parameters and source/executable hashes.
- `comparison.csv`: per-model and combined Conv, Dense, matrix and Invoke cycles.
- `timings.csv`: per-run initialization, measured planning, and Invoke cycles.
- `layers.csv`: per-layer R/W, WS/IS, IA/PS allocation, PS strategy, memory
  traffic, frame commands, capacity events and task cycles.
- `cpu_layers.csv`: trace operator intervals including CPU submission work.
- Per-run `result.json`, `run.log` and PS event files: detailed numerical and
  transaction checks.
- `sim/build.json`: hardware configuration, RTL source identities, tool version,
  and simulator identity.
- `firmware/*/firmware.json`: compiler options, source identities, ELF identity,
  and memory placement.

## Reuse-plan measurements

`sweep_shared_plans.py` runs selected IA allocations, WS/IS modes, R, W, and
PS controls for MobileNetV1 operator 14 and ResNet-8 operator 4. It reuses the
network simulator, including its 4 KiB im2col cache and memory timing. Input
tensors, weights, bias, and quantization parameters come from the prepared
models. Weights use the same packed 16 × 16 layout as TFLM preparation.

```bash
python3 test/ps_compression/sweep_shared_plans.py \
  --sim build/unified_validation/soc/sim \
  --prepared /path/to/prepared \
  --out build/unified_validation/plan_sweep \
  --gcc /path/to/riscv-none-elf-gcc --run-jobs 2
```

The sweep checks the expected output, immutable input and weights, and retained
INT32 rows for every plan. `plans.csv` records NPU task cycles, CPU START/wait
cycles, read bytes, and frame commands. Register programming occurs before the
measured CPU interval. Tensor addresses are fixed across sweep plans; complete
network timing is measured separately by `run_soc.py`.

Build output belongs under `build/`. Model files, generated tensors and
simulation executables are not required in source commits.
