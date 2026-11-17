# TFLM AI DSA Vivado SoC Project Export

This directory exports an openable Vivado project for the board-level SoC top.
The project uses `fpga_top` as the FPGA wrapper, maps pins with an Alkaid-style
board pinout inside the project XDC, and pulls the accelerator RTL from this
repository.
The board clock constraint is 50 MHz; `clk_wiz_0` is generated automatically by
the Tcl flow and creates the internal SoC/NPU clock.

## Hardware Configuration

The Tcl entries read literal assignments from `config/npu.mk`. Set `NPU_CONFIG`
to select another file. The following environment variables override the file:

| Setting | Supported values | Default | RTL generic |
|---|---|---:|---|
| `NPU_AXI_DATA_WIDTH` | 32, 64 bits | 64 | `BUS_WIDTH` |
| `SHARED_BANK_BYTES` | 1024, 2048, 4096 bytes | 2048 | `SHARED_BANK_BYTES` |
| `SHARED_BANK_COUNT` | 6, 7, 8, 9 | 7 | `SHARED_BANK_COUNT` |

The shared data capacity is `SHARED_BANK_BYTES * SHARED_BANK_COUNT`, or 14 KiB
with the defaults. Software assigns one, two, or four banks to IA before a
layer starts and uses the remaining banks for PS. S16 input requires at least
two IA banks. Accumulation across K tiles requires at least four PS banks for
RAW32 or three PS banks when the intermediate values satisfy the S24 bound.
The allocation remains fixed throughout the task.

`NPU_AXI_DATA_WIDTH` controls the tensor-data AXI4 interface, SoC data
interconnect, and memory data interface. The NPU AXI-Lite control interface
uses 32-bit data and 16-bit addresses. Internal shared SRAM ports are 128 bits.
The input CPU image contains 32-bit hexadecimal words for either AXI4 width.
The Tcl scripts pad it to `CPU_MEM_DP` CPU words and save that image as
`mem/cpu32.mem`. They also write `mem/cpu.mem` in the physical RAM word format.
For AXI64, each output line contains two consecutive CPU words, with the word
at the lower byte address in bits 31:0. AXI32 uses one CPU word per line.
`fpga_top` initializes RAM directly from this native image and sets
`CPU_MEM_WORD_WIDTH=BUS_WIDTH` on `soc_top`. Ordinary SoC simulation continues
to accept CPU32 images, including sparse address directives and memory reloads.
`CPU_MEM_DP` continues to count 32-bit CPU words.

The configuration also supplies `PCR_ENGINE`, `PS_POOL_BYTES`, and
`PS_FORCE_RAW`. `PCR_ENGINE=1` enables shared PS storage and frame scheduling
in the common compute path. `GEMPACT_PS_COMPRESS` and the existing
`GEMPACT_PCR_ENGINE`, `GEMPACT_PS_POOL_BYTES`, and `GEMPACT_PS_FORCE_RAW`
environment settings can override those defaults. The total shared capacity
is determined by the two shared-bank generics.

```sh
NPU_CONFIG=config/npu.mk NPU_AXI_DATA_WIDTH=64 \
SHARED_BANK_BYTES=2048 SHARED_BANK_COUNT=7 \
vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/create_project.tcl
```

The Tcl parser accepts integer literals and validates parameter ranges before
creating a project. It does not evaluate Make expressions. Existing positional
arguments for the part, array size, CPU memory, clock, and implementation
strategy retain their meanings.

## Create Project

```sh
vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/create_project.tcl
```

The generated `.xpr` is placed under:

```text
build/vivado/tflm_ai_dsa_soc/tflm_ai_dsa_soc.xpr
```

## Run Synthesis

```sh
VIVADO_JOBS=8 vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_synth.tcl
```

For batch synthesis:

```sh
VIVADO_JOBS=8 vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_batch_synth.tcl
```

Optional Tcl arguments:

```text
<project_dir> <part> <SIZE> <IA_CACHE_BLOCKS> <CPU_MEM_DP> <CPU_MEM_INIT_EN> <CPU_MEM_PATH> <CORE_CLK_MHZ>
```

Example:

```sh
vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_synth.tcl \
  -tclargs build/vivado/tflm_ai_dsa_soc_s16_c4 xc7a200tfbg484-3 16 4 65536 0 "" 150.000
```

The SoC shell is contained in this repository. Initialize the PicoRV32 submodule with `git submodule update --init --recursive` before creating the project.
`CORE_CLK_MHZ` defaults to 150 MHz and is produced from the 50 MHz board clock
through Clocking Wizard.

## Export Self-Contained Project

Use `export_project.tcl` when the Vivado project should be moved or opened
without depending on the live source trees. It copies RTL from this repository,
generates both CPU32 and native RAM images in the exported directory, and sets
`CPU_MEM_PATH` to the native image's absolute path.
When no CPU memory image is passed, the export script first looks for the
current TFLM MNIST MLP hardware image at
`veri/tb/axi_soc_tflm_mnist_mlp_hw/cpu.mem`.
For the 150 MHz FPGA UART at 115200 bps, regenerate that image with
`SOC_UART_CLKDIV=1300` so the firmware programs the simple UART divider
correctly.

```sh
vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/export_project.tcl
```

The default export is:

```text
vivado_export/tflm_ai_dsa_soc/project/tflm_ai_dsa_soc.xpr
```

To export a specific configuration and immediately generate a bitstream:

