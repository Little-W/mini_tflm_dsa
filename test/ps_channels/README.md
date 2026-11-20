# 固定部分和通道

完整的 INT32 部分和行包含 512 位，划分为四个 128 位通道。`ps_frame_store` 的固定通道配置以完整行号产生地址，四个数据段每周期并行读取或写入。`ia_ps_channel_ram` 将可分配给 IA 的物理块分成四段，每段接入一个部分和通道；其余部分和空间按通道连续存放。

## 地址和容量

设每块包含 $R$ 个 128 位字，当前分配给 IA 的块数为 $A$，每段包含 $Q=R/4$ 个字。

- IA 逻辑字地址 $a$ 对应物理块 $a\bmod A$ 和块内字号 $\lfloor a/A\rfloor$。配置切换不会改变物理字的位置。
- 部分和通道 $c$ 的行地址 $r$ 对应物理块 $A+\lfloor r/Q\rfloor$ 和块内字号 $cQ+(r\bmod Q)$。四个通道均可在同一周期访问。
- IA 支持按字节写入；同块多个 IA 请求按端口编号选择，并报告访问错误。同地址同时读取与有效写入会保留读取前的数据并阻止该次写入。
- 所有存储实例采用 `regfile`，采用一个同步读端口和一个写端口。复位只清除控制状态，存储类型由综合工具推断。

六块和七块配置支持分配一个或两个 IA 块，八块和九块配置还支持分配四个 IA 块。每个合法配置的 IA 与部分和地址集合覆盖全部物理字，两个集合没有重叠。

生产配置为七块、每块 8,192 字节，共 57,344 字节。固定布局包括一个 128×512 存储、四个 128×128 存储以及四个 128×640 存储，总容量为 458,752 bit。

## 独立综合

工具按 Xilinx 7 系列资源进行综合，两个实现使用相同参数和综合选项。

| 模块与资源 | 按存储块轮转 | 固定通道 |
|---|---:|---:|
| 共享存储逻辑 LUT | 3,828 | 2,003 |
| 共享存储触发器 | 21 | 13 |
| 共享存储 `RAMB36E1` | 14 | 26 |
| 共享存储最长寄存器间组合单元数 | 9 | 8 |
| 帧控制逻辑 LUT | 1,106 | 967 |
| 帧控制触发器 | 827 | 825 |
| 帧控制 DSP | 8 | 2 |
| 帧控制最长寄存器间组合单元数 | 15 | 12 |

帧重放队列的 4,096 bit 容量保持一致，两种实现都采用 344 个分布式 RAM LUT。上述数值为独立模块的综合结果；完整 SoC 的物理 LUT 和 150 MHz 时序需要对应网表的布局布线测量。

## 验证

12 种几何配置覆盖每块 2 / 4 / 8 KiB 与 6 / 7 / 8 / 9 个块。存储测试完成 312,764 个周期和 10,746,800 个字节检查，覆盖字节掩码、IA 与部分和并行访问、配置切换、复位以及访问错误。

帧测试将两种布局同时连接到实际存储模块，逐周期比较公共控制输出与重放数据，并使用独立期望值核对 INT32。共完成 8,696 条命令、2,030,912 次 INT32 比较、58,983 个并行读写周期和 282 次容量压力检查。六组形式比较覆盖 39,449 位状态与输出；固定通道配置的 RAM 地址编码另由地址覆盖和实际存储测试检查。

完整 NPU 使用官方 LUT 和 DSP 功能模型，保留 256 个脉动计算单元、8 路向量 PE，以及全部存储容量。38 项任务和 11,118 次 INT32 检查通过，任务测量结果与 `66618da` 一致，总计 134,077 个周期。输出合并、WS/IS 切换和恢复专项完成 15 项任务及 11,392 次 INT32 检查。容量与非法配置专项完成 21 项任务、173,642 次 INT32 检查和 585,078 个周期，所有任务测量结果与 `66618da` 一致。三组整机专项使用同一个固定仿真程序。

固定源码散列、仿真程序散列、资源和测试结果见 `docs/data/ps_channel_validation.json`。

## 运行方法

```sh
python3 test/ps_channels/run_memory.py --out build/ps_channel_memory_all
python3 test/ps_channels/run_store.py --out build/ps_channel_store_all
python3 test/ps_channels/run_structure.py --out build/ps_channel_structure
python3 test/ps_channels/run_control_formal.py --out build/ps_channel_control_formal
python3 test/ps_channels/run_npu_structure.py --out build/ps_channels_fpga_structure
python3 test/ps_channels/synthesis.py --out build/ps_channel_synth/fixed_memory --layout fixed
python3 test/ps_channels/synthesis.py --out build/ps_channel_synth/rotating_memory --layout rotating
python3 test/ps_channels/synthesis.py --out build/ps_channel_synth/fixed_store --kind store --layout fixed
python3 test/ps_channels/synthesis.py --out build/ps_channel_synth/rotating_store --kind store --layout rotating
python3 test/fpga_integration/run.py --out build/ps_channels_fpga_npu --verilator verilator-modern --jobs 2
python3 test/writeback_cyclic/run_npu.py --out build/ps_channels_fifo_npu --sim build/ps_channels_fpga_npu/npu/s16
python3 test/ps_capacity_limits/run_npu.py --out build/ps_channels_capacity_npu --verilator verilator-modern --bus-width 64 --sim build/ps_channels_fpga_npu/npu/s16 --suite-timeout 900
```
