# Gemmini DWConv and hardware im2col on AXI64

This directory builds the complete `dwconv/gemmini-dwconv` accelerator at the
revision recorded in `dependencies.json`. The source includes `LoopConvDW`,
the DWConv PE dataflow, normal GEMM and convolution scheduling, and the
independent scratchpad-to-array `Im2Col` module. The wrapper enables
`hasIm2Col` while preserving every constructor parameter from the selected
configuration. The build uses the pinned third-party sources and the DMA
completion-field adaptation listed in its manifest.

## Hardware configuration

| Parameter | Value |
|---|---:|
| Array | 16 × 16 |
| Input and weight | INT8 |
| Spatial array output | INT20 |
| Accumulator | INT32 |
| Scratchpad | 32 KiB, four banks |
| Scratchpad read delay | 1 cycle |
| Accumulator RAM | 32 KiB, two banks |
| Physical DMA bus | 64 bit, eight byte strobes |
| Maximum AXI INCR burst | 256 beats |
| Maximum full-width transaction | 2,048 bytes |
| AXI transaction boundary | 4 KiB |
| DMA requests in flight | 4 per direction |
| Clock gating | Disabled |
| Independent hardware im2col | Enabled |
| DWConv dataflow | Enabled |

The two main data memories occupy 65,536 bytes. Hardware im2col reads the
shared scratchpad and holds a 16-byte vector in `im2col_data`; it has no
separate image RAM. `LoopConvDW` contains scheduling state and uses the same
scratchpad and accumulator. The array contains 256 INT20 `accum` registers
(640 bytes) for partial sums. These arithmetic registers, the transposer,
pipeline registers, command queues and address metadata are reported
separately from the two data RAMs.

The native DMA contains a 2,048-byte `BeatMerger.buffer`, a 2,048-byte
`StreamWriter.data_blocks` register array and a 64-byte
`StreamWriter.data_single_block`. These 4,160 bytes are DMA data registers
and are reported separately from scratchpad and accumulator RAM.

## Dependencies and build

The hardware README specifies Chipyard revision
`757d354410adbd886b76cd79299b35d5f8a0265c` and the `dwconv` branch of both
the hardware and its software project. The precise hardware and software
revisions used here are:

| Repository | Revision |
|---|---|
| `dwconv/gemmini-dwconv` | `4a33b75f975297e309847f41f81f4c0f8b20b81d` |
| `dwconv/gemmini-rocc-tests-dwconv` | `576f08c217dfefb9fa2e3e087575f23699565560` |

From the root of a clean checkout of this repository, obtain the dependencies
with the following commands. `comparison_deps` may point to another writable
directory. The selected software revision is checked out independently of the
hardware repository's submodule revision.

```bash
comparison_deps="$PWD/build/gemmini-dwconv-dependencies"
mkdir -p "$comparison_deps"

git clone --no-checkout https://github.com/ucb-bar/chipyard.git "$comparison_deps/chipyard"
git -C "$comparison_deps/chipyard" checkout --detach 757d354410adbd886b76cd79299b35d5f8a0265c
git -C "$comparison_deps/chipyard" submodule update --init \
  generators/rocket-chip generators/testchipip sims/firesim
git -C "$comparison_deps/chipyard/generators/rocket-chip" submodule update --init \
  hardfloat api-config-chipsalliance

git clone --no-checkout https://github.com/dwconv/gemmini-dwconv.git "$comparison_deps/gemmini-dwconv"
git -C "$comparison_deps/gemmini-dwconv" checkout --detach 4a33b75f975297e309847f41f81f4c0f8b20b81d
git -C "$comparison_deps/gemmini-dwconv" submodule update --init software/gemmini-rocc-tests
git -C "$comparison_deps/gemmini-dwconv/software/gemmini-rocc-tests" fetch origin dwconv
git -C "$comparison_deps/gemmini-dwconv/software/gemmini-rocc-tests" checkout --detach \
  576f08c217dfefb9fa2e3e087575f23699565560
```

`build.py` verifies all repository and submodule revisions. Tracked source
changes are rejected. The build creates the Scala project, generated RTL and
simulator in its work directory. It applies
`patches/dma_completion_bytes.patch` to a local copy of `DMA.scala`; all other
third-party sources are compiled directly from the verified repository.
The manifest records the patch, original source and compiled source hashes.

