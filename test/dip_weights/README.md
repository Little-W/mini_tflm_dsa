# DiP weight loading

This test drives the production `kernel_loader_buffer` through complete and
partial tiles, two-slot prefetch, and overlapping shadow loads. It checks
every physical weight against `B[(r+c) mod SIZE,c]`, then compares the matrix
outputs with an ordinary signed integer product. Tail rotation always uses
the physical array size.

```bash
python3 test/dip_weights/run.py \
  --verilator /path/to/verilator --out build/dip_validation/weights
```

The four configurations cover sizes 3, 4 and 16 with S8 and S16 weights.
The tests check weight-load values, the selected weight in every valid
physical row, and every final matrix output. A new input stream can start
while the preceding stream remains in lower array rows. The report records
those mixed-version valid cycles and verifies the row selector's timing.
C++ checks use UndefinedBehaviorSanitizer.
`summary.json` records source hashes, executable hashes and test counts.
