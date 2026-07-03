# TFLM AI DSA Vivado SoC Project Export

This directory exports an openable Vivado project for the board-level SoC top.
The project uses `fpga_top` as the FPGA wrapper, maps pins with an Alkaid-style
XDC, and pulls the accelerator RTL from this repository.
The board clock constraint is 50 MHz; `clk_wiz_0` is generated automatically by
the Tcl flow and creates the internal SoC/MMA clock.

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

`AIENGINE_ROOT` may be set when the full SoC shell lives outside the default
`/media/proj_tmp/aiEngine_integrated` path.
`ICB_LEN_W` is computed from `SIZE` by the project Tcl.
`CORE_CLK_MHZ` defaults to 150 MHz and is produced from the 50 MHz board clock
through Clocking Wizard.

## Export Self-Contained Project

Use `export_project.tcl` when the Vivado project should be moved or opened
without depending on the live source trees. It copies RTL from this repository
and `AIENGINE_ROOT`, copies the CPU memory image into the exported directory,
and sets `CPU_MEM_PATH` to the copied file's absolute path.

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
  /media/proj_tmp/aiEngine_integrated/veri/tb/axi_soc_runtime_build_S16_C4_P16/cpu.mem \
  150.000 1 0 1 1 Flow_AreaOptimized_high Performance_ExplorePostRoutePhysOpt 1
```

Argument order:

```text
<export_root> <part> <SIZE> <IA_CACHE_BLOCKS> <CPU_MEM_DP> <CPU_MEM_PATH>
<CORE_CLK_MHZ> <CPU_AXI_WRITE_TIMING_BUFFER> <BYPASS_RAM_PINGPONG>
<RAM_WRITE_TIMING_BUFFER> <RUN_IMPL> <SYNTH_STRATEGY> <IMPL_STRATEGY>
<CPU_ENABLE_ICACHE>
```

`CPU_ENABLE_ICACHE` defaults to `1` in the export flow so the FPGA project
matches the SoC performance regressions. It can also be overridden with the
`VIVADO_CPU_ENABLE_ICACHE` environment variable.

The exported directory contains a short `README.md`, copied source files,
constraints, `mem/cpu.mem`, routed reports when `RUN_IMPL=1`, and
`fpga_top.bit` after bitstream generation.

## Post-Implementation Smoke

After implementation, run a minimal functional netlist simulation with:

```sh
vivado -mode batch \
  -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_post_impl_smoke.tcl \
  -tclargs vivado_export/tflm_ai_dsa_soc_s16_c4/project/tflm_ai_dsa_soc.xpr
```

The smoke test waits for `user_led_tri_o[1]` (`soc_finish`) and fails if
`user_led_tri_o[2]` (`cpu_trap`) asserts.
