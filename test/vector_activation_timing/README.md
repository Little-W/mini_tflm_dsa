# 向量激活限幅与边界比较

本检查覆盖 `vector_activation_clamp`、`vector_round_shift` 和 `vector_engine_control` 的完整公开输出。

激活限幅对各比较操作数扩展一个符号位，使用普通窄位差值的符号位形成大小关系。各结果保留完整输入范围、零点偏移的补码回绕、激活下限优先级和现有配置寄存周期。

舍入模块为每个字节独立归并较低字节与保护位，使字节进位保持平衡的组合层次。位置边界比较使用普通 RTL 比较模块；输入含未知位时，寄存器仍保存完整关系表达式的四态结果。

## 功能检查

```sh
python test/vector_activation_timing/run_activation.py --out build/vector_activation_timing/activation
python test/vector_activation_timing/run_timing.py --out build/vector_activation_timing/timing
```

| 检查对象 | 完整模块形式等价 | 四态结果比较 |
| --- | ---: | ---: |
| 四类激活限幅 | 4 项 | 2,097,152 次 |
| 舍入及全部输入、中间寄存配置 | 16 项 | 4,194,304 次 |
| 生产参数的向量控制器及位置比较 | 4 项 | 1,048,576 次 |

所有形式检查使用自由外部输入，比较全部公开输出。检查覆盖普通 RTL、`SYNTHESIS`、`XILINX_FPGA` 及两种宏同时定义的情况。四态检查包含未知数值位、未知移位量、符号端点、输出偏移、无序边界及寄存边沿前后的结果。

现有 `vector_round_pipeline` 检查另外通过 8 项完整时序等价，以及两个实现配置各 52,352 个四态输入周期；`vector_arithmetic_depth` 检查通过 52,352 个四态输入周期。相关入口统一解析所需的 RTL 依赖。

## 完整向量引擎测量

```sh
python test/vector_activation_timing/measure.py --out build/vector_activation_timing/measurement
```

测量使用 16 通道、8 个 PE、64 位总线、8 路窗口返回、共享存储和本地量化。参考实现和当前实现使用相同的依赖源码及映射设置：组合延迟目标 6667 ps、连线延迟参数 300 ps、LUT 输入上限 8。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 10,140 | 9,852 |
| LUTRAM 占用的 LUT | 176 | 176 |
| 包含存储的名义 LUT | 10,316 | 10,028 |
| 寄存器 | 6,307 | 6,307 |
| DSP | 26 | 39 |
| RAMB18 | 9 | 9 |
| 最长寄存器间组合级数 | 11 | 10 |

该资源比较包含 `vector_narrow_compare` 的池化与 PE 比较优化。对应的中间版本为 9,953 个逻辑 LUT，本组激活限幅及边界比较继续减少 101 个逻辑 LUT。全部通道、PE、存储容量及事务周期保持相同。

`measurement.json` 保存完整模块指标、路径、生产配置和源码 SHA-256。整机资源及实际连接后的组合级数由完整 SoC 报告提供。