Use Java 17, sbt 1.9.7 and Verilator 5.054:

```bash
python3 test/gemmini_comparison/gemmini_dw_rtl/build.py \
  --chipyard "$comparison_deps/chipyard" \
  --gemmini "$comparison_deps/gemmini-dwconv" \
  --work-dir "$comparison_deps/rtl-build" \
  --java /path/to/jdk17/bin/java \
  --verilator /path/to/verilator \
  --sp-kib 32 --acc-kib 32 --dma-bus-bits 64 --spad-read-delay 1 \
  --read-beat-interval 1 --jobs 4
```

`--sbt` accepts a launcher command, for example `--sbt python3 /path/to/sbt.py`.
`--reuse-generated` recompiles an existing elaboration after checking its
configuration and parameter header. The maximum transfer size is derived
from the AXI data width and the protocol limit of 256 beats.
The command above performs a complete build in an empty work directory; the
first sbt invocation downloads its pinned Scala and Chisel dependencies.

The build produces:

| Path under the work directory | Contents |
|---|---|
| `generated_sp32_acc32_axi64_spdelay1/GemminiCompare.v` | Complete accelerator and AXI conversion RTL |
| `generated_sp32_acc32_axi64_spdelay1/plusarg_reader.v` | RocketChip simulation utility |
| `generated_sp32_acc32_axi64_spdelay1/gemmini_params.h` | Hardware-generated software parameters |
| `generated_sp32_acc32_axi64_spdelay1/generated_configuration.json` | Enabled hardware features |
| `generated_sp32_acc32_axi64_spdelay1/build_manifest.json` | Dependency revisions, configuration and file hashes |
| `obj_sp32_acc32_axi64_spdelay1/VGemminiCompare` | Executable RTL simulator |

### Native DMA and TileLink configuration

The wrapper sets `dma_buswidth=64`, `dma_maxbytes=2048` and both AXI manager
transfer ranges to `TransferSizes(1, 2048)`. Gemmini uses its dedicated
TileLink DMA port. The CPU cache-line size does not limit this port's transfer
range. `TLToAXI4` emits 64-bit data, eight-bit `WSTRB`, eight-bit `AxLEN` and
`AxSIZE=3` for full-width transfers. The physical address space is 32 bits.

Gemmini's reader and writer choose naturally aligned, power-of-two TileLink
transactions. With the 2,048-byte maximum, each transaction remains inside
a 4 KiB page; a logical transfer spanning a page boundary uses several
transactions. The memory service accepts up to 256 beats at any supported
beat size and checks page boundaries for every accepted address.

The configuration subclass emits `MAX_BYTES` from its `dma_maxbytes` value.
The generated software parameters are `MAX_BYTES=2048`,
`MAX_BLOCK_LEN=128` and `MAX_BLOCK_LEN_ACC=32` for the 16×16 INT8/INT32
configuration. Command generators and model firmware must be compiled with
this generated header. `build.py` verifies the header against the RTL
configuration, and `run_cases.py` checks the command generator's parameters.

DMA completion reports use a 16-bit byte count through `StreamReadResponse`
and `ScratchpadMemReadResponse`. This represents the complete 2,048-byte
transaction when the load controller retires a command. The one-field source
adaptation is applied during staging and leaves the pinned checkout unchanged.

## Command and memory interface

`GemminiCompare` accepts ready/valid RoCC commands with a seven-bit function
and two 64-bit operands. `busy` remains asserted while work is outstanding.
The 64-bit AXI master uses three-bit IDs. The official `TLToAXI4` and
`AXI4UserYanker` modules implement protocol conversion.

The independent operator simulator accepts:

```text
VGemminiCompare memory.bin memory_base commands.txt output_base output_bytes expected.bin timed_start result.json read_interval [first_read_latency inter_burst_gap_cycles [read_outstanding_limit]]
```

The command file contains `funct 0xRS1 0xRS2` records and `FENCE` records. A
fence waits for accelerator completion and every memory response. Timing
starts at `timed_start`, a zero-based command record index, and ends after
the final fence. Output bytes and every byte outside the output region are
checked. The memory service uses a three-cycle initial read response,
one-cycle read beat interval by default, three-cycle inter-burst gap, and
one outstanding write. Write data can transfer one beat each cycle.
Transactions are checked against the physical data width, the 256-beat
protocol limit and the 4 KiB boundary.

