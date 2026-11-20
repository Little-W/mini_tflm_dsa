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
exactly `SIZE` processing-element cycles.

Adjacent streams use different heights, zero or one boundary bubble, and
independent valid gaps. The first input row may coincide with a weight
selection change and the first load of the following weight tile. The test
checks the selector and selected weight at every valid physical row, including
cycles when different rows use different weight versions. It also checks
delayed loading, loading gaps, consecutive selector changes, and reloading
after reset. Existing weight registers hold both tiles; their total data
capacity is unchanged.

Each configuration records its source and executable hashes, command,
value counts, timing checks, mixed-version valid cycles, protected load cycles,
and undefined-behavior sanitizer status.
The aggregate result is written to `summary.json`.

## 权重加载和阵列周期检查

计算单元用条件表达式选择下一拍预取权重，装载事件和权重交换事件保持原有优先级。阵列保留两套权重寄存器，逐列控制直接连接各计算单元。

```sh
python3 test/compute_rtl/run_cell_formal.py --reference 653477ed --out build/cell_formal
python3 test/dip_array/run.py --sizes 3 16 --verilator verilator-modern --jobs 1 --out build/array_numeric
```

状态等价覆盖两种权重装载模式和五组位宽，共 1,139 个比较位。四态仿真检查 100,000 个周期中的未知权重、未知输入及连续交换，完成 200,001 次输出和寄存状态比较。规模 3、16 的六组数值配置完成 456 个场景和 486,788 次整数参考比较。具体参数、源码散列值及运行结果见 `test/compute_rtl/measurement.json`。
