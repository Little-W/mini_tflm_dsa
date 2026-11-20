# WS 量化参数写入共享

`vec_requant_full` 按 DMA 字的通道索引选择写入 bank，同一 bank 的全部 WS 通道共用一次写数据选择。每个通道继续保存原始乘数、原始移位量、预处理乘数和预处理移位量，共 103 位。

生产配置为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`。两个 bank 各使用一个 64 位乘数 `regfile` 和一个 39 位移位参数 `regfile`，深度均为 8。每个存储实例以常量地址并行读取全部通道，读写周期与原有寄存器数组相同。数据存储不增加复位或器件资源属性。

## 写入和读取行为

一个 DMA 拍中的连续字分别进入不同的 bank。写入位置由通道索引的低位决定，保留原有地址回绕行为。尾拍的有效字数、DMA 响应握手、WS/IS 模式及参数装载阶段共同决定各 bank 的写使能。

当 bank 数和通道数为二的幂，且 bank 数不超过通道数时，使用共享写数据结构。其他参数组合保留逐字更新的顺序，同一通道的重复写入由较后的有效字覆盖。乘数和移位参数分别写入，未写入的内容保持原值。全部通道始终并行读取。

## 状态与完整接口验证

`run_formal.py` 分别提取参考提交和候选源码中的实际 WS 写入代码，以全部存储状态作为比较输出。DMA 数据、地址、拍计数、装载阶段和响应使能均可任意变化。证明覆盖每个时钟边沿后的全部原始及预处理参数。

| BUS_WIDTH | VLEN | MAX_IA_REUSE | 比较的参数状态位 | 结果 |
|---:|---:|---:|---:|---|
| 32 | 16 | 32 | 1,648 | 通过 |
| 64 | 16 | 32 | 1,648 | 通过 |
| 128 | 16 | 32 | 1,648 | 通过 |
| 64 | 2 | 2 | 206 | 通过 |
| 32 | 1 | 2 | 103 | 通过 |
| 96 | 16 | 32 | 1,648 | 通过 |
| 64 | 3 | 2 | 309 | 通过 |
| 128 | 2 | 2 | 206 | 通过 |

完整 `vec_requant` 接口以官方 `LUT6_2` 和 `DSP48E1` 功能模型逐周期比较全部十八个公开输出，包括无效周期的数据。两个总线配置分别覆盖 256 个场景、528,662 个周期。

| 配置 | 向量数 | DMA 命令数 | DMA 返回拍数 |
|---|---:|---:|---:|
| BUS32 | 206,800 | 922 | 12,322 |
| BUS64 | 209,001 | 958 | 6,496 |

场景覆盖 per-tensor、per-channel、WS、IS、INT8、INT16、输入间隔、尾部通道、配置刷新和运行期间复位。

## 实际展开容量

`run_capacity.py` 使用 `config/npu_fpga.mk` 展开完整生产 NPU，分别使用参考量化源码和共享写入源码，其余输入源保持相同。容量工具将 WS 参数独立记录为 `requant_ws_parameters`。

| 容量 | 参考实现 | 共享写入实现 |
|---|---:|---:|
| IS 参数 | 52,736 bit | 52,736 bit |
| WS 参数 | 1,648 bit | 1,648 bit |
| 完整 NPU 顺序状态 | 798,201 bit | 798,201 bit |
| regfile 实例数 | 60 | 64 |

## 综合资源与组合路径

参考提交为 `369a3ab`。独立综合保留 `vec_requant` 的全部公共输出，使用相同的普通 Xilinx 映射流程。

| 资源 | 参考实现 | 共享写入实现 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 10,377 | 8,851 | −1,526 |
| 外部触发器 | 7,044 | 7,044 | 0 |
| DSP48E1 | 96 | 96 | 0 |
| CARRY4 | 423 | 423 | 0 |
| LUT RAM 标称位置数 | 1,120 | 1,120 | 0 |
| SRL 标称位置数 | 192 | 192 | 0 |
| RAMB18/RAMB36 | 0/0 | 0/0 | 0/0 |

参数写数据到寄存器 D 端的最长路径由 9 个单元降至 4 个单元。共享实现使用寄存器 CE 保存未选通的通道，写使能路径为 9 个单元。整个量化模块的最长寄存器间组合路径保持为 17 个单元。候选综合峰值进程树 RSS 为 506,621,952 字节，约 483.2 MiB。

以上路径统计使用实际相连的映射单元。器件内部延时、布线延时、物理 LUT 位置和 150 MHz 时序由完整 SoC 实现报告确定。

## 复现命令

```bash
python test/requant_parameter_write/run_formal.py --out build/requant_parameter_write/formal
python test/requant_pipeline/run_interface.py --out build/requant_parameter_write/interface --reference-rev 369a3ab --bus-width 32 64 --verilator verilator-modern --jobs 1 --xilinx
python test/requant_parameter_write/test_capacity.py
python test/requant_parameter_write/run_capacity.py --out build/requant_parameter_write/capacity_compare --verilator verilator-modern
python test/requant_parameter_write/prepare_measurement.py --out build/requant_parameter_write/inputs
python scripts/fpga/open_fpga_synth.py --source-root . --case-config build/requant_parameter_write/inputs/cases.json --cases reference bank_write --out build/requant_parameter_write/synthesis --lock-file build/synth-small.lock
python test/requant_parameter_write/measure_paths.py --synthesis build/requant_parameter_write/synthesis --out build/requant_parameter_write/paths.json
```

`measurement.json` 保存实际源文件摘要、形式比较、接口回归、容量展开、资源和路径统计。