`--read-interval 1` on the runners selects one read beat per cycle within a
burst. `--read-interval 2` selects one beat every two cycles for bandwidth
sensitivity measurements. Both retain the same three-cycle initial response
and three-cycle gap between queued bursts. Each result group records the
selected service interval; use separate output directories for the two runs.

`--first-read-latency L` selects synchronous memory with a separate deadline
for every accepted AR request. When the response channel is idle and RREADY
stays asserted, the first R handshake occurs exactly L cycles after its AR
handshake. The memory reads into the response register on the preceding
edge, including L=1. Request waiting proceeds in parallel. The default
`--inter-burst-gap-cycles 1` permits an already ready next request to return
on the cycle following the preceding RLAST. RDATA and RLAST remain stable
under backpressure. `--read-latency-cycles` is an alias for
`--first-read-latency`.

The synchronous service accepts four outstanding reads by default.
`--read-outstanding-limit 1` selects serialized requests for latency
measurements. Results record each request's AR-to-first-R delay, additional
queue delay, first-response backpressure and the measured interval between
ready requests. These settings are independent of the accelerator's
unchanged four-request DMA configuration.

## Feature activity measurements

The result JSON records completed read/write traffic, maximum observed
burst sizes and activity from the actual internal hardware signals:

| Result field | Source |
|---|---|
| `loop_depthwise_launches` | Accepted RoCC function 29 |
| `dwconv_active_cycles` | `ExecuteController.is_dwconv_depthwise` |
| `loop_dwconv_busy_cycles` | `LoopConvDW` scheduling activity |
| `independent_im2col_active_cycles` | `ExecuteController.im2col_en` |
| `independent_im2col_requests` | Accepted `Im2Col.io.req` handshakes |
| `independent_im2col_responses` | Accepted `Im2Col.io.resp` handshakes |

AXI statistics include `axi_data_bits`, `axi_strobe_bits`, `read_beats`,
`write_beats`, maximum burst lengths in beats and bytes, observed outstanding
request counts, and request/beat histograms indexed by bytes per beat.

DWConv tests require function 29 launches and active DWConv execution.
Independent im2col tests require nonzero request and response counts.
`LoopConvDW` also forwards other commands, so its busy count is interpreted
together with the specialized launch and execution counters.

Operator timing includes configuration, launch, DMA, execution and
completion. The wrapper has no host CPU. Model comparisons instantiate
the shared PicoRV32 performance configuration and system memory so that
software scheduling, quantization and short operators are included.

## Convolution schedules

`../model_runtime/im2col.h` implements the independent hardware Im2Col
schedule. DMA loads the original image into scratchpad rows with up to
16 channels per row. The first three scratchpad banks hold image data;
the fourth holds one output-channel group's weights. Input-channel groups
are sized from the kernel area and the weight-bank capacity. A tile planner
uses the actual 32 KiB scratchpad and 32 KiB accumulator capacities.

The driver configures `gemmini_extended3_config_ex` with the output width,
kernel dimensions, stride, channel count and output-block dimensions.
The Im2Col unit supplies each window directly to the systolic array. Each
compute receives 16 input rows, including the padded tail of a partial
output block, while its output descriptor selects the valid rows. A fence
separates weight updates between compute groups. Output-channel groups reuse
the loaded image when all input channels fit in one channel tile. Spatial
padding uses the accelerator's zero-fill DMA operation.

The ordinary `LoopConv` schedule and this independent Im2Col schedule are
selected explicitly by `../model_runtime`'s `--conv-policy native` and
`--conv-policy im2col` options. Both retain GEMM for contiguous 1×1 stride-1
layers and the dedicated DWConv dataflow for depthwise layers. Rectangular
kernels use `LoopConv`. Results record the selected policy and observed
Im2Col activity.

The DWConv schedule uses function 29 with up to 16 channels and two spatial
phases per loop. For a 3×3 kernel, this gives at most six output rows with
stride 1 and four output rows with stride 2. Input DMA, compute and
accumulator readback use the fork's native DWConv layout.

## Shared operator tests

`generate_gemm.py` runs the pinned third-party GEMM tiler to produce commands
for the common workload tensors. `run_cases.py` verifies their hashes and
compares every INT8 output byte with the common reference.

