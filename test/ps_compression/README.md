# PS compression, shared memory, and schedule measurements

These tests exercise the PS store and scheduler in the common NPU execution
path. The DiP array receives a complete input row each cycle, propagates inputs
diagonally between PEs, and uses rotated stationary weights. PS storage and
replay operate on complete rows of 16 INT32 values.

## Hardware configuration

The standard model profile uses a 16 × 16 array, 16 frame descriptors, a
1024-row PS directory, a 4 KiB DMA window cache, and eight vector PEs. Shared
IA/PS memory has six to nine banks, with 2, 4, or 8 KiB per bank. The two
target configurations are:

| Configuration | Shared banks | Shared data capacity | External AXI data width |
|---|---|---:|---:|
| [`config/npu.mk`](../../config/npu.mk), general and ASIC | Seven 2 KiB banks | 14 KiB | 64 bits |
| [`config/npu_fpga.mk`](../../config/npu_fpga.mk), FPGA | Seven 8 KiB banks | 56 KiB | 64 bits |

The external AXI interface also supports 32 bits. Each shared bank has a
128-bit internal data interface. The FPGA configuration uses two `RAMB36E1`
primitives per bank; data and parity capacity are reported separately.
ASIC banks use complete `RAMTP128X16` macros. See
[shared RAM mapping](../../docs/shared_ram_mapping.md) for mapping and capacity
checks.

Prepare selects one, two, or four IA banks for each matrix layer, with the
remaining banks assigned to PS. IA and PS access disjoint allocations through
independent interfaces. S8 IA data uses compact storage; S16 IA data requires at least
two IA banks. RAW32 and adaptive policies use the same physical memories and
the same scheduling cost function.

The planner enumerates legal IA allocations, R/W, WS/IS, and continuous or
per-frame execution. Static weights can establish a strict S16 or S24 bound
for retained partial sums. Runtime admission uses that bound and actual free
space; each active frame keeps its own next K position. Under capacity
pressure, the scheduler completes resident output columns and releases their
storage before accepting more columns. See
[scheduling and window caching](../../docs/scheduling_and_window_cache.md) for
the capacity conditions and score equations.

## Module and NPU tests

```bash
make dip-array-test VERILATOR=/path/to/verilator
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator
make shared-memory-structure YOSYS=/path/to/yosys
```

The structure test requires Yosys with `read_slang`. It checks bank dimensions,
synchronous read/write interfaces, the PS directory and decode FIFO, and the
registers used for complete IA rows. The functional suites cover lossless
INT32 coding, Sparse128, S16/S24 bounds, frame replacement, per-bank admission,
protected-frame completion, saved K progress, concurrent IA/PS traffic, S8 and
S16 inputs, AXI abort, WS/IS, tails, and invalid configuration recovery. C++
module tests enable undefined-behavior checks. NPU tests compare every final
INT32 accumulator and output value with independently computed results.

The shared NPU suite runs 48 cases. Its directed configuration uses a 1 KiB
im2col cache; the complete-model simulator uses the 4 KiB cache described
above. The packed and frame integration suites reuse the shared NPU executable:

```bash
python3 test/ps_compression/run_shared_npu.py \
  --out build/ps_compression/shared_npu \
  --verilator /path/to/verilator --bus-width 64 --jobs 3

python3 test/ps_compression/run_packed_shared.py \
  --sim build/ps_compression/shared_npu/sim \
  --out build/ps_compression/packed_shared

python3 test/ps_compression/frame_npu_test.py \
  --binary build/ps_compression/shared_npu/sim/obj/Vtb_conv_npu \
  --out build/ps_compression/frame_npu

python3 test/ps_compression/run_literal_bound_npu.py \
  --sim build/ps_compression/shared_npu/sim \
  --out build/ps_compression/literal_bounds
```

Packed tests cover LHS, RHS, and both operands, global K strides, partial
tiles, Conv weights, and randomized AXI waiting. The frame tests include
extreme bias values, absent bias, S16 input/output, single reduction tiles,
and final-K bias addition. Packed and frame integration run 32 and 46 cases
respectively. The bound tests check admission and error handling when a
record exceeds its configured maximum length.

The larger-bank suite exercises 8 KiB banks, compact S8 R up to 64, S16 R up
to 32, packed operands, Conv, and fixed and randomized memory timing:

```bash
python3 test/shared_ia_ps/run_geometry_npu.py \
  --out build/ps_compression/geometry_8k \
  --bank-count 7 --bus-width 64 \
  --verilator /path/to/verilator --jobs 3
```

## Complete-model comparison

Use the prepared models and references described in
[`test/model_benchmark`](../model_benchmark/README.md). A RISC-V RV32IM C/C++
toolchain and the pinned PicoRV32 source are required. This example selects
the 14 KiB shared-memory configuration explicitly:

