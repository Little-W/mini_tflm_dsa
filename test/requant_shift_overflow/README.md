# 量化移位的溢出检测

`requant_shift_pipeline` 在粗移位之前检查原始乘积的三个有效高段，在细移位阶段按保留位置并行归并符号差异。商、保护位、舍弃位、两级寄存和推进使能保持相同含义。输入含未知位时使用完整移位结果的范围表达式。

## 功能验证

参照提交为 `548bda54`。检查覆盖 generic、SYNTHESIS、XILINX_FPGA 及两宏同时启用四种配置。

- 完整移位流水和完整 `requant_compute_lane` 通过 12 项形式等价检查。计算通道同时覆盖立即参数和延迟参数两种配置，外部输入均无约束，比较全部公开输出和每周期状态行为。
- 四态仿真完成 1,048,576 次结果比较，覆盖全部移位量、正负边界、未知乘积位、未知移位位以及推进使能保持。
- `vec_requant` 及其余依赖文件与参照提交逐字一致，完整计算通道的接口等价适用于其全部实例。

## 完整模块综合

独立模块测量配置为 16 个通道、2 个计算通道、512 行输入缓冲、64 位总线，支持八位和十六位输出。使用相同预综合与 LUT 映射设置：6667 ps 目标、300 ps 连线成本、最大 8 输入 LUT 成本模型，并检查 ABC9 映射等价。

| 指标 | 参照实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 2,259 | 2,233 |
| LUTRAM 名义位置 | 64 | 64 |
| SRL 名义位置 | 14 | 14 |
| 触发器 | 1,290 | 1,290 |
| 推断 DSP | 18 | 18 |
| RAMB18 等效块 | 19 | 19 |
| 最长寄存器间组合级数 | 10 | 10 |

资源与路径详见 `measurement.json`，形式和四态检查详见 `validation.json`。实际器件频率由器件布局布线后的时序报告确认。

## 重现

```sh
python test/requant_shift_overflow/run.py --out build/requant_shift_validation --jobs 2
python test/requant_shift_overflow/measure.py --out build/requant_shift_measurement
```
