# 前端解码边界比较

前端的行尾判断直接使用两个模加法等式及和值最高位。三个逐步解码计数器的
末项判断通过 `add_equal` 与数据加法并行计算。全部寄存器更新、配置、请求接受、
错误处理和输出周期保持相同；当前实现没有增加状态位。

## 形式验证

参考提交为 `f923581080e653c034a30692ed72613f62236cc2`。
`run.py` 从实际前端源码提取运算和实例，核对其余 RTL 逐字相同，并完成以下证明：

| 检查内容 | 输入及状态范围 | 结果 |
| --- | --- | --- |
| 位置行尾选择 | 96 位任意输入，完整原始减法、加法和两个 `add_equal` 实例 | 通过 |
| 输出宽度为零 | 任意位置输入和保存的末列值 | 通过 |
| 配置状态关系 | 32 位状态，初始复位后任意配置数据及握手 | 时序归纳通过 |
| 三个逐步解码边界 | 32 位计数器与三个 16 位范围，共 80 位任意输入 | 三个结果均相同 |

配置状态证明覆盖输出宽度与保存末列之间的关系，包含复位和重新配置。
比较保留原有 32 位加法的回绕行为，包括范围为零和计数器为 `32'hffff_ffff` 的输入。

## 独立映射

测量范围包含实际窗口队列、DMA 描述符选择及完整前端。线性 DMA、缓存、预测器及
三个 AXI 辅助模块作为六个接口边界。使用 `SIZE=64`、`IM2COL_SIZE=16`、
`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、`CONV_CACHE_SETS=128`、`LANES=4`。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 7,705 | 7,795 |
| RAM LUT | 56 | 56 |
| FF | 3,487 | 3,487 |
| DSP48E1 | 33 | 33 |
| CARRY4 | 855 | 855 |
| 最长寄存器路径 | 16 | 15 |

路径分析使用完整逐位连接，并计入 DSP 内部组合计算。表中 LUT 为布局前的原语计数；
物理 LUT 数和完整 SoC 路径由对应版本的整机布局与分析给出。

## 实际 FPGA 数值与周期测试

数值测试包含实际窗口仲裁器、队列、DMA、前端、缓存及预测器，使用官方 FPGA 原语模型，
为全部生成的 C++ 编译单元启用未定义行为检查。数值测试参数为 `BUS_WIDTH=32`、
`DMA_SIZE=64`、前端 `SIZE=16`、`CACHE_BLOCKS=4`、`CONV_CACHE_SETS=128`、`LANES=4`。

完整窗口测试接收 422 个请求，完成 418 个，复位取消 4 个，检查 4,457 个输出数值和
19 次预期错误。驻留窗口的 1,545 行接口记录与参考实现逐字相同；128 个请求产生
512 次响应，最大响应间隔为 3 个周期，首末响应跨度为 1,534 个周期。

短窗口测试先保存四个请求并施加响应背压，再对每种列数连续发送 64 个请求。

| 每个请求的列数 | 响应次数 | 最大响应间隔（周期） | 首末响应跨度（周期） |
| --- | ---: | ---: | ---: |
| 1、2、3、4 | 64 | 2 | 126 |
| 5、7、8 | 128 | 3 | 382 |
| 12 | 192 | 3 | 574 |
| 15、16 | 256 | 3 | 766 |

十种列数全部通过；包含缓存准备请求，共完成 641 个请求和 4,688 个输出数值，运行 4,149 个周期。

逐步解码测试组合五种输出行宽（1、3、5、7、17）、两种卷积核尺寸（5、7）及三种通道数
（5、7、17），共 30 种配置。每种配置首先请求最后一个输出位置及最后一个归约元素，
使三个逐步解码过程都得到实际执行，再运行随机坐标和背压请求。
两份 FPGA 模型各完成 960 个请求、7,916 个输出数值，运行 249,416 个周期。
保存的 249,411 行窗口、AXI 和忙碌状态记录逐字相同，全部独立数值检查通过。

## 运行方法

```bash
python3 test/frontend_decode_boundaries/run.py --out build/frontend_decode/formal
python3 test/window_dma/run.py --fpga --jobs 1 --verilator verilator-modern --out build/frontend_decode/fpga
python3 test/window_descriptor_stage/short_windows.py --model-dir build/frontend_decode/fpga --out build/frontend_decode/short --verilator-include /path/to/verilator/include
python3 test/frontend_decode_boundaries/numeric.py --model build/frontend_decode/fpga --reference-model /path/to/reference/fpga --proof build/frontend_decode/formal/summary.json --out build/frontend_decode/boundary --verilator-include /path/to/verilator/include
python3 test/window_descriptor_stage/synthesis.py --reference f9235810 --out build/frontend_decode/synthesis
```

逐步解码比较复用两份已通过完整窗口测试的模型对象，并核对模型源文件、形式验证报告及
对象文件的 SHA-256。正式结果保存在 `docs/data/frontend_decode_boundaries_validation.json`。
