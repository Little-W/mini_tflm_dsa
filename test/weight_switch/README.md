# Complete NPU weight-switch tests

`run.py` sends the same matrix cases through the complete NPU with runtime RAW32
and adaptive partial-sum storage. It checks every accumulator before requantization,
every output byte, all protected memory, and every saved and recovered PS row.
The reference uses an ordinary integer matrix product and the NMSIS integer
requantization rules.

The cases cover continuous single-K WS groups, partial K and output-channel tiles,
unequal row groups, packed operands, maximum IA reuse, output FIFO capacity,
bias, per-channel quantization, IS, S16 input and output, multiple K tiles, and
explicit frame scheduling. Each case runs with fixed AXI response timing and with
deterministic random read/write backpressure.

Two short-group cases, M17/R2 and M33/R4 with K16/N519, permit AW and W
handshakes during only 32 cycles of each 512-cycle period. Read timing remains
unchanged. This fills the output banks while successive groups contain partial
tiles. The test stores this memory-model setting in configuration word 63; that
word is not submitted to the NPU register interface.

```bash
python3 test/weight_switch/run.py --out build/weight_switch/default \
  --verilator "$VERILATOR" --jobs 2
python3 test/weight_switch/run.py --out build/weight_switch/fpga \
  --bank-bytes 8192 --verilator "$VERILATOR" --jobs 2
```

The passive observer records weight commits while earlier rows remain in the
array, first input rows arriving before an earlier group finishes, two weight
versions simultaneously selected by valid array rows, IA group gaps, output bank occupancy,
and AXI write stalls. FIFO write availability is checked for every S8 and S16
output row. Group completion counts use delayed row metadata and remain valid
when a single-K group does not require a PS-store command.

To compare two source checkouts, run this test script twice with the same test
files and hardware profile. The second run checks all input and reference hashes
before calculating cycle ratios:

```bash
python3 test/weight_switch/run.py --rtl-root /path/to/first/checkout \
  --out build/weight_switch/first --verilator "$VERILATOR" --jobs 2
python3 test/weight_switch/run.py --rtl-root /path/to/second/checkout \
  --out build/weight_switch/second --verilator "$VERILATOR" --jobs 2 \
  --reference build/weight_switch/first/summary.json
```

`--sim` reuses an existing build after checking the RTL, compiled observer,
derived AXI memory, and executable hashes. Build-script and execution-script
hashes are recorded separately; input and expected-output hashes must match for
cycle comparisons. Direct streaming is counted at the actual IA group trigger.
`--cases` selects named cases; `--generate-only` writes reproducible inputs and
references without compiling RTL. `summary.json` contains numeric results,
overlap counters, source hashes, and optional comparisons. The `.events.txt`
files record exact clock counts for input starts, input ends, output ends, and
weight commits. Generated compiler objects are removed after a completed run;
the executable, build description, logs, and results remain available.
