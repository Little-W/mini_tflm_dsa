# 卷积样本偏移计算

`conv_im2col_sample_offsets` 对各通道的有符号八位样本加上配置偏移，分别保留九位结果。该纯组合模块保持完整计算边界，使用普通加法和 `use_dsp` 属性推断并行算术。前端原有寄存器、返回周期、输出掩码及 S8/S16 格式选择保持不变。

## 完整前端测量

参考提交为 `c3133900d28c7393eaeaed266fbbffb60854a580`。两侧均使用当前 SoC 的 `SIZE=16`、`LANES=8`、`BUS_WIDTH=64`、16 个缓存集合、2 路、128 字节缓存行、单请求返回队列，完整参数见 `production_synthesis.json`。两侧使用同一 Yosys、Slang、ABC9 与 Xilinx 器件库，批次大小为 64，并分别完成全部模块及连接图分析。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 17,017 | 16,883 |
| 分布式存储 LUT | 228 | 228 |
| 触发器 | 6,506 | 6,506 |
| DSP48 | 11 | 13 |
| RAMB36 / RAMB18 | 1 / 14 | 1 / 14 |
| 寄存器之间最长组合级数 | 17 | 15 |
| 输入到寄存器最长组合级数 | 16 | 15 |
| 寄存器到输出最长组合级数 | 16 | 13 |
| 输入到输出最长组合级数 | 3 | 3 |

逻辑 LUT 减少 134 个。资源计数与组合级数来自完整映射网表；150 MHz 的器件时序仍需布局布线延迟分析。该表仅比较此算术模块改动对完整前端的影响，其他前端修改和整机资源在集成源码上分别测量。

## 验证

响应格式化器的 8 组参数覆盖 1、2、4、8、16、20 个通道及 4、8、16 字节缓存读取宽度。组合证明覆盖全部输入、偏移、状态、掩码和每个字节位置，四态仿真覆盖所有输入位的 `X/Z`。所有公开输出通道均与参考实现及数学表达式一致，包括未使能通道。

从当前 RTL 提取的偏移计算模块另外完成 1、4、8、16 通道的映射后证明，使用完整 `cells_sim.v` 功能模型，不限制输入值，分别比较 9、36、72、144 个输出位。8 通道配置推断 2 个 DSP，局部逻辑 LUT 为 0。完整前端的组合图同时包含 DSP 的实际内部寄存器设置和端口依赖。

## 复现

在仓库根目录执行：

```sh
python test/conv_frontend/tools/check_return_formatter.py \
  --source-root . --reference-source-root /path/to/reference \
  --out build/sample_offsets/formatter
python test/conv_frontend/tools/check_sample_offsets.py \
  --out build/sample_offsets/mapped
python scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config test/conv_frontend/production_synthesis.json --cases frontend \
  --abc9-batch-size 64 --abc9-isolate-leaves --out build/sample_offsets/frontend
python test/output_configuration/analyze_interfaces.py \
  --top conv_im2col_frontend \
  --netlist build/sample_offsets/frontend/frontend/mapped.json \
  --pre-lut build/sample_offsets/frontend/frontend/pre_lut.il \
  --out build/sample_offsets/frontend/frontend/interface_paths.json
```

参考目录使用上述固定提交。输入源码、映射工具、网表与各检查结果的 SHA-256 保存在 `sample_offsets_validation.json`。