The 31-case comparison uses the fork's `tiled_matmul_auto` in WS mode. Every
case uses row-major operands, 64-byte tensor address alignment and automatic
tile selection, recorded as `explicit_tile: [0, 0, 0]`. This fixed procedure
selects tiles from dimensions and available memory before RTL execution.
The comparison does not use measured case timings to select a dataflow,
operand layout or tile. The comparison report checks these settings for all
31 command sequences.

Given the common GEMM tensors produced by `../prepare.py`, the commands are:

```bash
common_workloads=/path/to/common_gemm_workloads
comparison_build="$comparison_deps/rtl-build"

python3 test/gemmini_comparison/gemmini_dw_rtl/generate_gemm.py \
  --gemmini-tests "$comparison_deps/gemmini-dwconv/software/gemmini-rocc-tests" \
  --params-header "$comparison_build/generated_sp32_acc32_axi64_spdelay1/gemmini_params.h" \
  --params-origin hardware-generated \
  --workloads "$common_workloads" --out "$comparison_deps/gemm-traces" \
  --flow ws --transpose none --tensor-alignment 64

python3 test/gemmini_comparison/gemmini_dw_rtl/run_cases.py \
  --sim "$comparison_build/obj_sp32_acc32_axi64_spdelay1/VGemminiCompare" \
  --traces "$comparison_deps/gemm-traces" --output "$comparison_deps/gemm-results" \
  --params-header "$comparison_build/generated_sp32_acc32_axi64_spdelay1/gemmini_params.h" \
  --build-manifest "$comparison_build/generated_sp32_acc32_axi64_spdelay1/build_manifest.json" \
  --read-interval 1
```

`run_operators.py` accepts a model-runtime command exporter and the common
Conv/DW workload catalogue. It checks the independent INT32 reference,
selects the native accumulator scale of 1/32 with nearest-even rounding,
and writes INT8 output through the accelerator. It then checks the output
against the same common INT8 tensor used by the NPU. The result records
the actual tile sizes, input and output hashes, command hashes, selected
convolution path and hardware activity. Passing `--tile-height-override
NAME=ROWS` selects an explicit native tile height for a named case.

`sim/im2col_trace.cc` provides a compact independent test of the hardware
Im2Col instruction sequence. It emits random signed inputs, weights and
biases, commands and a CPU-computed INT32 reference. It covers arbitrary
valid output widths and heights within one tile, partial input-channel
groups, spatial tails and strides 1 or 2 without an intermediate software
im2col tensor.

## AXI protocol checks

`check_axi64.py` runs the complete accelerator's native MVIN/MVOUT path for
four byte-copy cases: an aligned 2,048-byte transfer, a logical transfer
crossing a 4 KiB page, a 13-byte transfer with partial byte strobes, and four
512-byte rows that exercise overlapping read requests.
The aligned case must produce actual 256-beat read and write transactions.
Each case compares every output byte and checks that all other memory bytes
retain their initial values.

```bash
python3 test/gemmini_comparison/gemmini_dw_rtl/check_axi64.py \
  --sim "$comparison_build/obj_sp32_acc32_axi64_spdelay1/VGemminiCompare" \
  --build-manifest "$comparison_build/generated_sp32_acc32_axi64_spdelay1/build_manifest.json" \
  --params-header "$comparison_build/generated_sp32_acc32_axi64_spdelay1/gemmini_params.h" \
  --gemmini-tests "$comparison_deps/gemmini-dwconv/software/gemmini-rocc-tests" \
  --output "$comparison_deps/axi64-protocol-results"
```

`check_read_latency.py` repeats these tests with first-response latencies
1, 2, 3, 8 and 17 and outstanding limits 1 and 4. Each configuration checks
the exact idle-channel latency. Four ready requests must transfer their
combined 256 read beats in 256 cycles, including all burst transitions.

```bash
python3 test/gemmini_comparison/gemmini_dw_rtl/check_read_latency.py \
  --sim "$comparison_build/obj_sp32_acc32_axi64_spdelay1/VGemminiCompare" \
  --build-manifest "$comparison_build/generated_sp32_acc32_axi64_spdelay1/build_manifest.json" \
  --params-header "$comparison_build/generated_sp32_acc32_axi64_spdelay1/gemmini_params.h" \
  --gemmini-tests "$comparison_deps/gemmini-dwconv/software/gemmini-rocc-tests" \
  --output "$comparison_deps/read-latency-results"
```
