# Production C and RTL co-simulation

This test calls the production NMSIS functions and VCE driver through actual
AXI-Lite, NPU, DMA and AXI RAM RTL. Hardware inputs, parameters and outputs are
protected from CPU access during execution. Returned tensors and adjacent
storage bytes are checked after each operation.

Coverage includes DW, Conv mode changes, small and global pooling, INT8 Add,
signed vector operations, channel tails, unaligned INT8 buffers, 4 KiB boundaries,
fixed latency and random memory delays. Add uses the three ResNet-8 quantization
parameter sets, signed tie cases, output saturation, identical inputs and
software execution for in-place output.

```bash
python test/vector_engine_cosim/run.py --out build/vector_engine_cosim \
  --verilator /path/to/verilator --jobs 1 --size 16 --pe-count 8
```

Use `--disabled` to check software dispatch when VCE is unavailable. Build input
hashes and executable hashes are verified when `--skip-build` is selected.
All co-simulation timing includes the C driver's AXI-Lite accesses, but the host
CPU instruction execution is untimed. Complete RISC-V inference measurements
are provided by `test/model_benchmark`.
