# Static weight bounds for retained partial sums

`drivers/dsa_ps_bound.h` derives a row-size bound from immutable S8 weights
and the complete legal S8 input interval, including both operands' offsets.
It supports ordinary strided weights and packed 16 × 16 tiles. Preparation
stores the selected PS control bits in the descriptor; Invoke reuses them.

For a corrected input interval `[x_lo, x_hi]`, the minimum contribution of a
weight is `min(w*x_lo, w*x_hi)` and the maximum is `max(w*x_lo, w*x_hi)`.
The input interval contains zero, so extending a prefix can only widen its
range. The helper scans the last retained prefix,
`16 * floor((K - 1) / 16)`, and accumulates positive and negative weight sums
for each output channel. Final-K bias is excluded. The result is 32, 48,
or 64 bytes for one complete 16-lane INT32 row. A zero result keeps the
ordinary capacity estimate.

The tests cover inclusive S16 and S24 limits, values immediately outside
those limits, all 65,536 endpoint combinations of a 16-element input,
random weights and zero points, ordinary row padding, packed channel/K
tails, the largest supported reduction, and invalid parameters. The
independent reference checks every nonfinal K16 prefix. AddressSanitizer
and UndefinedBehaviorSanitizer run on the C++ test.

```bash
python3 test/ps_bound/run.py --out build/ps_bound
```

To check the constants in all prepared Conv and Dense operators, add the
prepared model directory. The Python environment needs NumPy and FlatBuffers,
as used by the model preparation tools.

```bash
python3 test/ps_bound/run.py \
  --prepared /path/to/prepared \
  --out build/ps_bound_models
```

`model_bounds.json` records each operator's input interval, retained prefix,
minimum and maximum, selected row size, and model/weight hashes. Each
model is checked in both ordinary and packed layouts. `summary.json`
contains test counts and executable/source hashes.