```bash
export PICORV32_ROOT=/path/to/picorv32
python3 test/ps_compression/run_soc.py \
  --out build/ps_compression/soc \
  --prepared /path/to/prepared \
  --gcc /path/to/riscv-none-elf-gcc \
  --verilator /path/to/verilator \
  --bus-width 64 --shared-bank-bytes 2048 --shared-bank-count 7 \
  --pool-bytes 12288 --first-read-latency 8 --dataflow 2 \
  --samples 0 1 --kind both --jobs 3 --run-jobs 3
```

For the FPGA memory geometry, use `--shared-bank-bytes 8192`,
`--shared-bank-count 7`, and `--pool-bytes 49152`, with a separate output
directory. The hardware profile and its usable data capacity accompany each
result.

The command runs MNIST CNN, MobileNetV1 VWW, DS-CNN KWS, and ResNet-8, with two
inputs, two storage policies, and two measurement types: 32 independent SoC
runs. Within each RAW/adaptive pair, the RTL executable, firmware ELF, memory
geometry, and input tensors are identical. A runtime flag calls
`dsa_set_ps_force_raw()` before `AllocateTensors()` and Prepare. Both policies
select IA allocation, R/W, and WS/IS. RAW forces uncompressed PS. Adaptive
uses lossless coding for retained PS, including windows that fit in RAW32.
Tasks with a single K tile have no retained PS.

Each run validates final outputs and checks that model and input bytes remain
unchanged. Trace runs also compare every operator output with the prepared
nearest-even references. PS event checking compares retained rows and their
replay, and validates allocation and retirement order. Reports require zero
task restarts and zero hardware errors.

Layer configuration is stored in persistent tensor arena memory during
Prepare. Invoke passes that configuration pointer and current activation
addresses through NMSIS. The
[prepared lifecycle test](../prepared_lifecycle/README.md) checks repeated
Invoke calls, unchanged configurations and static tensors, and zero increases
in Prepare calls, planning cycles, and arena use.

## Cycle definitions

| Measurement | Interval |
|---|---|
| `initialization_cycles` | Model setup, `AllocateTensors()`/Prepare, weight packing, planning, and input copy |
| `planning_cycles` | Driver cache lookup and parameter scoring, measured by `rdcycle` during initialization |
| Complete inference | CPU `rdcycle` immediately around `Invoke()`, including submission and waiting |
| Conv/Dense hardware cycles | NPU task start to task completion |
| Conv/Dense CPU intervals | Trace operator start to end, including CPU preparation and MMIO |

Pointwise Conv remains in the Conv category when it uses a physical GEMM
command. Dense corresponds to graph `FULLY_CONNECTED` operators. Trace
output collection occurs after the operator-end marker. Performance runs have
tracing disabled. Planning cycles are part of initialization and are also
reported separately.

Compression speedup is the sum of RAW cycles divided by the sum of adaptive
cycles for matching inputs on the same hardware. Reports list the 1.2× target
separately from numerical correctness. Each AXI width and shared-memory
configuration has its own paired comparison. Initialization is reported
separately from repeated inference.

The simulator profile records first-read latency and continuous read-beat
spacing. `--latency` applies the same fixed RAM wait setting to both
policies. `--resume` checks model/input identity, executable hashes,
measurement kind, source identity, and memory timing before reusing a result.
Firmware changes trigger a firmware rebuild. After RTL changes, rebuild the
simulator by running without `--resume`.

## Result files

- `soc_summary.json`: complete run records, output comparisons, cycle totals,
  selected hardware parameters, and source/executable hashes.
- `comparison.csv`: per-model and combined Conv, Dense, matrix, and Invoke cycles.
- `timings.csv`: per-run initialization, measured planning, and Invoke cycles.
- `layers.csv`: per-layer R/W, WS/IS, IA/PS allocation, PS strategy, memory
  traffic, frame commands, capacity events, and task cycles.
- `cpu_layers.csv`: trace operator intervals including CPU submission work.
- Per-run `result.json`, `run.log`, and PS event files: numerical and
  transaction checks.
- `sim/build.json`: hardware configuration, RTL source hashes, memory timing,
  tool version, and simulator identity.
- `firmware/*/firmware.json`: compiler options, source hashes, ELF identity,
  and memory placement.

## Dense AUTO and candidate measurements

`sweep_dense_shapes.py` uses the production Prepare path with real weights,
bias, and quantization parameters. It reads the selected simulator's
`build.json` to obtain the AXI width, maximum DMA transfer, shared-bank
geometry, and memory timing. `planner_profile.py` generates the host
exporter's configuration and checks its compiled values against this
profile. The report records the four transfer cost coefficients and the two
loading-control coefficients used by the firmware and exporter.

Measure the five actual M=1 Dense layers with both prepared inputs:

