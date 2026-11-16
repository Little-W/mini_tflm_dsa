# Ordered read descriptor tests

`run.py` builds the production `axi_linear_block_dma` with a byte-addressed AXI memory model and checks every returned data word, unpacked lane, row, column, slot, format, zero point, client tag, and completion error.

The command stream includes contiguous packed tiles, strided rows, unaligned INT8 and INT16 inputs, partial columns, 256-beat transfers, and transfers crossing a 4 KiB address boundary. Two descriptors receive error responses and are followed by valid descriptors. Commands remain asserted until `rd_start_ready`, and the address channel is checked for stability during backpressure.

Each build runs both fixed and randomized address/response delays. Every AXI address receives an independent eight-cycle response deadline, so multiple accepted descriptors can overlap their latency. The checks require early address issue with four AXI requests and four response contexts, and simultaneous completion and command acceptance with one response context.

Run the native 64-bit configuration:

```sh
python test/linear_dma_context/run.py --bus-width 64 --outstanding 4 --contexts 4
```

`--outstanding 1|4` controls physical AXI requests. `--contexts 1|4` controls independent logical descriptor metadata. `--bus-width 32|64` selects the data bus. `--dma-max-bytes` defaults to 256 bus beats; all physical transfers also respect 4 KiB boundaries. `--verilator` selects the compiler and `--out` selects the result directory.

The output directory contains the generated build commands, source and executable SHA-256 values, both run logs, and `summary.json`. The summary includes overlap counts, simultaneous request/response activity, error completions, and address backpressure cycles.
