# 配置形状结果寄存

`conv_im2col_frontend` 在接受配置的时钟边沿保存 `group_c` 和
`kernel_w` 的幂次检查结果。配置寄存器 `c` 与两个检查结果使用同一个
`cfg_valid && cfg_ready` 条件，复位结果均为零。分块解码直接读取保存的结果。
配置完成、配置错误、请求接受和数据输出的周期保持相同。

## 逐周期形式验证

参考提交为 `a0742c4526f63cafc72f800164a86cab547c4aea`。
`run.py` 直接提取参考文件和当前文件中的两个形状检查区域，核对其余前端源码
逐字相同，并核对配置寄存器的复位值、接收条件和全部赋值。

测试分别使用通用 RTL 与官方 `LUT6`、`LUT6_2` 功能模型进行时序归纳。
每种模式比较两个检查结果及对应的 32 位配置状态。初始复位之后，配置数据、
配置有效、配置就绪和复位输入均可任意变化。两种模式均通过，覆盖两个新增状态位。
该状态对应关系与其余源码相同的检查共同保证完整前端的逐周期行为保持相同。

## 实际 FPGA 窗口测试

窗口数值测试使用 `DMA_SIZE=64`、前端 `SIZE=16`、`BUS_WIDTH=32`、
`CACHE_BLOCKS=4`、`CONV_CACHE_SETS=128`，前端使用四个输出通道。
测试使用官方 FPGA 原语模型，并为全部生成的 C++ 编译单元启用未定义行为检查。

- 完整窗口测试接收 422 个请求，完成 418 个，复位取消 4 个，检查 4,457 个输出数值及 19 次预期错误。
- 覆盖随机坐标、背压、读错误排空、配置取消、复位、无效列数和普通请求与窗口请求并发。
- 连续驻留窗口的 128 个请求产生 512 次响应，响应间最大间隔为 3 个周期，首末响应跨度为 1,534 个周期。
- 1,545 行逐周期记录与参考实现逐字相同，完整测试的场景统计也相同。
- 队列先保存四个请求并停止接收响应，再对每种列数连续发出 64 个短窗口请求；十种列数均通过。

| 每个请求的列数 | 响应次数 | 最大响应间隔（周期） | 首末响应跨度（周期） |
| --- | ---: | ---: | ---: |
| 1、2、3、4 | 64 | 2 | 126 |
| 5、7、8 | 128 | 3 | 382 |
| 12 | 192 | 3 | 574 |
| 15、16 | 256 | 3 | 766 |

短窗口测试包括缓存准备请求，共完成 641 个请求、4,688 个输出数值，运行 4,149 个周期。
各项统计与参考实现相同。

## 独立映射

测量范围包含实际窗口队列、DMA 描述符选择及完整前端。线性 DMA、读缓存、
下一次使用预测器及三个 AXI 辅助模块作为六个接口边界。
综合参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、
`CACHE_BLOCKS=64`、`CONV_CACHE_SETS=128`、`LANES=4`。
表中 LUT 为布局前的逻辑原语计数，RAM LUT 按存储结构计算；物理 LUT 数由整机布局给出。
组合逻辑级数采用逐位连接分析，保留 DSP 内部组合计算的计数。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 7,653 | 7,705 |
| RAM LUT | 56 | 56 |
| FF | 3,485 | 3,487 |
| DSP48E1 | 33 | 33 |
| CARRY4 | 855 | 855 |
| 最长寄存器路径 | 15 | 16 |

两个形状检查结果已成为寄存器输出。当前独立映射的最长路径为
`p0` 经位置解码到 `row_wrap_q`，包含 16 个组合单元。
完整 SoC 的跨模块路径由对应版本的整机测量确定。

## 运行方法

```bash
python3 test/frontend_shape_register/run.py --out build/frontend_shape/formal
python3 test/window_dma/run.py --fpga --jobs 1 --verilator verilator-modern --out build/frontend_shape/fpga
python3 test/window_descriptor_stage/short_windows.py --model-dir build/frontend_shape/fpga --out build/frontend_shape/short --verilator-include /path/to/verilator/include
python3 test/window_descriptor_stage/synthesis.py --reference a0742c45 --out build/frontend_shape/synthesis
```

正式结果和源码 SHA-256 保存在
`docs/data/frontend_shape_register_validation.json`。
