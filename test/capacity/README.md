# Capacity configuration checks

Run the software regression through Make or directly with Python:

```sh
make capacity-test
python3 -m unittest discover -s test/capacity -p 'test_*.py' -v
```

They check budget and scheduling invariants, exercise failed and repeated
configuration updates, and inspect real Make entry points. A recording compiler substitute
checks whether the UVM Make entry point rebuilds when effective configuration
changes and reuses the binary when it does not. This is a dependency test, not
an RTL compile or simulation.

The host tests compile the C planner and both driver implementations when a
native C compiler is available. They compare C and Python decisions across
supported capacities, representative workloads, WS/IS, adaptive/RAW32 PS storage and explicit
request limits. The generator checks reconstruct complete INT32 accumulators
from generated input bytes and verify the expected outputs. The shared-memory
checks include all supported bank sizes, exact per-bank PS reservations, and
the R=64 capacity of four 8 KiB IA banks. All writable test configurations and binaries live in
temporary directories; the checked-in `config/npu.mk` is not modified.

Python uses only its standard library. Make tests skip if GNU Make is absent;
C tests skip if no native C compiler is available. VCS, a RISC-V toolchain and
an RTL compiler are not needed for this regression.

## Terminal configuration editor

`test_menuconfig.py` checks the draft/save transaction, byte-unit input,
dependent PCR/RAW settings, failed optimization, external-edit protection,
and configuration creation. It also checks all four Make entry points and
rejects mixed edit/build goals before any configuration is changed.

On POSIX systems with GNU Make and Python curses, three tests open **real
pseudoterminals** and run `make menuconfig` with disposable configuration files:

- Edit the budget, optimize in memory, cancel an exit, save, and quit.
- Attempt an over-budget save, observe the error, and discard the draft.
- Resize from 80×24 to 40×8 and back, then exit without modifying the file.

The PTY driver uses normal navigation and editor keystrokes, with a controlling
terminal and foreground process group; it does not replace curses or the
configuration editor. Raw terminal transcripts are written to
`build/capacity/menuconfig/*.pty.log`. These are functional editor checks, not
RTL simulations. On platforms without POSIX PTYs/curses, only those terminal
tests are skipped; the configuration and noninteractive CLI checks still run.

Run just the menuconfig regression with:

```sh
python3 -m unittest discover -s test/capacity -p test_menuconfig.py -v
```

## RTL capacity elaboration

For a real RTL elaboration, first solve or select a legal PCR configuration,
then use a Verilator with `--json-only` support (validated with version 5.48):

```sh
python3 test/capacity/check_elaboration.py --config config/npu.mk

NPU_CONFIG=config/npu_fpga.mk python3 test/capacity/check_elaboration.py \
  --output-root build/capacity/fpga_elaboration
```

`--config` selects an explicit file; otherwise `NPU_CONFIG` is used, with
`config/npu.mk` as the default. `--verilator /absolute/path/to/verilator` selects another executable. If the
installation requires `VERILATOR_ROOT`, set that variable as for an ordinary
Verilator build. `--output-root` selects the result directory. The script checks
the elaborated shared IA/PS banks, directory, fixed buffers, and sequential
state against the configuration. It writes the effective bank dimensions, AXI
data width, compiler command, and source hashes into `result.json`.
It deletes the rebuildable AST by default; `--keep-tree` retains it.

### 只读表容量

展开统计通过明确的模块及数组名称识别只读表，并检查实际 AST 中的完整
常量赋值、逐项地址覆盖和时钟边沿读取。只读表要求所有元素均有常量值，
运行期间保持只读。普通 `initial` 赋值不会自动成为存储容量统计对象。

`vector_engine.avg_reciprocal` 的默认容量为 `257 × 18 = 4626 bit`。
报告将它列为 `vector_pool_reciprocal_rom`，同时纳入 `buffer_arrays_bits`
及容量规划程序的预算。`read_only_arrays_bits` 和 `read_only_declarations`
保存独立的只读容量及层次信息。`sequential_bits` 统计时序状态，
`read_only_bits` 统计只读表，两者之和为 `total_bits`。

七个 8 KiB 共享存储块的生产配置使用 999134 位逻辑存储数组，包含上述
只读表；预算按字节向上取整为 124892 字节，低于 128 KiB。普通触发器和
流水线寄存器在完整逻辑状态统计中单独保留。只读表的实际 FPGA/ASIC AST
检查命令为：

```sh
python3 test/vector_pool_reciprocal/run_capacity.py \
  --verilator /absolute/path/to/verilator \
  --out build/capacity/vector_pool_reciprocal
```

This checks the actual array sizes seen by the RTL compiler. The shared RAM
uses `SHARED_BANK_BYTES` in {2048, 4096, 8192} and `SHARED_BANK_COUNT` in 6..9.
`NPU_AXI_DATA_WIDTH` selects a 32-bit or 64-bit AXI4 data bus; AXI-Lite retains
32-bit data and 16-bit addresses. SRAM macro allocation is reported separately
from logical storage. The `physical_shared_memory` report separates logical
data, allocated data, unused data, and FPGA parity capacity. Use the shared-array
backend and complete reference outputs to verify matrix execution.

The parameter regression checks all 24 combinations of bus width and legal
shared bank geometry, capability reporting, DMA limits, and 4 KiB splitting:

```sh
python3 test/performance_analysis/validate_configuration_bounds.py \
  --verilator /absolute/path/to/verilator \
  --out build/capacity/configuration_bounds
```

## Physical shared RAM mapping

The ASIC preset is [`config/npu.mk`](../../config/npu.mk), with seven 2 KiB
banks. It supports 2, 4, and 8 KiB banks, each assembled from complete
`RAMTP128X16` data arrays. The FPGA preset is
[`config/npu_fpga.mk`](../../config/npu_fpga.mk), with seven 8 KiB banks.
FPGA project entries require the 8 KiB bank size. Both presets support six
through nine banks.

The physical checks use the production shared RAM and report the synthesis
tool, source hashes, cell counts, and data capacities:

```sh
python3 test/shared_ia_ps/check_asic_mapping.py \
  --yosys /absolute/path/to/yosys --out build/capacity/asic_shared_mapping

python3 fpga/vivado/tflm_ai_dsa_soc/scripts/check_shared_ram.py \
  --yosys /absolute/path/to/yosys --out build/capacity/fpga_shared_mapping

python3 fpga/vivado/tflm_ai_dsa_soc/scripts/test_npu_config.py \
  --out build/capacity/fpga_configuration --picorv32 /absolute/path/to/picorv32
```

The ASIC check expands `smic40_sram_1r1w` with macro interface declarations and
verifies dimensions, counts, and connections for all 12 bank configurations.
Foundry timing uses the actual library and ASIC synthesis flow. The FPGA check
performs Yosys `synth_xilinx -family xc7` for all four bank counts. It checks
two `RAMB36E1` cells per bank, synchronous 1R1W access, full data capacity, zero
parity write inputs, and the absence of LUTRAM. The Tcl configuration check
records project properties through command replacements.

The detailed mapping tables and report fields are in
[Shared RAM mapping](../../docs/shared_ram_mapping.md).
