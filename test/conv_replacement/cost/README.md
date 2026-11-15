# Static cache-policy storage audit

Run from the repository root:

```sh
python3 test/conv_replacement/cost/audit.py
```

The script reads the current production cache, predictor, frontend and
scheduler declarations. It checks the expected register inventory and emits
`build/conv_replacement/cost/cost.json`; `--out` selects another generated
report path. It does not read an archived report, saved source snapshot, or
previous synthesis log.

The report separates the 512 B, 1 KiB and 2 KiB data capacities from tags,
valid bits, LRU bits, 32-bit next-use ranks, the 16-byte transient buffer, and
shared control registers. It also lists multiplication, shifting and
comparison expression sites. Counts are logical declared bits and expression
sites. They are not counts of mapped multipliers or physical RAM macros.

This check performs no synthesis or simulation. It makes no area, Fmax,
power, or whole-NPU resource claim. Existing frontend/datapath state and the
shared block-DMA command/owner/descriptor registers are outside its limited
cache-policy accounting. A changed register structure causes an explicit
inventory assertion rather than silently reusing an old total.
