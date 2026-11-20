# 量化尾部通道和行数计算

`vec_requant_full` 的块起点由块坐标左移得到。`VLEN` 为二的幂次且能由 `REG_WIDTH` 位表示时，尺寸高位与块编号的比较确定当前块是否完整、处于尾部或已经结束。尾部计数直接取尺寸的低位，其余参数配置使用完整的减法和饱和表达式。

计算保留所有 32 位尺寸和块坐标的原有含义，块起点按现有 32 位结果截断。配置寄存器、通道使能、输入握手和十二级量化流水均保持原有采样边沿。

## 功能验证

参考提交为主分支中的 `2e17beb`。形式检查提取两份实际源码中的尾部计算，对两个 32 位尺寸及两个完整块坐标使用自由输入，比较全部 64 位通道数和行数输出。同时核对被证明表达式以外的全部逻辑保持相同。

15 组算术参数全部通过 Yosys SAT，包含 `VLEN=1、2、3、7、16、32、1024、65536、131072、1073741824` 与 `REG_WIDTH=4、16、32、64` 的对应组合。这些参数覆盖幂次和非幂次通道数、窄寄存器容量、块起点左移截断、尺寸零值及无符号最大值。

完整接口回归采用生产通道数，启用 `SYNTHESIS` 分支及 Xilinx 官方 `LUT6_2`、`DSP48E1` 模型。两份设计逐周期比较全部 18 个公开输出，包含无效周期的数据值。

| 总线宽度 | 场景 | 比较周期 | 向量组数 | DMA 命令 | DMA 响应拍 |
|---|---:|---:|---:|---:|---:|
| 32 | 256 | 528,662 | 206,800 | 922 | 12,322 |
| 64 | 256 | 528,662 | 209,001 | 958 | 6,496 |

## 综合和组合路径

生产配置为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`，保留全部公开输出，采用相同的 Xilinx 七系列综合流程。

| 项目 | 参考设计 | 当前设计 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 8,018 | 7,953 | −65 |
| 触发器 | 7,040 | 7,013 | −27 |
| CARRY4 | 419 | 390 | −29 |
| DSP48E1 | 96 | 96 | 0 |
| 分布式 RAM LUT | 1,120 | 1,120 | 0 |
| SRL LUT | 192 | 192 | 0 |
| RAMB18 / RAMB36 | 0 / 0 | 0 / 0 | 0 |
| 通道使能寄存器的最长组合路径 | 15 | 9 | −6 |
| 尾部通道数寄存器的最长组合路径 | 12 | 4 | −8 |
| 从 `k_r` 到寄存器的最长组合路径 | 13 | 14 | +1 |
| 全模块最长组合路径 | 15 | 15 | 0 |

路径长度按实际网表中寄存器之间经过的组合单元数量计算。当前最长路径分别由装载偏移到状态寄存器，以及复用掩码到装载字数寄存器。`k_r` 的最长路径到达装载字数寄存器。完整 SoC 布局布线后的时序分析负责检查 150 MHz 目标。

本次复用 `2e17beb` 的参考综合网表；输入源码、全部依赖、参数、原语模型和去除输出目录差异后的映射命令均已核对一致。`measurement.json` 保存源码摘要、综合统计、形式证明和完整接口结果。

## 复现

从仓库根目录运行，环境中需提供带 slang 插件的 Yosys Python 模块和 Verilator。

```bash
python test/requant_tail_count/run_formal.py \
  --out build/requant_tail_count/formal
python test/requant_pipeline/run_interface.py \
  --out build/requant_tail_count/interface \
  --reference-rev 2e17beb --bus-width 32 64 \
  --verilator verilator-modern --jobs 1 --xilinx
python test/requant_tail_count/prepare_measurement.py \
  --out build/requant_tail_count/inputs
python scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_tail_count/inputs/cases.json \
  --cases reference tail_count \
  --out build/requant_tail_count/synthesis
python test/requant_tail_count/measure_paths.py \
  --reference build/requant_tail_count/synthesis/reference \
  --candidate build/requant_tail_count/synthesis/tail_count \
  --out build/requant_tail_count/paths.json
```
