# 偏置驻留范围与尾块行数

## 当前设计

两个数据银行并行判断偏置组的起点、末端和装载状态，`active_bank` 选择一位驻留结果。范围上界先将请求起点、请求长度和银行末端压缩为两个操作数，再通过三位产生与传播条件及三分支归并树计算最终进位。各层普通布尔信号保留组合边界，完整扩展位用于处理计数范围末端。

DMA 完整行数和扣除尾块后的行数并行计算，尾块范围判断选择最终行数。状态更新边沿、公开输出周期、复用顺序、存储深度与数据精度保持不变。

## 验证结果

`run_formal.py` 对完整 `bias_loader` 比较原有状态、存储位、对应组合观察点及公开输出。六组配置共 118,593 个比较位通过等价证明，公开输入和握手序列没有数值限制。参考提交为 `aa0a169c7d4a514523e2fb50b5037bdca42c7340`。

| SIZE | BUS_WIDTH | COUNT_WIDTH | GROUP_BLOCKS_MAX |
|---:|---:|---:|---:|
| 4 | 32 | 1 | 1 |
| 16 | 32 | 12 | 4 |
| 16 | 64 | 28 | 32 |
| 16 | 64 | 29 | 32 |
| 16 | 128 | 29 | 32 |
| 16 | 64 | 32 | 1 |

`check_four_state.py` 提取实际范围判断逻辑，覆盖 1、5、29、32 位计数及装载索引共享选项，完成 142,720 次严格四态结果比较。

`test/bias_loader_reuse/run.py` 的 392 个场景通过，合计 193,571 个周期和 880 个 DMA 请求。覆盖 WS/IS、32/64 位总线、一至三十二个分块的容量、尾块、银行复用、DMA 等待和配置重载。每个场景检查 DMA 地址范围、请求次数及偏置数值。

## 完整模块映射

测量对象为完整 `bias_loader`，参数为 `SIZE=16`、`DATA_WIDTH=32`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`，包含控制器、缓冲区和两个数据银行。

| 指标 | 当前结果 |
|---|---:|
| 逻辑 LUT | 1,331 |
| 触发器 | 1,227 |
| CARRY4 | 91 |
| 推断得到的 RAMB36E1 | 1 |
| DSP48E1 | 0 |
| 最长寄存器间组合路径 | 9 级 |

采用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`。映射组合图完整，寄存器间路径包含数据和同步控制输入。RTL 使用普通可综合逻辑及推断存储；资源名称描述综合结果。150 MHz 需要完整 SoC 布局布线后的器件时序报告确认。

[measurement.json](measurement.json) 保存当前源码 SHA-256、逐配置证明位数、四态结果、数值测试及映射摘要。`collect_results.py` 要求这些结果使用相同源码。

## 复现

在仓库根目录执行，需要 `pyosys`、Icarus Verilog 和 Verilator：

```bash
python test/bias_residency_timing/run_formal.py \
  --reference-rev aa0a169c --out build/bias_residency_timing/formal
python test/bias_residency_timing/check_four_state.py \
  --reference-rev aa0a169c --out build/bias_residency_timing/four_state
python test/bias_loader_reuse/run.py \
  --out build/bias_residency_timing/numeric --jobs 1
python test/bias_residency_timing/prepare_measurement.py \
  --reference-rev aa0a169c --out build/bias_residency_timing/inputs
python scripts/fpga/open_fpga_synth.py \
  --source-root build/bias_residency_timing/inputs/current \
  --case-config build/bias_residency_timing/inputs/cases.json \
  --cases loader_current --max-register-path-cells 14 \
  --out build/bias_residency_timing/mapping \
  --lock-file /tmp/npu_synthesis_20261121.lock
python test/bias_residency_timing/collect_results.py \
  --formal build/bias_residency_timing/formal \
  --four-state build/bias_residency_timing/four_state \
  --numeric build/bias_residency_timing/numeric \
  --mapping build/bias_residency_timing/mapping/loader_current \
  --out build/bias_residency_timing/measurement.json
```
