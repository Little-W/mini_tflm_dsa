# DiP array verification

This test supplies complete input rows and compares every output with an
ordinary integer matrix product. The reference sums products in 64 bits and
then applies the array's modulo-2^32 accumulator behavior. Weight-column
rotation is performed only while preparing the physical load sequence.

```bash
python3 test/dip_array/run.py \
  --verilator /path/to/verilator \
  --out build/unified_validation/dip_array --jobs 3
```

The default run covers array sizes 2, 3, 4, 8, and 16, with S8×S8,
S16×S8, and S16×S16 operands. Each configuration checks continuous rows,
input gaps, short and long streams, signed extremes, INT32 wraparound,
partial sums from previous K blocks, and loading shadow weights during
active computation. Every column must produce the same input row after
exactly `SIZE` processing-element cycles. Output cycles before and after
the valid interval must contain zeros.

Each configuration records its source and executable hashes, command,
value counts, timing checks, and undefined-behavior sanitizer status.
The aggregate result is written to `summary.json`.
