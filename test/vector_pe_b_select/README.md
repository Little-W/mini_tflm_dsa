# 向量 PE 的 B 操作数选择

无效通道的 A 操作数和累加值保持为零，B 操作数直接选择权重或右操作数。实际 `registered_vector_pe` 的八种操作在 A 和累加值均为零时都输出零，因此 B 输入可以保留当前数据。使能、操作码、A 和累加值的寄存周期保持相同。

## 形式检查

`run_formal.py` 从实际 `vector_engine.sv` 提取操作数选择、操作码寄存和 PE 实例，并检查其他 RTL 内容保持相同。检查使用实际 `registered_vector_pe` 和官方 `DSP48E1` 功能模型。

状态比较覆盖 `TILE/PE_COUNT` 为 `1/1`、`3/2`、`16/8` 和 `32/16` 的四种配置，比较 A、累加值、操作码和有效 B 状态，同时证明无效通道的 A 与累加值为零。有效性观察寄存器仅用于形式模型，初始为有效，随后在实际捕获边沿保存实际通道使能。生产 RTL 不增加该寄存器。

算术比较覆盖八种操作编码与两种有效性状态，共 16 项。全部计算来自实际 DSP 功能模型，输入数值和暂停序列不附加限制。四项状态检查和十六项算术检查全部通过。

## 完整模块结果

配置为 `TILE=16、PE_COUNT=8、BUS_WIDTH=64`。五 DSP 标量乘法器用于前三行，最后一行采用提交 `a237915c` 的四 DSP 实现。

| 实现 | 逻辑 LUT | RAM LUT | 触发器 | DSP48E1 | 最长寄存器间组合单元数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 剩余长度共享，`fc320ec2` | 11,593 | 248 | 5,976 | 16 | 15 |
| 增加池化完成预计算，`fa46e6b0` | 11,641 | 248 | 5,976 | 16 | 15 |
| 在 `fc320ec2` 上简化 PE 的 B 选择 | 11,535 | 248 | 5,976 | 16 | 15 |
| 池化预计算、PE 的 B 选择和四 DSP 标量乘法器 | 11,461 | 248 | 5,994 | 15 | 15 |

组合版本的 `rd_valid[0]` 至实际向量寄存器最长为 5 个组合单元；`win_req_ready` 至四个 `input_reserved` 寄存器分别为 1 个组合单元。资源统计保留全部输入存储容量和生产配置。物理 LUT 位置与 150 MHz 布局布线时序由整机实现结果提供。

组合版本的 64 位总线数值测试通过 592 项任务，共比较 169,361 个输出。每项任务的周期数、DMA 统计和重叠统计与参考结果一致，总计 2,995,967 个周期。测试采用实际 Xilinx 原语功能模型。`measurement.json` 保存源码摘要、模型摘要、形式比较、数值比较和完整路径结果。

## 运行方法

```sh
python3 test/vector_pe_b_select/run_formal.py --out build/vector_pool_pe_four_dsp/pe_formal
python3 test/vector_engine/run.py --bus-width 64 --pes 8 --jobs 1 --xilinx --out build/vector_pool_pe_four_dsp/bus64
python3 scripts/fpga/open_fpga_synth.py --cases vector_engine --out build/vector_pool_pe_four_dsp/synthesis
python3 test/vector_pool_receive/measure_boundary.py \
  --netlist build/vector_pool_pe_four_dsp/synthesis/vector_engine/mapped.json \
  --pre-lut build/vector_pool_pe_four_dsp/synthesis/vector_engine/pre_lut.il \
  --out build/vector_pool_pe_four_dsp/pool_boundary.json
python3 test/vector_reservation/measure_boundary.py \
  --netlist build/vector_pool_pe_four_dsp/synthesis/vector_engine/mapped.json \
  --pre-lut build/vector_pool_pe_four_dsp/synthesis/vector_engine/pre_lut.il \
  --out build/vector_pool_pe_four_dsp/reservation_boundary.json
```
