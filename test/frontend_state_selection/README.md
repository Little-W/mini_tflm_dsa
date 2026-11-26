# 前端坐标范围与运行状态选择

`conv_coordinate_step` 同时输出完整坐标和范围资格。高位零值条件按两位分组，每组直接使用六个操作数位；范围判断与完整坐标的进位计算各自保持组合边界。低位和值及范围差值仍由普通 RTL 算术产生。

`conv_im2col_stream_control` 分别计算下一行、下一卷积核位置和组内连续读取的请求资格。每种局部资格最多包含六个输入，公开请求标志直接归并这些结果。`conv_im2col_state_control` 并行准备普通操作、流式推进、描述符和错误响应的状态候选，在末级选择要保存的状态。

四个局部辅助模块分别保存在同名文件中，源码布局和每个端口的中文功能说明均通过工程检查。三个接口模块的端口、保存时刻和公开四态行为均保持一致。运行状态采用打包联合体连接枚举表示与位向量表示，保持各状态位并兼容 Slang、Verilator 和 Icarus。含未知位的控制或状态数据沿用逐项选择结果；任意状态位组合也保留原有优先次序。所有算术、选择及归并均使用普通 RTL。

## 验证

| 检查 | 参数或范围 | 结果 |
|---|---|---:|
| 坐标模块全部输出的组合证明 | 17、18、31、32、35、64 位，两种编译方式 | 12 项通过 |
| 坐标模块四态比较 | 完整和值与范围资格 | 360,000 次通过 |
| 完整状态选择模块的组合证明 | 1、5、9 位列计数，两种编译方式 | 6 项通过 |
| 完整状态选择模块四态比较 | 任意状态位、控制及状态数据 | 196,608 次通过 |
| 完整流式控制模块的组合证明 | 通用与 FPGA 编译方式 | 2 项通过 |
| 完整流式控制模块四态比较 | 全部二态组合、逐位未知值及随机四态 | 319,556 次通过 |
| 完整几何父模块的时序等价 | 直接及寄存描述符，两种编译方式 | 4 项通过 |
| 完整流式父模块的时序归纳 | 4、8、16 通道，直接及寄存描述符 | 5 项通过 |

组合证明不限制功能输入，状态选择证明使用标准 `case` 顺序语义。状态和流式控制的 Slang 通用方式显式使用 `-USYNTHESIS -UXILINX_FPGA`，FPGA 方式使用 `-DSYNTHESIS=1 -DXILINX_FPGA=1`，结果保存在 `compilation_validation.json`。完整流式证明比较公开输出及实际保存状态，从两侧相同的零初值开始进行归纳。映射后的完整 DMA 也通过 ABC 网络等价检查。完整结果与源码摘要保存在 `validation.json`。

## 完整 DMA 测量

参数为 `SIZE=16`、`BUS_WIDTH=64`、`WINDOW_LANES=8`、缓存行 128 字节、16 组两路缓存。参考和当前版本使用相同的其余前端及 DMA 输入，只有本目录对应的三个 RTL 文件不同。

| 项目 | 参考输入 | 当前 |
|---|---:|---:|
| 逻辑 LUT | 14,291 | 14,274 |
| 输入坐标到运行状态的最长组合单元数 | 11 | 10 |
| 配置寄存器到运行状态的最长组合单元数 | 12 | 13 |
| 完整 DMA 的最长组合单元数 | 12 | 13 |

当前配置路径从输入格式位出发，经过通道范围、推进后的有效范围和读取请求资格到达运行状态。该路径及完整连接记录保存在 `measurement.json`，可与完整 SoC 的后续映射一起检查。

映射采用 `physical-cost`、6667 ps 目标、300 ps 连线代价和最多 8 个输入的切割设置。结构级数描述组合连接数量，器件实现频率仍需布局布线时序分析。

## 重复执行

在工程根目录执行：

```sh
python test/frontend_state_selection/run_control.py --out build/frontend_state_control
python test/frontend_state_selection/run_stream_control.py --out build/frontend_stream_control
python test/frontend_arithmetic/check_coordinate_step.py --reference 32379597 --candidate rtl/npu/conv/conv_coordinate_step.sv --out build/frontend_coordinate
python test/frontend_arithmetic/check_decode_match.py --reference 32379597 --sources rtl/npu/conv/conv_im2col_geometry.sv --helpers rtl/npu/conv/conv_coordinate_step.sv --out build/frontend_geometry
python test/frontend_arithmetic/check_stream.py --candidate rtl/npu/conv/conv_im2col_stream_control.sv --out build/frontend_stream
```

`measure_paths.py` 接收完整 DMA 的 `mapped.json` 和 `pre_lut.il`，直接遍历坐标、配置寄存器到实际状态寄存器的连接，不增加分析用的 RTL 实例。
