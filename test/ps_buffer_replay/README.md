# Partial-sum replay tests

This test compares `ps_buffer_wide_fifo` with an independent queue of complete frames. It checks every returned 64-bit value, queued frame count, remaining replay count, readiness, and exact-depth write address.

Three configurations cover depths 7, 17, and 16, with frame capacities 1, 3, and 2. Directed and deterministic random sequences exercise simultaneous frame completion and replay from an empty queue, replacement while an older frame is replayed, synchronous read/write collisions, repeated trigger levels, and circular addresses.

```sh
python test/ps_buffer_replay/run.py --verilator verilator
```

`--rtl` selects a source snapshot for review. `--out` selects the output directory. The runner saves compiler commands, source and executable SHA-256 values, run logs, and `summary.json`.
