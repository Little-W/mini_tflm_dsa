# 量化参数公共读取选择

`vec_requant_full` 将原始乘数、原始移位量、预处理乘数和预处理移位量组合为 103 位参数字。IS 与 per-tensor 参数在公共位置选择；每个通道随后在公共参数与自己的 WS 参数之间选择。

| cfg_per_channel_eff | is_mode_r | 读取来源 |
|---:|---:|---|
| 0 | 0 或 1 | per-tensor 参数 |
| 1 | 0 | 当前通道的 WS 参数 |
| 1 | 1 | 当前输入行的 IS 参数 |

通道选择条件为 `cfg_per_channel_eff && !is_mode_r`。这组表达式保留模式输入在当前周期的作用，任意模式组合均有确定的数据来源。完整参数字复用已有的 `requant_shift_mux`，将两个相邻位的二选一逻辑放入 `LUT6_2` 的两个输出；最后一个数据位单独选择。通用实现继续使用普通二选一表达式。

本次修改只涉及组合选择，所有存储容量、时钟使能、寄存阶段和公开输出周期保持相同。

## 形式与接口验证

`run_formal.py` 提取参考提交和候选源码中的实际公共选择及通道选择代码。全部参数值、两个模式位和输入行地址均可自由变化。BUS32、BUS64、BUS96、BUS128 分别验证通用实现和官方 `LUT6_2` 模型，共八组；每组比较 16 个通道的全部 1,648 位参数，全部通过。

完整接口比较使用官方 `LUT6_2` 和 `DSP48E1` 功能模型，参考提交为主分支中的 `e644187`。全部十八个公开输出逐周期比较，包括无效周期的数据。

| 总线 | 场景 | 周期 | 输入向量 | DMA 命令 | DMA 返回拍 |
|---|---:|---:|---:|---:|---:|
| BUS32 | 256 | 528,662 | 206,800 | 922 | 12,322 |
| BUS64 | 256 | 528,662 | 209,001 | 958 | 6,496 |

测试覆盖 per-tensor、per-channel、WS、IS、INT8、INT16、输入间隔、尾部通道、配置刷新和运行期间复位。

## 综合资源与组合路径

综合顶层为 `vec_requant`，保留全部公开输出，参数为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`。参考结果与当前参考提交的全部源文件摘要、参数和映射命令已逐项核对相同。

| 资源 | 参考实现 | 公共读取实现 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 8,851 | 8,039 | −812 |
| 外部触发器 | 7,044 | 7,044 | 0 |
| DSP48E1 | 96 | 96 | 0 |
| CARRY4 | 423 | 423 | 0 |
| LUT RAM 标称位置数 | 1,120 | 1,120 | 0 |
| SRL 标称位置数 | 192 | 192 | 0 |
| RAMB18/RAMB36 | 0/0 | 0/0 | 0/0 |

参数至乘法 DSP 输入寄存器和移位量寄存器的最长组合路径均保持为 6 个单元，模块最长寄存器间路径保持为 17 个单元。候选综合峰值进程树 RSS 为 491,405,312 字节，约 468.6 MiB。

上述路径统计实际相连的映射单元。物理 LUT 位置、器件内部延时、布线延时和 150 MHz 结果由完整 SoC 实现报告确定。

## 复现命令

```bash
python test/requant_parameter_read/run_formal.py --out build/requant_parameter_read/formal
python test/requant_pipeline/run_interface.py --out build/requant_parameter_read/interface --reference-rev e644187 --bus-width 32 64 --verilator verilator-modern --jobs 1 --xilinx
python test/requant_parameter_read/prepare_measurement.py --out build/requant_parameter_read/inputs
python scripts/fpga/open_fpga_synth.py --source-root . --case-config build/requant_parameter_read/inputs/cases.json --cases reference shared_read --out build/requant_parameter_read/synthesis --lock-file build/synth-small.lock
python test/requant_parameter_read/measure_paths.py --reference build/requant_parameter_read/synthesis/reference --candidate build/requant_parameter_read/synthesis/shared_read --out build/requant_parameter_read/paths.json
```

`measurement.json` 保存源文件摘要、组合证明、完整接口比较、参考结果检查、资源和路径统计。
