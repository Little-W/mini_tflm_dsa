# Conv C driver and NMSIS dispatch checks

Run from the repository root:

```bash
python3 test/conv_driver/run.py
```

Both driver variants compile with `-Wall -Wextra -Werror` and run with UBSan.
The test uses the **real** NMSIS ordinary, wrapper, 1x1, fast 1x1 and 1xN entry
points and the accelerated aliases. Their hardware path receives `NULL` scratch
and activation, filter, and output buffers protected with `PROT_NONE`. A CPU
window read, im2col write, filter MAC, or output access therefore faults. The
MMIO mock records complete register snapshots for two batches / three groups,
checks NHWC output strides and OHWI group pointers, and supplies only status
responses. It does not compute convolution output and is not RTL simulation.

Checks also cover capability/version rejection without register writes, busy,
error, timeout (no unsafe software retry), geometry/address/parameter rejection,
and real NMSIS software fallback when hardware capabilities are absent. Original
NMSIS scalar arithmetic is compiled on the host with the small portability
header `host_compat.h`; DSP/vector paths are not enabled.

`build/conv_driver/` contains generated commands, build logs, runtime logs and
`status.json`. All test data is created by the executable; no saved vector or
previous result is required.
`BUILD_DIR=/absolute/path` moves only build outputs. Linux `MAP_32BIT` is used to
meet the actual 32-bit accelerator bus-address contract.

For co-simulation or a platform MMIO abstraction, compile production sources
with `DSA_MMIO_CUSTOM` and provide `dsa_mmio_write(addr, data)` and
`dsa_mmio_read(addr)`. Their address argument includes `DSA_MMIO_BASE`. Compile
with `DSA_NN_CONV_ENABLE=0` to obtain a software-only NMSIS reference without
accessing accelerator registers.
