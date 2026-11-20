# 标量乘法器的 DSP 级联实现

`rtl/npu/conv/vector_scalar_multiplier.sv` 每周期接收两个有符号 INT32
操作数，经过两个时钟采样边沿输出完整 INT64 乘积。原有 `clk`、`a`、`b`、
`product` 接口保持。数据通路持续运行，无复位和使能端口。

`p_use_dsp=1` 使用五个 `DSP48E1`。四个 DSP 分别计算低半字乘低半字、
低半字乘高半字、高半字乘低半字和高半字乘高半字。低半字按无符号数
扩展，高半字按有符号数扩展，四个部分积均由对应 DSP 的 `PREG` 保存。

第二阶段将高半字乘积与低半字乘积的高十六位拼接，作为第五个 DSP 的
`A:B` 输入。两个交叉部分积分别接入 `C` 和 `PCIN`，完成三个操作数的
四十八位求和。`PCIN` 直接连接第三个部分积 DSP 的 `PCOUT`。低十六位
由普通寄存器保存，与最终 `PREG` 在同一边沿接收第一阶段的数据。

| 时钟边沿 | 部分积寄存器 | 结果寄存器 |
|---|---|---|
| E0 | 接收输入 0 的四个部分积 | 接收前一个输入的最终结果 |
| E1 | 接收输入 1 的四个部分积 | 接收输入 0 的完整乘积 |
| E2 | 接收输入 2 的四个部分积 | 接收输入 1 的完整乘积 |

`p_use_dsp=0` 使用通用可综合算术实现，保留相同的数值和周期行为。
`ASIC_SYNTHESIS` 下该参数默认为 0；`XILINX_FPGA` 或 `SYNTHESIS` 下默认为 1；
其余仿真环境默认为 0。参数允许显式覆盖默认值。辅助 DSP 模块与主模块
位于同一文件，现有源文件列表可以直接使用。

## 功能与周期验证

```sh
python3 test/vector_scalar/run.py --out build/vector_scalar \
  --simulate --synthesis --verilator verilator-modern \
  --synth-script scripts/fpga/open_fpga_synth.py

python3 test/vector_engine/run.py --out build/vector_scalar_bus32 \
  --bus-width 32 --verilator verilator-modern --jobs 2 --xilinx --pes 8

python3 test/vector_engine/run.py --out build/vector_scalar_bus64 \
  --bus-width 64 --verilator verilator-modern --jobs 2 --xilinx --pes 8
```

形式验证使用官方 `DSP48E1` 功能模型，将参数值 0、1 分别与 `b8b34d5`
中的标量乘法器进行时序等价比较。四个部分积、组合拼接和完整乘积共
242 位全部通过，覆盖任意输入和连续流水。仿真额外检查 1,134,340 个
完整 64 位乘积，包含符号边界、交替位模式、全部低半字值与连续随机输入。
每次同时检查低十六位和高四十八位的采样周期。

完整向量回归分别使用 BUS32、BUS64、TILE16、PE8 和实际 DSP 功能模型，
每种配置执行 592 项任务，覆盖深度卷积、池化、归约、Add、Softmax、
DMA 等待、地址边界、错误恢复和计算写出重叠。各项输出由独立整数模型
检查，接口稳定性由原有断言检查。

## 资源与物理实现

XC7 独立模块综合结果如下。

| 实现 | 逻辑 LUT | 普通寄存器 | DSP | CARRY4 |
|---|---:|---:|---:|---:|
| 四个 DSP 与组合求和 | 95 | 64 | 4 | 12 |
| 五个 DSP 级联求和 | 0 | 16 | 5 | 0 |

正式实现与已完成独立布局布线的五 DSP 电路，在展开后的全部顶层端口、
单元类型、参数和连接上完全一致。比较时仅移除 `g_dsp.` 层级前缀。
`check_routed_graph.py` 复查该关系，并核对四十八位专用级联连接、五个
`PREG=1`、合法放置和布线完成状态。

```sh
python3 test/vector_scalar/check_routed_graph.py \
  --mapped build/vector_scalar/synthesis/scalar_dsp/mapped.json \
  --routed-reference /path/to/routed_scalar_dsp \
  --out build/vector_scalar/routed_graph.json
```

独立物理实现的级联源和接收者分别位于 `DSP48_X0Y78` 与 `DSP48_X0Y79`。
布线完成后使用五个 DSP、十六个普通寄存器和五个用于常量的物理 LUT
位置。目标时钟为 150 MHz；该独立实现报告尚未覆盖 DSP 寄存端口的完整
器件时序，频率确认字段保留为空。集成时增加一个 DSP，完整 SoC 的器件
容量和时序由整机实现结果检查。

`measurement.json` 保存最终源文件、官方原语模型、形式证明、数值回归和
物理电路比较的摘要及 SHA256。
