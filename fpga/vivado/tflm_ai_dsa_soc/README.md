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
