# 偏置驻留范围与尾块行数

## 当前设计

两个数据银行并行判断当前偏置组的起点、末端和装载状态，`active_bank` 选择一位驻留结果。范围末端使用扩展一位的加法，保持完整计数范围内的进位。

DMA 完整行数和扣除尾块后的行数并行计算。尾块范围判断选择最终行数，行数减法与范围比较可以并行执行。`REG_WIDTH` 和 `COUNT_WIDTH` 的类型转换位置保持原有整数行为。

这两项修改保持全部状态更新边沿、公开输出周期、复用顺序、存储深度与数据精度。

## 完整模块测量

测量对象为完整 `bias_loader`，参数为 `SIZE=16`、`DATA_WIDTH=32`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`。参考版本为 `bdd7109f`。各项测量均包含控制器、缓冲区和两个数据银行。

| 综合方式 | 参考逻辑 LUT | 当前逻辑 LUT | 参考 DSP | 当前 DSP | 参考最长寄存器路径 | 当前最长寄存器路径 |
|---|---:|---:|---:|---:|---:|---:|
| 原生映射 | 1,287 | 1,268 | 0 | 0 | 21 | 16 |
| 宽算术 DSP 映射，最小位宽 8 | 1,075 | 1,054 | 14 | 15 | 15 | 11 |
| 宽算术 DSP 映射及物理面积成本 | 1,034 | 1,010 | 14 | 15 | 16 | 11 |

各方式的触发器均为 1,184，存储均为一个 `RAMB36E1`。DSP 映射允许总预算 740；当前独立模块增加的一枚可选 DSP 用于提前计算的减法。整机综合按全局预算选择算术单元。

物理面积成本映射下，寄存器至 `dma_rows_to_read` 的最长路径由 16 级缩短至 8 级；至 `bias_valid` 的组合输出边界由 8 级缩短至 7 级，至 `bias_group_valid` 由 9 级缩短至 8 级。路径报告包含实际 DSP 内部寄存器边界。逻辑 LUT 数是映射网表统计，物理 LUT 占用由整机布局统计。

## 验证

`run_formal.py` 使用完整 `bias_loader` 比较全部同名寄存器、存储位、组合观察点及公开输出。输入和握手序列均未施加约束；六组配置共 114,313 个比较位通过一步组合证明和两步时序归纳。参数包含：

| SIZE | BUS_WIDTH | COUNT_WIDTH | GROUP_BLOCKS_MAX |
|---:|---:|---:|---:|
| 4 | 32 | 1 | 1 |
| 16 | 32 | 12 | 4 |
| 16 | 64 | 28 | 32 |
| 16 | 64 | 29 | 32 |
| 16 | 128 | 29 | 32 |
| 16 | 64 | 32 | 1 |

`test/bias_loader_reuse/run.py` 的 392 个场景通过，合计 193,571 个周期和 880 个 DMA 请求。覆盖 WS/IS、32/64 位总线、一至三十二分块容量、尾块、银行复用、DMA 等待和配置重载。每个场景检查 DMA 地址范围、请求次数及偏置数值。

`measurement.json` 保存验证结果、逐配置证明位数、源文件 SHA-256 和各映射结果摘要。`collect_results.py` 检查正式证明、数值测试和综合快照均使用相同源码。

## 复现

在仓库根目录运行，Python 环境需能导入 `pyosys`，数值测试需要 `verilator`：

```bash
python3 test/bias_residency_timing/run_formal.py --out build/bias_residency_timing/formal_final
python3 test/bias_loader_reuse/run.py --out build/bias_residency_timing/numeric --jobs 1
python3 test/bias_residency_timing/prepare_measurement.py --out build/bias_residency_timing/inputs_rows
```

将生成的 `cases.json` 传入 `scripts/fpga/open_fpga_synth.py --case-config`，选择 `loader_reference` 和 `loader_current`。DSP 测量增加 `--wide-alu-dsp-budget 740 --wide-alu-minimum-width 8`；物理面积成本映射使用 `scripts/fpga/remap_fpga_luts.py --mode physical-cost`。

`measure_paths.py` 接收每项测量的 `mapped.json` 和对应 `pre_lut.il`，同时统计完整寄存器路径、实际行数寄存器边界和组合输出边界。
