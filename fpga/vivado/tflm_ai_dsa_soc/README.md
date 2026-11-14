# TFLM AI DSA Vivado SoC Project Export

This directory exports an openable Vivado project for the board-level SoC top.
The project uses `fpga_top` as the FPGA wrapper, maps pins with an Alkaid-style
board pinout inside the project XDC, and pulls the accelerator RTL from this
repository.
The board clock constraint is 50 MHz; `clk_wiz_0` is generated automatically by
the Tcl flow and creates the internal SoC/NPU clock.

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

For a non-project synthesis check:

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
without depending on the live source trees. It copies RTL from this repository
and copies the CPU memory image into the exported directory,
and sets `CPU_MEM_PATH` to the copied file's absolute path.
When no CPU memory image is passed, the export script first looks for the
current TFLM MNIST MLP hardware image at
`/home/etc/FPGA/tflm_ai_dsa/veri/tb/axi_soc_tflm_mnist_mlp_hw/cpu.mem`.
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
  /home/etc/FPGA/tflm_ai_dsa/veri/tb/axi_soc_case/cpu.mem \
  150.000 1 0 1 1 Flow_AreaOptimized_high Performance_Explore 1 10000000
```

For a bitstream smoke test, use a self-contained `cpu.mem` generated with
`SOC_APP=case`, because the faster `SOC_APP=runtime` flow keeps its data payload
in a separate `runtime_data.mem` overlay at `0x00080000`. Passing only the
runtime `cpu.mem` to Vivado will synthesize a program image without the data
payload and the post-implementation CPU smoke will trap.

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
smoke program with margin. It can also be overridden with
`VIVADO_SIM_MAX_SYS_CYCLES`.

Final 150 MHz MNIST MLP project export:

```sh
make -C /home/etc/FPGA/tflm_ai_dsa/veri/sim tflm_mnist_mlp_soc_c \
  SOC_CASE=axi_soc_tflm_mnist_mlp_hw \
  TFLM_SOC_MMA_ENABLE=1 TFLM_NMSIS_NN_ENABLE=1 \
  MMA_SIZE=4 MMA_IA_CACHE_BLOCKS=32 MMA_PS_FRAME_COUNT=4 \
  SOC_CPU_MEM_DP=65536 SOC_UART_CLKDIV=1300

VIVADO_JOBS=8 \
VIVADO_NPU_WEIGHT_WIDTH=8 \
VIVADO_NPU_DATA_WIDTH=8 \
VIVADO_NPU_ENABLE_CLOCK_GATING=1 \
vivado -mode batch \
  -source fpga/vivado/tflm_ai_dsa_soc/scripts/export_project.tcl \
  -tclargs vivado_export/tflm_ai_dsa_soc_final_150m_mnist_mlp \
  xc7a200tfbg484-3 4 32 65536 \
  /home/etc/FPGA/tflm_ai_dsa/veri/tb/axi_soc_tflm_mnist_mlp_hw/cpu.mem \
  150.000 1 0 1 0 Flow_AreaOptimized_high Performance_Explore 1 30000000
```

The exported directory contains a short `README.md`, copied source files,
constraints, simulation testbenches, `mem/cpu.mem`, routed reports when
`RUN_IMPL=1`, and `fpga_top.bit` after bitstream generation.

The exported project adds these simulation tops to `sim_1`. The default
simulation top is `fpga_top_post_impl_tb`, so the Vivado GUI can immediately run
a post-implementation functional waveform after implementation is complete:

- `fpga_top_behav_smoke_tb` for behavioral simulation. The export flow sets its
  generics to the copied absolute `mem/cpu.mem` path.
- `fpga_top_post_impl_tb` for post-implementation functional simulation. It
  uses the implemented netlist and the BRAM INIT baked in during synthesis.

## Post-Implementation Smoke

After implementation, run a minimal functional netlist simulation with:

```sh
vivado -mode batch \
  -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_post_impl_smoke.tcl \
  -tclargs vivado_export/tflm_ai_dsa_soc_s16_c4/project/tflm_ai_dsa_soc.xpr
```

The smoke test waits for `user_led_tri_o[1]` (`soc_finish`) and fails if
`user_led_tri_o[2]` (`cpu_trap`) asserts.
