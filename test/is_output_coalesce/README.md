# IS output grouping validation

Run from the repository root:

```sh
python3 test/is_output_coalesce/run.py --verilator verilator --jobs 2
```

The test uses the complete AXI-Lite interface with IA capacity 8, 799 partial-sum
rows, and 4 INT16 output banks. Each of its 23 cases runs with both fixed memory
service and randomized AXI backpressure. It compares every byte of the 512 KiB
external memory image and rejects reads or writes outside the allowed tensor
regions.

The cases cover per-channel requantization, input offsets, all four operand
layouts, multiple channel groups, INT16 inputs with INT8 outputs, partial output
rows, a 4096-byte output stride, sustained write backpressure, and recovery after
read or write errors. The additional AXI monitor checks that every write burst
stays inside a 4 KiB page. For eligible IS groups, it also checks the selected
grouping mode, burst width, and starting address.

IS output grouping consumes R consecutive channel tiles from the existing INT8
output FIFO. Each valid output row produces one burst of 16R bytes. The tested
qualification conditions require R to be a power of two between 2 and 16, N to
be divisible by 16R, and both the output address and row stride to be divisible
by 16R. Separate cases exercise the original tile writer when either address
condition is absent. The INT8 and INT16 RAM capacities remain unchanged.

Results, simulator source hashes, binary hashes, input descriptions, and memory
images are written under `build/is_output_coalesce`. `--out` selects another
result directory. An existing matching build can be reused with `--build-dir`
and `--skip-build`; source hashes are checked before running it.