```bash
python3 test/ps_compression/sweep_dense_shapes.py \
  --sim build/ps_compression/soc/sim \
  --prepared /path/to/prepared \
  --out build/ps_compression/dense_actual_auto \
  --gcc /path/to/riscv-none-elf-gcc \
  --suite actual --selection auto --literal-bound --samples 0 1 \
  --run-jobs 2
```

The independent batch experiment keeps MNIST operator 5's real K=784, N=64
weights and constructs M=64 input rows from the two prepared samples:

```bash
python3 test/ps_compression/sweep_dense_shapes.py \
  --sim build/ps_compression/soc/sim \
  --prepared /path/to/prepared \
  --out build/ps_compression/dense_batch_auto \
  --gcc /path/to/riscv-none-elf-gcc \
  --suite batch --layers mnist_cnn:5 --rows 64 \
  --selection auto --literal-bound --run-jobs 2
```

Batch inputs alternate the two real activation rows. An independent INT64
matrix calculation followed by nearest-even quantization supplies the expected
output. Batch results are reported as separate matrix experiments and are
excluded from complete-network totals.

`--selection auto` measures the minimum estimated-cost plan selected by the
driver for each policy. `--selection critical` measures representative legal
plans around IA allocation, dataflow, and frame choices. To refine a previous
result, `--selection complete_raw --refine-from path/to/summary.json` measures
all distinct RAW candidates, adaptive continuous candidates, and nearby
adaptive frame candidates for qualifying shapes. The recorded candidate set
defines the scope of the measured minimum.

The sweep validates output, immutable operands, and retained INT32 rows for
every plan. It saves the exact prepared layout, literal bound, policy,
hardware profile, and selected configuration. Register programming occurs
before the measured CPU START/wait interval. Tensor addresses remain fixed
across the candidate plans.

## Conv reuse-plan measurements

`sweep_shared_plans.py` runs selected IA allocations, WS/IS modes, R/W, and PS
controls for MobileNetV1 operator 14 and ResNet-8 operator 4. It reuses the
network simulator and its memory timing. Input tensors, weights, bias, and
quantization parameters come from the prepared models. Weights use the same
packed 16 × 16 layout as TFLM preparation.

```bash
python3 test/ps_compression/sweep_shared_plans.py \
  --sim build/ps_compression/soc/sim \
  --prepared /path/to/prepared \
  --out build/ps_compression/conv_plan_sweep \
  --gcc /path/to/riscv-none-elf-gcc --run-jobs 2
```

`plans.csv` records NPU task cycles, CPU START/wait cycles, read bytes, PS
occupancy, and frame commands. The same numerical and immutable-data checks
apply to each plan. Complete-network timing is measured separately by
`run_soc.py`.

## Compression statistics from RTL PS rows

`run_codec_corpus.py` extracts retained INT32 rows from successful RTL runs,
validates their replay, and compares exact codec representations. It accepts
complete-model trace summaries and candidate-sweep summaries. Repeated
`--summary` options combine compatible results; `--case` selects a recorded
case. The selected simulator, event files, run logs, and codec sources must
match their recorded hashes.

```bash
python3 test/ps_compression/run_codec_corpus.py \
  --sim build/ps_compression/soc/sim \
  --summary build/ps_compression/soc/soc_summary.json \
  --out build/ps_compression/codec_corpus
```

The comparison uses 16 INT32 lanes per row and checks exact reconstruction
for every candidate codec. The `observed` representation reproduces the
selected RTL policy, including literal fallback, row boundaries, and
16-byte allocation rounding. It checks payload-word and RAW-record counts
against the RTL events. Opcode distributions are reconstructed by the
matching software codec.

| Unit or field | Meaning |
|---|---|
| Uncompressed PS row | 16 INT32 lanes, 64 bytes |
| PS payload word | 128 bits, 16 bytes |
| External AXI data beat | 4 bytes for AXI32 or 8 bytes for AXI64 |
| `useful_bytes` | Encoded payload length before 16-byte allocation rounding |
| `payload_bytes` | Allocated encoded payload, including word rounding |
| Directory bytes per record | Actual directory bits divided by eight |

For the supported bank counts, the directory uses 34 bits per record with
2 KiB banks, 38 bits with 4 KiB banks, and 42 bits with 8 KiB banks. The tool
derives the width from the selected simulator profile. A candidate that
requires an additional opcode bit includes that bit in its directory cost.
The physical directory is allocated once; the per-record statistics charge
directory space for each recorded row to compare storage representations.

The report provides payload-only compression, total record compression
including directory metadata on both sides, and RAW payload divided by the
compressed payload plus its directory. It also records payload-word counts,
allocation rounding, and codec usage by model, layer, and dataflow. Candidate
storage sizes and measured RTL cycles are separate quantities. Final
performance comparisons use the paired RTL execution results.

Build output belongs under `build/`. Model files, generated tensors, and
simulation executables are not required in source commits.
