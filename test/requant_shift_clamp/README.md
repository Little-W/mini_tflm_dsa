# 量化移位商的饱和输出

`requant_shift_pipeline` 对完整 64 位有符号乘积执行右移，并保留最近偶数舍入所需的信息。模块支持每周期一组输入，输出在七个使能采样边沿后产生。`i_en` 为零时，所有流水寄存器同时保持。

FPGA 实现将相邻两个商位的饱和和清零选择放入同一个 `LUT6_2`。每个单元接收两个数据位、移位溢出、原始符号和大移位条件。移位量大于 63 时输出零；其余情况下，发生溢出的正数输出最大 34 位有符号数，负数输出最小 34 位有符号数。最高一对数据位单独处理符号位。通用 RTL 使用相同的完整条件选择。

这一结构保留商、舍入增量、暂停行为及全部公开输出周期。完整量化仍包含十二个寄存阶段。

## 综合结果

生产配置为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`。参考提交为 `2f06471c`，综合采用 Yosys 0.71、ABC9 与 Xilinx 7 系列原语模型。完整量化模块的全部公开输出参与综合。

| 指标 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 7,953 | 7,687 |
| 分布式 RAM LUT | 1,120 | 1,120 |
| SRL LUT | 192 | 192 |
| 触发器 | 7,013 | 6,469 |
| DSP48E1 | 96 | 96 |
| 最长寄存器间组合单元数 | 15 | 15 |

独立移位通道由 222 个逻辑 LUT 减少至 201 个，触发器保持 287 个，最长组合路径保持 4 个单元。完整量化模块减少 266 个逻辑 LUT 和 544 个触发器。完整 SoC 的物理 LUT 位置与器件时序由整机实现单独统计。

## 功能检查

`run_formal.py` 使用完整 64 位乘积和全部 7 位移位量，对 FPGA 原语实现及通用实现分别进行时序归纳证明。数学参考直接计算六十四位商、余数和最近偶数舍入。两项证明均通过，延迟为七个使能采样边沿。

另对参考实现与当前实现进行完整状态等价比较，时钟使能不受约束。11,487 个等价比较位全部通过，覆盖任意暂停。

实际 FPGA 分支的完整接口比较使用官方 `LUT6_2` 和 `DSP48E1` 模型，检查配置、DMA 命令、参数读取、INT8/INT16 输出、有效信号和任务结束周期。

| 总线宽度 | 场景 | 周期 | 输出向量 | DMA 命令 | DMA 返回拍 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 32 | 256 | 528,662 | 206,800 | 922 | 12,322 |
| 64 | 256 | 528,662 | 209,001 | 958 | 6,496 |

全部检查通过。`measurement.json` 保存源码、参考实现、原语库、综合网表、仿真程序及运行记录的 SHA-256，并保存实际连接的最长寄存器路径。

## 运行命令

```sh
python3 test/requant_shift_clamp/run_formal.py \
  --out build/requant_shift_clamp/formal

python3 test/requant_pipeline/run_interface.py \
  --reference-rev 2f06471c --xilinx --bus-width 32 64 \
  --verilator "$VERILATOR_BIN" --jobs 2 \
  --out build/requant_shift_clamp/interface

python3 test/requant_shift_clamp/prepare_measurement.py \
  --out build/requant_shift_clamp/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_shift_clamp/inputs/cases.json \
  --cases reference_shift paired_shift reference_quant paired_quant \
  --out build/requant_shift_clamp/synthesis \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock
```
