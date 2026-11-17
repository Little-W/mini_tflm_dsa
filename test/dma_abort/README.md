# AXI write completion during task abort

Run `python3 test/run_cpp_rtl.py dma_abort` from the repository root.
The test uses Verilator and undefined-behavior sanitization and covers fourteen
aligned/unaligned and 4 KiB page split combinations with missing source data, stalled address
acceptance, stalled write data and partially transmitted ordinary writes.

The scoreboard checks each accepted AW against the complete W burst and B
response. Address and data payloads must remain stable during backpressure.
An already asserted W beat retains its data and byte strobes. Subsequent beats
complete accepted bursts with zero strobes when the producer has stopped.
Every scenario submits another command without resetting the DMA.

The result contains accepted-address and write-beat totals, source hashes,
the executable hash and sanitizer compilation details. Runtime files remain
under `build/dma_abort` or the directory selected with `--out`.
