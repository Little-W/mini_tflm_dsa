# Packed matrix layout and capacity regression

This regression instantiates the complete `npu_axil_top`, programs it through
AXI-Lite, and executes the production matrix loaders, systolic array, partial
sum storage, quantization pipelines, and output DMA. It uses the existing
`test/conv_npu/axi_memory.sv` responder with its fixed and randomized AXI waiting
behavior.

```sh
python3 test/matrix_layout/run.py --profiles 8 4 16 --jobs 2
```

The executable requires Verilator with SystemVerilog timing support and a C++20
compiler. `--verilator` selects the executable, and `--out` selects the result
directory. `--skip-build` reuses a simulator only when the compiled RTL and test
source hashes still match. `--case REGEX` selects a subset of named workloads.
The default result directory is `build/matrix_layout`.

`--ws-only` instantiates the hardware with `ENABLE_IS_MODE=0` and runs workloads
whose effective dataflow is WS. The register checks also verify that the IS
support bit in `MATRIX_CAPS` matches the instantiated hardware.

## Hardware profiles

All profiles use a 16 by 16 array, 16 partial sum frames, 799 partial sum rows,
32 S8 output banks, 4 S16 output banks, and four outstanding AXI read and write
requests. The IA cache contains 8, 4, or 16 blocks, as selected by `--profiles`.
The test passes these capacities explicitly to the production top module.

The AXI-Lite checks read `MATRIX_CAPS` at `0xe4`, `MATRIX_PS_ROWS` at `0xe8`, and
`MATRIX_OUTPUT_BANKS` at `0xec`. They compare the reported capacities with the
instantiated parameters. They also exercise read-only register writes, separate
AW/W arrival orders, stalled responses, byte write strobes for packed layout
flags, a masked START bit, and rejection of configuration writes while busy.

## Workloads and checks

- WS and IS with each combination of row-major and packed LHS/RHS matrices.
- Complete tiles, reduction tails, output row and column tails, multiple reuse
  groups, signed 8-bit and signed 16-bit inputs, nonzero input corrections,
  per-tensor and per-channel quantization, activation bounds, and exact RNE ties.
- Signed 16 by 8 multiplication with signed 16-bit output. An explicit write
  stall fills all four S16 FIFO banks. Assertions check bank occupancy, prohibit
  writes into unread banks, require backpressure, and verify the final output.
  S16 output selects WS throughout the matrix controller, including when the
  input control register also has its IS selection bit set. Dedicated cases
  exercise that selection with partial tiles and partial sum capacity limits.
- Native Conv with packed RHS weights in both dataflows. LHS packed Conv
  configurations must return a configuration error before any AXI transaction.
- IS per-channel groups with `R=4,W=1` and `R=4,W=2`, including 63 output
  channels. The IA16 profile also exercises `R=8,W=4`, including a 127-channel
  tail group.
- A configuration requiring exactly 799 partial sum rows; configurations
  requiring more storage; and a single reduction tile that does not need
  intermediate partial sums. With IA16, an S16 job requesting eight output
  banks must be rejected before memory access.
- Reads and writes ending at a 4 KiB boundary, independent AXI channel waiting,
  consecutive jobs without reset, injected read and write response errors,
  an error on the final partial bias request, and successful jobs after errors.

Packed operands have the physical shape
`[ceil(rows/16), ceil(K/16), 16, 16]`, with row-major elements inside each tile.
LHS rows are output matrix rows; RHS rows are output matrix columns. The test
fills reduction padding with nonzero values and checks that the loader clears
all elements beyond logical `K`. Unused rows in the final packed tile are
excluded from the permitted read region.

The reference uses Python unbounded integer dot products and integer
division rounded to nearest with ties to even. S16 outputs use the reduced
Q31 multiplier and signed 64-bit requantization rule. Inputs are chosen so
that valid accumulators fit signed 32-bit storage. The Conv reference forms
its NHWC windows independently, including zero padding after input correction.

Every AXI read is checked against a byte-level allocation map for inputs,
weights, bias, and quantization parameters. Every asserted write strobe must
address an output byte. Successful jobs compare the complete 512 KiB memory
image, including output stride padding and all non-output data. Configuration
errors must leave the image unchanged. For an injected write response error,
each output byte may contain its original value or its correct computed value;
all non-output bytes still require exact equality. Completion requires all
memory responses to be drained.

## Results

`summary.json` contains task results and per-task measurements. Each profile
has a `build.json` with compiled source hashes, the build command, and the
simulator hash. Each workload has `case.json`, `config.mem`, `init.mem`,
`golden.mem`, and `access.mem`. The JSON records include the matrix shape,
layout flags, quantization mode, reuse factors, capacity requirement, and
expected output SHA256.

The cycle field includes AXI-Lite launch and status polling. These regression
cycles describe the test's completion interval; accelerator performance
comparisons use the project's dedicated comparison and model benchmarks.

The focused bias storage regression covers resident group reuse and bounded
partial groups with capacities of 1, 2, 4, and 8 blocks:

```sh
make -C test/bias_loader_reuse run JOBS=2
```
