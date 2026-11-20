# 累加存储的串行读取共享

`vector_engine` 保留 `acc_buf` 的容量、全部写入来源和八路 PE 并行读取。
深度卷积量化、向量归约、平均池化、Softmax 共用一个异步串行读取选择器。

| 消费周期 | 读取地址 | 接收数据的位置 |
|---|---|---|
| `QUANT_STREAM` | `q_issue` | `q_accumulator` |
| `VECTOR_REDUCE` | `reduce_index` | 归约运算和最终结果写入 |
| Softmax 操作的其余周期 | `soft_exp_index` | 共享乘法器的 Softmax 操作数 |
| 其余周期 | `quant_index` | 平均池化的幅值、符号和舍入输入 |

选择器在原有寄存器采样边沿之前给出数据，未增加流水寄存器。
`serial_acc_read_index` 和 `serial_acc_read_data` 使用显式组合逻辑，
`softmax_i_exp_rdata` 保留 `u_softmax` 的输入边界信号。新增 RTL 不使用函数。

## 形式验证

```sh
python3 test/vector_acc_read/run.py \
  --out build/vector_acc_read_formal32 --bus-width 32
python3 test/vector_acc_read/run.py \
  --out build/vector_acc_read_formal64 --bus-width 64
```

验证分为三个相互连接的步骤。

1. 从当前完整 RTL 提取实际控制电路，保留 `state`、`c.op`、`load_kind`、
   `global_pool` 的寄存器及实际转移逻辑。其他数据寄存器以及与这些控制值、
   配置操作码、复位和接受条件无关的数据谓词允许取任意值。归纳证明检查：
   量化状态属于深度卷积，平均池化状态属于平均池化，归约状态不占用这两种
   运算及 Softmax 的读取用途。该步骤不限制外部输入序列。
2. 将修改前后完整向量引擎展开，通过相同公开 RTL 信号名称和位下标，
   为每个寄存状态位建立对应关系。在已经证明的控制条件下，证明两个
   完整 32 位标量乘法操作数相等。
3. 将这两个相等的操作数替换为同一组任意值，合并相同乘法表达式，并
   允许共用乘积取任意值。随后比较所有寄存器的下一状态和全部公开输出。
   寄存器的复位、写使能、保持路径与数据更新都参与比较。

乘法表达式的替换仅用于验证电路。生产 RTL 保留实际算术逻辑。
BUS32 验证 13,369 个寄存状态位，BUS64 验证 13,446 个寄存状态位；
两者均比较全部 35 个公开输出端口。源文件版本、SHA256 以及内存
使用统计保存于各输出目录的 `summary.json`。

## 完整向量回归

```sh
python3 test/vector_engine/run.py --out build/vector_acc_read_bus32 \
  --bus-width 32 --verilator verilator-modern --jobs 2 --xilinx --pes 8
python3 test/vector_engine/run.py --out build/vector_acc_read_bus64 \
  --bus-width 64 --verilator verilator-modern --jobs 2 --xilinx --pes 8
```

两种配置分别执行 592 项任务，使用实际 `DSP48E1` 功能模型和独立整数
参考运算。覆盖深度卷积、池化、归约、Add、Softmax、DMA 等待、地址边界、
错误恢复及计算写出重叠。每项任务的输出、周期和全部统计字段均与修改前
相同。

| 配置 | 任务数 | 检查的输出数 | 各任务周期总和 |
|---|---:|---:|---:|
| BUS32、TILE16、PE8 | 592 | 168,751 | 2,959,670 |
| BUS64、TILE16、PE8 | 592 | 168,636 | 2,933,721 |

## 独立综合

```sh
python3 test/vector_acc_read/prepare_measurement.py \
  --out build/vector_acc_read_measurement --bus-width 64
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/vector_acc_read_measurement/cases.json \
  --cases vector_reference vector_shared \
  --out build/vector_acc_read_measurement/synthesis
```

完整 `vector_engine` 在 BUS64、TILE16、PE8 下的独立综合结果如下。

| 指标 | 分别读取 | 共享串行读取 |
|---|---:|---:|
| 逻辑 LUT | 13,892 | 13,092 |
| 分布式存储 LUT 位置估计值 | 248 | 248 |
| 普通寄存器 | 6,104 | 6,104 |
| DSP | 16 | 16 |
| RAMB18 / RAMB36 | 0 / 0 | 0 / 0 |
| 最长组合路径的单元数 | 23 | 24 |

逻辑 LUT 减少 800。共享地址选择增加一层组合选择；实际器件的延迟和物理
LUT 位置数量由完整 SoC 的布局布线结果确认。`measurement.json` 保存源
文件、形式验证、完整回归和综合测量摘要。
