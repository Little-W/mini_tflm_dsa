# 量化寄存加法验证

`vec_requant_full` 在阶段 10 使用 `requant_registered_sum` 保存 36 位商、输出偏移和舍入进位之和。阶段 0 至 2 使用共享乘法器保存输入、部分积和完整乘积，详见 [共享量化乘法器验证](../requant_product/README.md)。

本目录 `measurement.json` 保存版本 `038a095` 的寄存加法测量，下面的资源表和阶段 2/10 比较对应该固定版本。`run_integration.py` 根据当前源文件中实际使用的加法实例验证阶段连接；当前完整量化验证 36 位 `rounded_s10`。

## 周期与算术

| 寄存阶段 | 保存的结果 |
|---|---|
| 0 | INT32 输入、乘数和移位量 |
| 1 | 有符号部分积 |
| 2 | 48 位高位和 16 位低位构成的完整乘积 |
| 3 至 9 | 分级移位、溢出方向、商和舍入进位 |
| 10 | 商、INT8 输出偏移及舍入进位之和 |
| 11 | 激活范围限制和 INT8/INT16 饱和结果 |

完整通道保持十二个寄存阶段，每周期可接收一组输入。两个加法单元都以 `!init_cfg` 驱动 `CEP`；配置刷新期间保持算术寄存结果。`rst_n` 继续控制原有有效位和输出清零，算术寄存器沿用原有不复位的行为。

部分积高位按 48 位模加保存，舍入结果按 36 位模加保存。`s16_mode` 为 1 时输出偏移为零，其余情况对 `dst_offset_r` 进行符号扩展。`CARRYIN` 直接接收单比特舍入增量。ASIC 和通用仿真分支使用相同位宽和使能条件的 `always_ff`，FPGA 分支使用 DSP 的输出寄存器。

所有新增 RTL 位于现有 `rtl/npu/writeback/vec_requant.sv`，工程源文件列表保持兼容。存储容量和 REGFILE 接口保持不变。

## 验证结果

参考版本为 `1c081bc`，完整量化源的 SHA256 记录在 `measurement.json`。

- `run.py` 使用官方 `DSP48E1` 功能模型，证明 1、17、36、48 位两种实现共八组全输入算术等价。时钟使能每周期自由变化。
- `run_integration.py` 从参考版本的实际赋值和当前实例连接提取阶段 2/10，证明全部 84 位阶段输出一致，覆盖符号扩展、INT16 模式和任意配置暂停。
- 完整量化接口在 BUS32、BUS64 下各运行 256 个场景、528,662 个周期。全部 18 个输出在每个周期比较，包含无效周期的输出值。BUS32 比较 206,800 组向量，BUS64 比较 209,001 组向量。
- 接口场景覆盖 per-tensor、per-channel、WS、IS、INT8、INT16、DMA 参数装载、输入间隔、尾部通道、配置刷新和执行期间复位。
- 独立整数除法参考模型检查 320,000 个输出，四种配置全部通过；FPGA 配置加载官方 `LUT6_2` 和 `DSP48E1` 功能模型。
- 路径统计工具的十四项测试全部通过，包含起点和终点过滤后保留完整组合依赖的检查。

## 独立综合

综合顶层为 `vec_requant`，参数为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`，保留完整公共输出。器件为 `xc7a200tfbg484-3`，不启用全 SoC 的通用宽 ALU DSP 预算映射。

| 资源 | 参考实现 | 寄存加法实现 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 11,680 | 10,373 | −1,307 |
| LUT RAM 的标称 LUT 数 | 1,120 | 1,120 | 0 |
| SRL 的标称 LUT 数 | 192 | 192 | 0 |
| 外部触发器 | 9,476 | 7,588 | −1,888 |
| CARRY4 | 759 | 423 | −336 |
| DSP48E1 | 64 | 96 | +32 |
| 其中 PREG=1 | 32 | 64 | +32 |
| RAMB18/RAMB36 | 0/0 | 0/0 | 0/0 |

两个综合任务的最高内存使用量分别为 520.59 MiB 和 519.07 MiB。以上 LUT 数来自映射网表；实际物理 LUT 数由完整 SoC 布局后统计。

## 寄存器路径

`measure_paths.py` 对实际映射网表按寄存起点或终点筛选，统计相连组合单元。DSP 输入路径截止到原语输入，输出路径从 PREG 开始。

| 路径 | 参考实现 | 寄存加法实现 |
|---|---:|---:|
| 进入阶段 2 的外部组合单元 | 13 | 0 |
| 阶段 2 输出至下一寄存器 | 5 | 5 |
| 进入阶段 10 的外部组合单元 | 11 | 1 |
| 阶段 10 输出至下一寄存器 | 6 | 6 |
| 模块最长寄存器路径 | 17 | 17 |

阶段 2 原路径包含一个 LUT 和十二个 CARRY4；当前部分积寄存输出直接连接 DSP 输入。阶段 10 原路径包含两个 LUT 和九个 CARRY4；当前只有输出偏移的一个选择 LUT。新增的三十二个 DSP 都在 PREG 结束算术路径。

两个 `CEP` 均由主输入 `init_cfg` 取反产生，独立模块的寄存器起点统计不包含该主输入路径。最长十七个组合单元的路径位于量化参数 DMA 命令计算。DSP 内部延时和布线延时需要器件时序分析，此处组合级数不用于声明 150 MHz 已达到。

全 SoC `1c081bc` 的原生 DSP 数为 429。此修改预计增加至 461；启用 740 个 DSP 的预算时，需要重新选择其余通用算术单元。预算选择依据集成后的实际网表完成。

## 运行方法

在仓库根目录设置好 Yosys、Slang、Pyosys 和 Verilator 工具环境后执行：

```bash
python test/requant_registered_sum/run.py --out build/requant_registered_sums/formal
python test/requant_registered_sum/run_integration.py --out build/requant_registered_sums/integration --reference-rev 1c081bc
python test/requant_pipeline/run_interface.py --out build/requant_registered_sums/interface --reference-rev 1c081bc --bus-width 32 64 --verilator verilator-modern --jobs 2 --xilinx
python test/requant_rne/run.py --out build/requant_registered_sums/rne --verilator verilator-modern --xilinx
python scripts/fpga/test_netlist_metrics.py
python test/requant_registered_sum/prepare_measurement.py --out build/requant_registered_sums --reference-rev 1c081bc
python scripts/fpga/open_fpga_synth.py --source-root . --case-config build/requant_registered_sums/cases.json --cases reference registered_sums --out build/requant_registered_sums/synthesis --lock-file build/synth-small.lock
python test/requant_registered_sum/measure_paths.py --synthesis build/requant_registered_sums/synthesis --out build/requant_registered_sums/paths.json
```
