# 执行偏置地址计算

`npu_bias_execution_address` 接收偏置张量的字节基址和当前输出通道编号，计算 `base + (channel << 2)` 的低 32 位。模块使用普通加法表达式和已有的 `parallel_prefix_add`，并行形成高、低位和值及进位，不增加寄存器或执行周期。输入的扩展宽度由基址参数与 32 位通道编号共同决定。

模块保留包含 X/Z 的输入在完整地址表达式中的传播方式。`npu_matrix_engine` 使用该地址结果执行帧偏置选择，端口连接和宽度参数由验证脚本检查。

## 功能验证

`run.py` 对基址宽度 1、8、16、19、29、32、40、64 分别运行通用配置和 FPGA 配置，共 16 项无输入限制的组合等价证明。四态比较共完成 250,176 次，覆盖随机输入、逐位 X/Z、完整未知输入，以及通道左移后被移出的位段，全部通过。具体参数、源文件摘要和运行记录摘要见 [validation.json](validation.json)。

## 局部组合路径

测量在相同的寄存器边界内包含执行模式选择、偏置字节地址计算和帧资格选择。两份设计使用相同参数及物理面积代价映射。

| 项目 | 直接地址表达式 | 并行地址计算 |
| --- | ---: | ---: |
| 逻辑 LUT | 104 | 94 |
| 触发器 | 129 | 129 |
| 综合推断的 DSP | 0 | 1 |
| CARRY4 | 8 | 0 |
| 最长寄存器间组合路径 | 11 | 6 |

RTL 中没有 FPGA 运算原语实例。综合工具依据算术表达式推断运算资源。完整资源、映射验证及路径数据见 [measurement.json](measurement.json)。该表描述上述局部寄存器范围；完整 SoC 的资源和连接路径由 SoC 综合单独测量。

## 复现命令

在仓库根目录执行：

```bash
python3 test/matrix_bias_address/run.py --out build/matrix_bias_address/validation
python3 test/matrix_bias_address/measure.py --out build/matrix_bias_address/measurement
```
