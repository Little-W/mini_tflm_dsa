# Matrix pipeline overlap checks

The runner checks numerical outputs while DMA loading, weight transfer, partial-sum replay, and output writes overlap. It uses the 16×16 standard core, eight IA blocks, 720 partial-sum rows, four INT16 output banks, and the 4 KiB window cache. These main data RAMs occupy 64 KiB.

Eight matrix shapes exercise one-element frames, narrow columns, partial reduction tiles, and multiple output tiles. Each shape runs with both WS and IS, both row-major and packed tensors, and one IA/weight reuse block. The complete 32-task sequence runs with fixed and randomized AXI waits. Four additional tasks cover per-channel quantization, INT16 inputs, nonaligned addresses, 4 KiB boundaries, and ordinary convolution in both dataflows. A separate kernel-buffer test checks 1,024 elements while a RAM bank is refilled during transmission of its previously captured tile.

Run from the repository root:

```sh
python3 test/pipeline_overlap/run.py \
  --out build/pipeline_overlap \
  --verilator verilator \
  --bus-width 64 \
  --first-read-latency 8
```

`--repo` selects another source checkout. `--build` reuses a simulator directory produced by `test/gemmini_comparison/run_mini.py`; the runner verifies its parameters and source hashes before execution. `--bus-width 32` exercises the 32-bit parameterization. The default memory accepts four accelerator read requests in flight, registers read data synchronously, and serves consecutive beats every cycle after each request's independently timed first response.

`summary.json` records each numerical result, the simulator and source hashes, and the kernel-buffer result. Per-suite logs retain the detailed cycle counters and protocol assertions.
