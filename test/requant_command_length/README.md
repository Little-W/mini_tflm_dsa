# 量化参数 DMA 长度计算

`vec_requant_full` 使用一个 33 位减法器计算剩余参数字数。最高位保留无符号减法的借位，低 32 位保留完整差值。装载偏移超过总数时返回零，其余情况将字数饱和到 `VLEN`。

饱和后的字数使用 `$clog2(VLEN + 1)` 位保存。对于非零字数 `n`，每拍读取 `B = BUS_WIDTH / 32` 个参数字，突发长度字段由 `(n - 1) / B` 计算。字数为零时该字段为零。末拍编号的窄减法与借位、上限判断并行，范围判断完成后选择对应结果。命令寄存器、响应计数和量化流水的采样边沿均保持原有行为。

## 功能验证

参考提交为主分支中的 `1d7c6b7`。`run_formal.py` 从两份实际源码提取长度表达式，将装载总数与偏移设置为两个独立的 32 位自由输入，比较全部 32 位字数和 8 位突发长度。12 组参数全部通过 Yosys SAT 证明，覆盖 `BUS_WIDTH = 32、64、96、128`，以及 `VLEN = 1、3、16、32、256、1024` 的对应组合。输入覆盖全部零值、最大值、相等值和无符号下溢情况。脚本同时核对被证明表达式以外的源码保持相同，状态寄存器及其采样条件保持一致。

完整接口回归启用实际 `SYNTHESIS` 分支，并使用 Xilinx 官方 `LUT6_2`、`DSP48E1` 功能模型。两份设计逐周期比较全部 18 个公开输出，包括无效周期的数据值。回归覆盖参数装载、DMA 暂停、尾部响应、配置切换、复位和错误恢复。

| 总线宽度 | 场景 | 比较周期 | 向量组数 | DMA 命令 | DMA 响应拍 |
|---|---:|---:|---:|---:|---:|
| 32 | 256 | 528,662 | 206,800 | 922 | 12,322 |
| 64 | 256 | 528,662 | 209,001 | 958 | 6,496 |

## 综合与组合路径

生产配置为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`，保留全部公开输出。采用相同 Xilinx 七系列综合流程与原语库。

| 项目 | 参考设计 | 当前设计 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 8,039 | 8,018 | −21 |
| 触发器 | 7,044 | 7,040 | −4 |
| CARRY4 | 423 | 419 | −4 |
| DSP48E1 | 96 | 96 | 0 |
| 分布式 RAM LUT | 1,120 | 1,120 | 0 |
| SRL LUT | 192 | 192 | 0 |
| RAMB18 / RAMB36 | 0 / 0 | 0 / 0 | 0 |
| 命令突发长度寄存器的最长组合路径 | 17 | 12 | −5 |
| 命令预期字数寄存器的最长组合路径 | 13 | 12 | −1 |
| 装载偏移寄存器的最长组合路径 | 13 | 13 | 0 |
| 全模块最长组合路径 | 17 | 15 | −2 |

路径长度统计真实网表中两个寄存器之间经过的组合单元数量。当前最长路径由 `m_r` 经过尾部通道数计算到达 `lane_en_s0`。150 MHz 的频率检查由完整 SoC 布局布线后的时序分析完成。

本次复用 `1d7c6b7` 的参考综合网表；输入源码、全部依赖、参数、原语模型和去除输出目录差异后的映射命令均已核对一致。`measurement.json` 保存源码摘要、综合统计、形式证明和完整接口结果。

## 复现

从仓库根目录运行，环境中需提供带 slang 插件的 Yosys Python 模块和 Verilator。

```bash
python test/requant_command_length/run_formal.py \
  --out build/requant_command_length/formal
python test/requant_pipeline/run_interface.py \
  --out build/requant_command_length/interface \
  --reference-rev 1d7c6b7 --bus-width 32 64 \
  --verilator verilator-modern --jobs 1 --xilinx
python test/requant_command_length/prepare_measurement.py \
  --out build/requant_command_length/inputs
python scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_command_length/inputs/cases.json \
  --cases reference command_length \
  --out build/requant_command_length/synthesis
python test/requant_command_length/measure_paths.py \
  --reference build/requant_command_length/synthesis/reference \
  --candidate build/requant_command_length/synthesis/command_length \
  --out build/requant_command_length/paths.json
```
