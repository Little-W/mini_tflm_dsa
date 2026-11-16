# AXI linear write segmentation

This test instantiates the production `axi_linear_block_dma` write engine. Each logical row supplies 1–256 source words and individual byte masks. The model checks every physical AW and W transfer, every source handshake, and the complete 2 MiB memory image after each command.

Run both supported outstanding profiles:

```sh
python3 test/linear_dma_write_4k/run.py --outstanding 1 4 --jobs 2
```

The test covers:

- Byte offsets 0–3, full and partial masks, zero masks, changing row offsets and repeated row addresses.
- 4 KiB boundaries, 256-word rows, the additional physical word required by an unaligned row, and descriptors containing 256 rows.
- Independent AW, W, B and source delays; stable channel payloads under backpressure; physical outstanding limits of 1 and 4.
- SLVERR and DECERR on initial, intermediate and final physical bursts, followed by another command without reset.
- Completion only after all source words, write data and B responses have completed.

Each physical burst must contain at most 256 beats and remain inside one 4 KiB page. Logical byte masks and source word counts are checked independently of physical segmentation. Fixed timing and deterministic random timing are both executed.

An optional reference RTL file can compare the measured cycle count of every single-segment command:

```sh
python3 test/linear_dma_write_4k/run.py \
  --reference-rtl /absolute/path/to/axi_linear_block_dma.sv
```

`summary.json` contains individual case cycles and counters, the RTL SHA256 and the build manifests. Each build manifest includes source hashes, the simulator hash and the exact build commands.