```sh
VIVADO_JOBS=8 vivado -mode batch \
  -source fpga/vivado/tflm_ai_dsa_soc/scripts/export_project.tcl \
  -tclargs vivado_export/tflm_ai_dsa_soc_s16_c4 xc7a200tfbg484-3 16 4 65536 \
  veri/tb/axi_soc_case/cpu.mem \
  150.000 1 0 1 1 Flow_AreaOptimized_high Performance_Explore 1 10000000
```

Use a self-contained `cpu.mem` generated with `SOC_APP=case` for a functional
bitstream test. Include the program and all model data in the initialized image.
The `SOC_APP=runtime` workflow stores its data payload separately in
`runtime_data.mem` at `0x00080000`; combine that payload with the program when
preparing a single FPGA memory image.

Argument order:

```text
<export_root> <part> <SIZE> <IA_CACHE_BLOCKS> <CPU_MEM_DP> <CPU_MEM_PATH>
<CORE_CLK_MHZ> <CPU_AXI_WRITE_TIMING_BUFFER> <BYPASS_RAM_PINGPONG>
<RAM_WRITE_TIMING_BUFFER> <RUN_IMPL> <SYNTH_STRATEGY> <IMPL_STRATEGY>
<CPU_ENABLE_ICACHE> <SIM_MAX_SYS_CYCLES>
```

The default FPGA export preset is area-prioritized synthesis strategy
`Flow_AreaOptimized_high` with synthesis directive `AreaOptimized_high`, and
implementation strategy `Performance_Explore`.

`CPU_ENABLE_ICACHE` defaults to `1` in the export flow so the FPGA project
matches the SoC performance regressions. It can also be overridden with the
`VIVADO_CPU_ENABLE_ICACHE` environment variable.
`NPU_ENABLE_CLOCK_GATING` defaults to `1` and gates the complete `npu_top`
clock while the accelerator is idle. It can also be overridden with the
`VIVADO_NPU_ENABLE_CLOCK_GATING` environment variable.
`SIM_MAX_SYS_CYCLES` defaults to `10000000`, which covers the full MNIST MLP
test program. Further models can set a suitable cycle limit. It can also be overridden with
`VIVADO_SIM_MAX_SYS_CYCLES`.

Example 150 MHz MNIST MLP project export:

```sh
make -C veri/sim tflm_mnist_mlp_soc_c \
  SOC_CASE=axi_soc_tflm_mnist_mlp_hw \
  TFLM_SOC_MMA_ENABLE=1 TFLM_NMSIS_NN_ENABLE=1 \
  MMA_SIZE=16 MMA_IA_CACHE_BLOCKS=4 MMA_PS_FRAME_COUNT=16 \
  SOC_CPU_MEM_DP=65536 SOC_UART_CLKDIV=1300

VIVADO_JOBS=8 \
VIVADO_NPU_WEIGHT_WIDTH=16 \
VIVADO_NPU_DATA_WIDTH=16 \
VIVADO_NPU_ENABLE_CLOCK_GATING=1 \
vivado -mode batch \
  -source fpga/vivado/tflm_ai_dsa_soc/scripts/export_project.tcl \
  -tclargs vivado_export/tflm_ai_dsa_soc_150m_mnist_mlp \
  xc7a200tfbg484-3 16 4 65536 \
  veri/tb/axi_soc_tflm_mnist_mlp_hw/cpu.mem \
  150.000 1 0 1 0 Flow_AreaOptimized_high Performance_Explore 1 30000000
```

The exported directory contains a `README.md`, copied source files,
constraints, simulation testbenches, `mem/cpu32.mem`, `mem/cpu.mem`, all Tcl
scripts including `npu_config.tcl` and `cpu_memory.tcl`, and a `config/npu.mk`
snapshot of the effective hardware
settings. `scripts/export_sources.tcl` resolves source paths relative to the
export directory. Routed reports are added when `RUN_IMPL=1`, followed by
`fpga_top.bit` after bitstream generation.

After moving an export, the copied scripts can create a project using its
local sources and configuration. Pass the local CPU32 image when enabling
initialization; the scripts generate the selected native image:

```sh
vivado -mode batch -source /path/to/export/scripts/create_project.tcl \
  -tclargs /path/to/export/project xc7a200tfbg484-3 16 4 65536 1 \
  /path/to/export/mem/cpu32.mem 150.000
```

The exported project adds these simulation tops to `sim_1`. The default
simulation top is `fpga_top_post_impl_tb`, so the Vivado GUI can immediately run
a post-implementation functional waveform after implementation is complete:

- `fpga_top_behav_smoke_tb` for behavioral simulation. The export flow sets its
  generics to the copied absolute `mem/cpu.mem` path.
- `fpga_top_post_impl_tb` for post-implementation functional simulation. It
  uses the implemented netlist and the BRAM INIT baked in during synthesis.

## Post-Implementation Functional Simulation

After implementation, run a minimal functional netlist simulation with:

```sh
vivado -mode batch \
  -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_post_impl_smoke.tcl \
  -tclargs vivado_export/tflm_ai_dsa_soc_s16_c4/project/tflm_ai_dsa_soc.xpr
```

The test waits for `user_led_tri_o[1]` (`soc_finish`) and fails if
`user_led_tri_o[2]` (`cpu_trap`) asserts.

## Tcl Configuration Tests

The configuration and project scripts can be checked with Python and Tcl 8.6.
The test records Vivado property calls through Tcl command replacements and
checks parameter propagation, copied scripts, and relocated export paths:

```sh
python3 fpga/vivado/tflm_ai_dsa_soc/scripts/test_npu_config.py \
  --out build/fpga/configuration --picorv32 /path/to/picorv32
```

RTL simulation, FPGA synthesis, implementation, and timing analysis use the
respective tools and reports described above.
