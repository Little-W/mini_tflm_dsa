# 向量 PE 的寄存操作数与共用 DSP 算术

## 周期与数据通路

`registered_vector_pe` 接收 INT16 操作数和 INT32 累加值。`i_en` 有效的上升沿保存三个操作数，当前 `i_op` 选择寄存操作数的计算结果。操作数寄存器保持原有无复位行为。

`vector_engine` 在 `EXECUTE` 更新操作码；操作数的接收条件还包含 Hadamard 写出等待条件。两种使能分别保留。`EXECUTE_COMMIT` 的结果消费周期、所有状态转移和存储写入条件保持一致。

每个 PE 使用一个 DSP48E1。`AREG=1`、`BREG=1` 分别保存 `b`、`a`；`MREG=0`、`PREG=0` 保持既有计算周期。预加法输入选择寄存的 `b` 或常数一，使乘法、乘加、求和与极值比较共用算术单元。

| 操作码 | 运算 |
|---|---|
| 0 | `a*b+acc`，保留低 32 位 |
| 1 | `acc+sign_extend(a)`，保留低 32 位 |
| 2 | `max(acc, sign_extend(a))` |
| 3 | `min(acc, sign_extend(a))` |
| 4 | `a*b` |
| 5、6 | 零，符合向量实例关闭扩展乘法的设置 |
| 7 | `acc` |

极值比较使用四十八位 `acc-a` 的符号位，覆盖全部 INT32/INT16 输入范围。输入值与累加值另有寄存器供极值选择和操作码 7 使用。操作码可以在 `i_en=0` 时改变，数据保持原值。

`ASIC_SYNTHESIS` 选择通用 RTL；`XILINX_FPGA` 或 `SYNTHESIS` 选择 DSP 实现。原有 `vector_pe` 的接口及扩展乘法逻辑保持兼容。辅助模块位于同一个源文件，不需要新增工程源文件。

## 功能验证

参考提交为主分支可恢复的 `d9abf98`。源文件摘要、原语库摘要与结果保存在 `measurement.json`。

- 官方 DSP48E1 模型的实际输入寄存器状态通过归纳等价证明。证明覆盖 `i_en` 的任意变化及完整操作数范围。
- 在已证明的状态对应关系上，对八种当前操作码分别执行全输入 SAT，比较全部 32 位结果。形式证明没有约束数据值或输入使能。
- 从两份真实 `vector_engine` 源码提取被修改的操作数选择、寄存与实例连接，比较全部操作数状态、独立操作码和结果。`TILE/PE_COUNT` 为 `1/1`、`3/2`、`16/8`、`32/16`；其余源代码与原有 PE 实现逐项检查一致。
- 官方 DSP 模型、通用 RTL 和独立 C++ 整数模型比较 261,583 个周期、523,165 次采样，其中 73,002 个周期保持操作数。覆盖有符号极值、低 32 位溢出、八种操作码和暂停时操作码变化。
- BUS32、BUS64 各完成 592 项完整向量任务，分别检查 168,491 和 169,361 个结果。各任务周期数与全部 DMA 统计和已保存的同参数回归结果逐项一致。
- 生产 NPU 结构展开的通用顺序状态为 798,185 bit，`vector_buffers` 为 9,696 bit，256 个阵列单元和 8 个向量 PE 保持一致。

| 接口 | 任务数 | 数值输出数 | 总周期数 | Add 任务数 | Softmax 任务数 |
|---|---:|---:|---:|---:|---:|
| BUS32 | 592 | 168,491 | 2,998,186 | 143 | 273 |
| BUS64 | 592 | 169,361 | 2,995,967 | 143 | 273 |

完整向量回归使用官方 FPGA 原语，包含生产 DMA、停顿与连续运算。完整 NPU 的集成验证由固定整合版本执行。

## 综合与连接路径

器件配置为 `xc7a200tfbg484-3`。完整向量参数为 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64`。两个实现使用相同的综合流程与参数，表中 LUT 为布局前逻辑原语数。

| 测量对象 | 指标 | 参考实现 | 当前实现 | 变化 |
|---|---|---:|---:|---:|
| 8 个 PE | 逻辑 LUT | 1,419 | 515 | −904 |
| 8 个 PE | FF | 384 | 384 | 0 |
| 8 个 PE | CARRY4 | 88 | 0 | −88 |
| 8 个 PE | DSP48E1 | 8 | 8 | 0 |
| 完整向量 | 逻辑 LUT | 12,785 | 11,743 | −1,042 |
| 完整向量 | FF | 6,104 | 5,976 | −128 |
| 完整向量 | CARRY4 | 872 | 760 | −112 |
| 完整向量 | DSP48E1 | 16 | 16 | 0 |
| 完整向量 | 分布式存储 LUT | 248 | 248 | 0 |
| 完整向量 | 最长寄存器间组合单元数 | 18 | 18 | 0 |

完整向量综合峰值内存为参考实现 515.33 MiB、当前实现 495.94 MiB。该修改不增加 DSP 数量。BRAM 与 SRL 均为零，存储容量保持一致。

实际连接图中的 PE 操作数寄存器到消费寄存器最长路径由 14 个组合单元变为 6 个。当前进入 DSP 输入寄存器的最长路径为 11 个，DSP 内部寄存后的算术输出到消费寄存器最长为 5 个。DSP 内部算术延迟和布线延迟需要器件时序分析；这里的组合单元数不换算为工作频率。

当前完整向量模块尚有四条超过 15 个组合单元的路径：

| 起点 | 终点 | 组合单元数 | 运算 |
|---|---|---:|---|
| `c.image.dilation_h` | `state` | 18 | 下一行坐标相加、范围比较和状态选择 |
| `c.output_offset` | `result_buf` | 18 | 量化偏移相加和饱和选择 |
| `state` | `reduce_acc` | 17 | 串行读取选择和归约加法 |
| `u_rounding.g_middle_register.remaining_amount` | `add_rounded` | 16 | 后半段移位和舍入递增 |

本目录记录模块综合结果；完整 SoC 的物理 LUT 数与 150 MHz 时序由整合后的布局、布线结果给出。

## 复现命令

在已加载项目工具环境的仓库根目录运行：

```bash
python test/vector_pe_dsp/run_formal.py --out build/vector_pe_dsp/formal
python test/vector_pe_dsp/run_engine_formal.py --out build/vector_pe_dsp/engine_formal
python test/vector_pe_dsp/run.py --out build/vector_pe_dsp/interface --verilator verilator-modern
python test/vector_pe_dsp/run_capacity.py --out build/vector_pe_dsp/capacity --verilator verilator-modern
python test/vector_engine/run.py --out build/vector_pe_dsp/vector_bus32 --bus-width 32 --verilator verilator-modern --jobs 1 --xilinx
python test/vector_engine/run.py --out build/vector_pe_dsp/vector_bus64 --bus-width 64 --verilator verilator-modern --jobs 1 --xilinx
python test/vector_pe_dsp/prepare_measurement.py --out build/vector_pe_dsp/inputs
python scripts/fpga/open_fpga_synth.py --case-config build/vector_pe_dsp/inputs/cases.json --cases reference registered vector_reference vector_registered --out build/vector_pe_dsp/synthesis
python test/vector_pe_dsp/measure_paths.py --synthesis build/vector_pe_dsp/synthesis --out build/vector_pe_dsp/paths.json
```

多任务运行时，为综合命令添加项目共同的 `--lock-file`。完整向量综合与 C++ 编译顺序执行。
