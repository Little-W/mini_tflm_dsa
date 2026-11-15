# Official RISC-V memory runtime

Both CPU baseline and hardware Conv firmware link the same optimized RISC-V
`memcpy` and `memset` from newlib **4.5.0.20241231**. The original SiFive sources
are preserved without edits. `memcpy.c` copies aligned words in an unrolled
loop; `memset.S` uses groups of word stores. Neither routine uses the
size-optimized byte-loop configuration.

[`package_sources.py`](package_sources.py) contains the upstream package URLs,
archive identities and SHA-256 values of the preserved source subset. These
are source provenance, not prebuilt runtime objects. `COPYING.NEWLIB` and the
original file headers retain the upstream licenses. Only the two routines and
their transitive private headers are included; public headers come from a
matching newlib development package. No target library binary is checked in.

## Build

```sh
python3 test/conv_soc_perf/runtime_newlib/build.py \
  --gcc /path/to/riscv64-unknown-elf-gcc \
  --newlib-include /path/to/newlib/include \
  --out build/conv_soc_runtime
```

The output directory may be outside the repository. Pass its generated
`libnewlib_memory.a` to the SoC runner's `--runtime-lib`, and pass the same public
header directory to `--newlib-include`. A complete bare-metal toolchain with
target libc can instead use the runner's normal `-lc` path; reproducing a
particular performance measurement requires the same runtime and compiler.

`build.py` verifies the original source hashes, records all compiler
dependencies, checks for unresolved symbols, and emits build commands, ELF
attributes, library hash, GCC version and selected RV32 `libgcc` hash under
`--out`. None of these generated files is a source input or patch payload.

The build uses `-O3 -march=rv32im_zicsr_zicntr -mabi=ilp32`, without compressed
instructions. `-fno-builtin` and `-fno-tree-loop-distribute-patterns` prevent a
memory loop from becoming a recursive library call. The only warning exception
is unused parameters in unchanged newlib locale inline headers.

With GCC 14.2.0, both `rv32im_zicsr` and `rv32im_zicsr_zicntr` select the
`rv32im/ilp32` multilib and accept `rdcycle`. The memory routines require only
RV32I loads, stores and arithmetic. Compile/link checks establish runtime
provenance; full numerical correctness and cycle measurements come from the
separate real CPU SoC benchmark.
