# Capacity configuration checks

Run the software regression through Make or directly with Python:

```sh
make capacity-test
python3 -m unittest discover -s test/capacity -p 'test_*.py' -v
```

They compare the solver against the independently verified 2026-11-15 study,
check budget and scheduling invariants, exercise failed and repeated config
updates, and inspect real Make entry points. A recording compiler substitute
checks whether the UVM Make entry point rebuilds when effective configuration
changes and reuses the binary when it does not. This is a dependency test, not
an RTL compile or simulation.

The host tests compile the C planner and both driver implementations when a
native C compiler is available. They compare C and Python decisions across
four capacities, eight workloads, WS/IS, nominal/raw PS storage and explicit
request limits. The generator checks reconstruct complete INT32 accumulators
from generated input bytes and compare legacy output hashes with the original
repository revision. All writable test configurations and binaries live in
temporary directories; the checked-in `config/npu.mk` is not modified.

Python uses only its standard library. Make tests skip if GNU Make is absent;
C tests skip if no native C compiler is available. VCS, a RISC-V toolchain and
an RTL compiler are not needed for this regression.

For a real RTL elaboration, first solve or select a legal PCR configuration,
then use a Verilator with `--json-only` support (validated with version 5.48):

```sh
python3 test/capacity/check_elaboration.py --config config/npu.mk
```

`--verilator /absolute/path/to/verilator` selects another executable. If the
installation requires `VERILATOR_ROOT`, set that variable as for an ordinary
Verilator build. `--output-root` selects the result directory. The script checks
the elaborated A/B panel RAMs and PS pool against the configuration and writes
the configuration, compiler command and source hashes into `result.json`.
It deletes the rebuildable AST by default; `--keep-tree` retains it.

This checks the actual array sizes seen by the RTL compiler. It does not model
SRAM macro rounding or constitute a functional matrix computation. Use the PCR
backend and a complete golden-output case for the latter.
