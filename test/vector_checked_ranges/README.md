# 向量读取范围复用

`vector_config_check` 在已有的检查状态中保存四个 DMA 读取槽位的末地址。
`vector_engine` 将这些寄存值直接连接到读取保护器，在 `CONFIGURE` 状态提供完整的起止地址。
所有外部接口、配置检查周期、向量存储容量和 PE 数量保持不变。

## RTL 结构

范围检查仍按输出、输入、第二输入或权重、偏置、乘数、移位参数的顺序执行。
`RANGE_SELECT` 保存原始范围，同时计算低八位和值及进位；`RANGE_ADD` 使用该进位计算高二十五位。
完整的三十三位末地址、六十四位长度高位、零长度、回绕及输出重叠检查均保留。

`RANGE_COMPARE` 按下表将末地址写入最终读取槽位。

| 配置类型 | 槽位 0 | 槽位 1 | 槽位 2 | 槽位 3 |
|---|---|---|---|---|
| 全局池化输入范围 | 输入 | 零 | 零 | 零 |
| Depthwise | 权重 | 已启用的偏置 | 乘数 | 移位参数 |
| 二元向量及 Softmax | 输入 | 第二输入或查表范围 | 零 | 零 |
| 其他非空间向量操作 | 输入 | 零 | 零 | 零 |
| 其他空间池化 | 零 | 零 | 零 | 零 |

全局池化输入范围具有最高选择优先级。偏置地址为零时不启用偏置槽位。
复位、新检查启动和错误完成在时钟边沿清空四个寄存值。
引擎仅在当前配置检查成功后进入 `CONFIGURE`，背压期间保存值保持稳定。
新增的控制状态为四个三十三位末地址以及九位部分和值及进位。

## 验证方法

- `run_checker.py` 对原检查器的全部公开输出及二十个状态信号进行逐周期等价证明。
  三组 `TILE` 参数为 8、16、32，配置、启动和后续复位输入均不受约束。
- `run_control.py` 从实际引擎和检查器生成形式模型，保留配置、状态机、范围检查与保存寄存器。
  无关数据状态扩展为任意值，复位前的数据寄存器初值保持任意。
  对 32 位及 64 位总线配置进行无界归纳，检查范围所属配置、长度高位、槽位优先级、未启用槽位零值和清除行为。
  `CONFIGURE` 阶段的四组起止地址与提交 `2297cb12` 中的实际表达式逐位比较。
- `test/vector_engine/run.py` 使用实际向量引擎和生产 DMA，按照独立整数参考检查数值、配置错误、存储错误和恢复行为。
  配置为 16 个通道、8 个向量 PE、64 位总线，并启用官方 Xilinx 功能模型。
  全部 592 项任务和 168,601 个输出通过，包括 143 项 Add 任务及 273 项 Softmax 任务。
- `measure.py` 在同一配置下测量完整向量引擎与实际 `conv_axi_read_guard`。
  算术采用普通 RTL 推断，LUT1 至 LUT6 的 ABC9 面积权重均为 1。

## 普通 RTL 测量

| 项目 | 提交 `2297cb12` | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 10,137 | 9,951 |
| 分布式 RAM LUT | 56 | 56 |
| 触发器 | 6,451 | 6,596 |
| CARRY4 | 721 | 685 |
| DSP48E1 | 17 | 17 |
| RAMB18E1 | 1 | 1 |
| RAMB36E1 | 2 | 2 |
| 范围准备、保存和读取保护器端点的最大组合级数 | 14 | 9 |
| 完整模块的最大组合级数 | 14 | 14 |

范围相关路径减少五级，逻辑 LUT 减少 186。
完整模块仍有十四级路径，其端点和逐级组成保存在 `measurement.json`。
这里记录的是本地逻辑映射结果，Vivado 布局时序由完整 SoC 测量提供。

## 复现

在仓库根目录运行以下命令。Python 环境需要安装包含 Slang 前端和 ABC9 的 Pyosys，
并能够调用现代 Verilator、GCC 和 Make。

```sh
python test/vector_checked_ranges/run_checker.py --out build/vector_ranges/checker
python test/vector_checked_ranges/run_control.py --out build/vector_ranges/control32 --bus-width 32
python test/vector_checked_ranges/run_control.py --out build/vector_ranges/control64 --bus-width 64
python test/vector_checked_ranges/measure.py --out build/vector_ranges/mapping
python test/vector_engine/run.py --out build/vector_ranges/numeric \
  --verilator verilator-modern --jobs 1 --tile 16 --pes 8 --bus-width 64 --xilinx
```

形式检查、映射和数值测试的源码 SHA256 与结果保存在 `measurement.json`。
