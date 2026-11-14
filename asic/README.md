# ASIC synthesis flow

This directory contains a Synopsys Design Compiler flow for the standalone
`npu_top` RTL.  The flow is based on the local Xinyuan example at
`/home/yusen/opt/xinyuan/xinyuan-syn` and uses the same FreePDK45/OSU
`gscl45nm.db` library by default.

Default target:

- Top: `npu_top`
- Frequency: `400 MHz`
- Period: `2.5 ns`
- Default NPU config: `SIZE=4`, `IA_CACHE_BLOCKS=32`, `PS_FRAME_COUNT=4`,
  `WEIGHT_WIDTH=8`, `DATA_WIDTH=8`, with IS/per-channel paths pruned.

Run synthesis:

```sh
make -C asic/syn syn
```

Print the latest summary:

```sh
make -C asic/syn summary
```

Useful overrides:

```sh
make -C asic/syn syn TARGET_FREQ_MHZ=400 MAX_CORES=8
make -C asic/syn syn NPU_SIZE=16 NPU_IA_CACHE_BLOCKS=4 NPU_PS_FRAME_COUNT=16 \
  NPU_WEIGHT_WIDTH=16 NPU_DATA_WIDTH=16 NPU_ENABLE_IS_MODE=1 NPU_ENABLE_PER_CHANNEL=1
make -C asic/syn syn NPU_SIZE=4 NPU_IA_CACHE_BLOCKS=32 NPU_PS_FRAME_COUNT=4 \
  NPU_WEIGHT_WIDTH=8 NPU_DATA_WIDTH=8 NPU_ENABLE_IS_MODE=0 NPU_ENABLE_PER_CHANNEL=0
```

Generated reports and netlists are written under `asic/syn/output/<date>_*`.
