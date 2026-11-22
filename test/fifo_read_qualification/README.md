# INT8 FIFO 读取资格与字节掩码

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`vec_s8_to_fifo_full` 采用分层选择读取银行有效位。每层选择至多四个输入，32 个银行经过三层组合选择。银行有效位与行数非零条件分别计算，在读取请求生成处合并。银行数量较小或使用非二次幂配置时，保留直接索引的参数化实现。

输出掩码逐字节比较剩余有效列数。剩余列数小于零时没有有效字节，超过总线宽度时所有字节有效。计数减法保持完整的有符号整数表达式，掩码生成覆盖空拍、部分尾拍、完整拍、转置和合并输出。

该结构保持寄存器数量、数据存储组织、请求时刻与响应时刻。存储器继续使用普通数组和通用存储模块推断。

## 验证范围

`run_formal.py` 比较完整 FIFO 的所有公开输出、数据存储地址、写数据、读写使能、有效银行计数和共同寄存状态。数据 RAM 的读数据作为双方共有的任意输入，RAM 实现源码保持一致。第一个周期施加复位，其余输入和后续复位均不受限制。两份完整时序逻辑参与归纳证明。

验证包括两种容量阈值配置，各覆盖 10 组参数：银行数量为 1、2、3、8、16、32、64，向量长度为 8 或 16，包含 32 位和 64 位总线以及两种数据存储布局。全部组合均通过一步时序归纳。

`run_four_state.py` 从实际 RTL 提取计数存储、银行有效位过程及读取资格表达式，检查未知复位、未知地址、未知计数、空银行和同周期写入与释放。9 组参数共执行 24,000 个周期及 1,080,000 项比较。

`run_mask.py` 从实际 RTL 提取完整字节掩码表达式。12 组参数通过全部二值输入的组合证明，并完成 786,432 项严格四态比较。

`run_cycle.py` 使用输出写回测试中的独立数值计算、背压稳定性断言及逐周期参考比较。32 位和 64 位总线各通过 81 项测试、12,392 个字节检查；逐周期比较分别覆盖 7,196 和 4,522 个周期，周期差为零。

## 模块资源与路径

测量参数为 `VLEN=16`、`BANKS=32`、`BUS_WIDTH=64`，启用转置、循环存储和预存容量阈值。工具使用相同的公共 RTL、器件系列及综合设置。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,149 | 1,126 |
| 名义 LUT，含分布式存储 | 1,209 | 1,186 |
| 触发器 | 165 | 165 |
| DSP | 0 | 0 |
| RAMB18 | 8 | 8 |
| 最长寄存器间组合级数 | 10 | 10 |
| `read_bank` 至 RAM 地址 | 8 | 7 |
| `read_bank` 至 `last_beat_idx_q` | 9 | 8 |
| `read_bank` 至 `active_read_count_q` | 7 | 5 |

统计使用完整连接图。此表描述独立 FIFO 模块；完整 SoC 的资源、跨模块路径和目标器件时序由整机综合及实现报告给出。

## 运行方法

在仓库根目录执行：

```bash
python test/fifo_read_qualification/run_formal.py --out /tmp/fifo_read_formal
python test/fifo_read_qualification/run_formal.py --generic --precomputed-watermark 0 --out /tmp/fifo_read_generic_formal
python test/fifo_read_qualification/run_four_state.py --out /tmp/fifo_read_four_state
python test/fifo_read_qualification/run_mask.py --out /tmp/fifo_read_mask
python test/fifo_read_qualification/run_cycle.py --bus-width 32 --out /tmp/fifo_read_bus32
python test/fifo_read_qualification/run_cycle.py --bus-width 64 --out /tmp/fifo_read_bus64
python test/fifo_read_qualification/prepare_measurement.py --out /tmp/fifo_read_measure
python scripts/fpga/open_fpga_synth.py --source-root /tmp/fifo_read_measure/source --case-config /tmp/fifo_read_measure/cases.json --cases reference current --out /tmp/fifo_read_measure/results
```

默认参考提交为 `cedf4ed33661a53c8194eca1d484cdc2279d7549`。所有测试均支持独立候选源码目录；源码、测试结果、日志及可执行文件的 SHA-256 记录见 `validation.json`。
