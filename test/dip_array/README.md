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

## 权重加载的双输出查找表

计算单元在预取写入和权重交换之间选择下一拍预取数据。FPGA 分支中相邻两位共用 `LUT6_2` 的两个输出，写入使能仍由原有的加载和交换事件决定。权重容量、事件优先级、数据传递和乘加结果的周期保持一致。

```sh
python3 test/dip_array/weight_mux_formal.py
python3 scripts/fpga/open_fpga_synth.py --cases array --out build/array_measure
```

形式检查直接读取实际计算单元及官方 `LUT6_2` 模型，对输入宽度、权重宽度和累加宽度的 `1/1/2`、`8/8/32`、`16/8/32`、`16/16/32`、`17/17/40` 五组参数证明全部对应寄存状态和输出等价，共 542 个比较位。四态仿真检查 100,000 个周期中的未知权重、未知输入及连续交换，完成 200,001 次输出和寄存状态比较。

在 `SIZE=16`、`DATA_IN_WIDTH=16`、`WEIGHT_WIDTH=16` 下，Yosys 0.71+40 的阵列独立综合结果为 2,593 个逻辑 LUT、11,807 个触发器和 256 个 DSP48E1。使用同样参数和工具测量提交 `4830c56`，对应逻辑 LUT 数为 4,401。此处统计映射后的逻辑单元，整机占用由器件布局结果确定。
