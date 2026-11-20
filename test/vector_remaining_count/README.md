# 向量剩余长度的并行计算

下一批有效通道数取 `length-vector_offset-active` 的三十二位回绕结果与 `TILE` 的较小值。实现复用分组前进判断中的低位偏移加法，只计算需要保存的低位差值。偏移加法的进位与低位减法的借位共同确定高位递增量，逐位进位关系用于检查高位差是否为零。

该结构保留全部三十二位长度和偏移编码，以及有效通道数的全部编码。寄存器、状态转移、复位、暂停和公开接口周期保持相同。所有计算均为组合逻辑。

## 验证

在仓库根目录运行：

```sh
python3 test/vector_remaining_count/run_formal.py --out build/vector_remaining/formal
python3 test/vector_acc_read/run.py --reference-rev 2f06471c --bus-width 64 --out build/vector_remaining/full_state
python3 test/vector_engine/run.py --bus-width 64 --pes 8 --jobs 1 --xilinx --out build/vector_remaining/bus64
python3 scripts/fpga/open_fpga_synth.py --cases vector_engine --out build/vector_remaining/synthesis
```

算术证明从实际 RTL 提取前进条件、下一偏移和下一批有效通道数，检查 `TILE=1、3、16、17、32、64、255`，没有添加输入范围假设。全部比较通过。

直接与附件提交 `2f06471c` 的完整状态比较覆盖 13,446 位寄存状态、35 个公开输出以及标量乘法器操作数，全部通过。BUS64 仿真使用官方 Xilinx 原语模型，完成 592 项任务和 169,361 个数值输出检查。每项任务的周期、读写和缓存统计与附件参照完全相同，总任务周期为 2,995,967。

## 完整向量综合

生产向量配置为 `TILE=16、PE_COUNT=8、BUS_WIDTH=64`。

| 项目 | 保留槽位译码的实现 | 共享剩余长度计算 |
| --- | ---: | ---: |
| 逻辑 LUT | 11,629 | 11,593 |
| 分布式 RAM LUT | 248 | 248 |
| 触发器 | 5,976 | 5,976 |
| DSP48E1 | 16 | 16 |
| 最长寄存器间组合单元数 | 15 | 15 |
| `win_req_ready` 至 `input_reserved` 组合单元数 | 1 | 1 |

完整路径图没有组合环或未识别单元。`measurement.json` 保存固定源码、实际连通路径、形式结果、数值统计以及工具摘要。完整 SoC 的物理 LUT 位置和 150 MHz 时钟由目标器件实现报告检查。
