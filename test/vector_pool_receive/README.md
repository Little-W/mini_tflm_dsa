# 池化响应的完成条件

每拍接收数量由已保存的行剩余长度计算。接收计数和写入通道采用相同的数量，并由实际响应有效信号控制更新。完成检查提前计算两种情形：当前计数已经等于目标，或者当前计数加本拍数量等于目标。第二种情形使用 `add_equal`，保持原有计数位宽和模运算。最终由 `rd_valid[0]` 选择本拍完成条件。

该结构保持所有寄存器的更新周期、总线接口和输入存储容量。响应有效信号到完成检查的路径只经过条件选择，计数加法提前计算。

## 检查结果

生产向量配置为 `TILE=16、PE_COUNT=8、BUS_WIDTH=64`。

| 项目 | `fc320ec2` | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 11,593 | 11,641 |
| 分布式 RAM LUT | 248 | 248 |
| 触发器 | 5,976 | 5,976 |
| DSP48E1 | 16 | 16 |
| 最长寄存器间组合单元数 | 15 | 15 |
| `rd_valid[0]` 至向量寄存器的最长组合单元数 | 10 | 5 |

对附件版本 `2f06471c` 的完整状态形式比较通过。64 位总线检查 13,446 位寄存状态和 35 个公开输出，32 位总线检查 13,369 位寄存状态和相同输出。控制阶段条件由实际控制逻辑归纳证明，标量乘法器操作数单独比较。

64 位总线数值测试通过 592 项任务，比较 169,361 个输出。每项任务的周期数、DMA 统计和各项重叠统计均与参考结果相同，总计 2,995,967 个周期。测试采用实际 Xilinx DSP 功能模型。

`measurement.json` 保存源码摘要、资源统计、连通路径、完整状态比较和数值比较。输入边界分析只为已有输入添加分析起点，终点采用综合网表中真实寄存器的数据和控制引脚。`rd_valid` 在 RTL 中为索引从 0 开始的非压缩数组；脚本将 RTL 索引换算为 Slang 展平后的端口位序。

## 运行方法

```sh
python3 test/vector_acc_read/run.py --reference-rev 2f06471c --bus-width 64 --out build/vector_pool_receive/full_state
python3 test/vector_acc_read/run.py --reference-rev 2f06471c --bus-width 32 --out build/vector_pool_receive/full_state32
python3 test/vector_engine/run.py --bus-width 64 --pes 8 --jobs 1 --xilinx --out build/vector_pool_receive/bus64
python3 scripts/fpga/open_fpga_synth.py --cases vector_engine --out build/vector_pool_receive/synthesis
python3 test/vector_pool_receive/measure_boundary.py \
  --netlist build/vector_pool_receive/synthesis/vector_engine/mapped.json \
  --pre-lut build/vector_pool_receive/synthesis/vector_engine/pre_lut.il \
  --out build/vector_pool_receive/boundary.json
```
