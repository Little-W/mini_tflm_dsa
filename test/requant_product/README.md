# 共享量化乘法器验证

`registered_multiplier_s32` 为标量和完整量化数据通路提供有符号 INT32 乘法。公共 `vector_scalar_multiplier` 接口保持不变；该接口以连续使能使用共享单元的两级算术流水。量化实例启用 `p_input_register=1`，将原有输入寄存阶段保存在乘法 DSP 的 AREG/BREG 中。

共享实现和 DSP 封装位于现有 `rtl/npu/conv/vector_scalar_multiplier.sv`。只编译量化模块的工程需要同时包含该文件；完整 NPU 和 SoC 的源文件列表已经包含它。

## 寄存阶段

| 量化阶段 | 数据 | 保存位置 |
|---|---|---|
| 0 | INT32 累加值和处理后的乘数 | 四个乘法 DSP 的 AREG/BREG |
| 1 | 低低、低高、高低、高高四个部分积 | 四个乘法 DSP 的 PREG |
| 2 | 完整 64 位乘积 | 合并 DSP 的 48 位 PREG 和低 16 位寄存器 |
| 3 至 9 | 分级移位、溢出方向、商和舍入进位 | 原有移位流水 |
| 10 | 商、输出偏移和舍入增量 | 舍入加法 DSP 的 PREG |
| 11 | 激活范围和 INT8/INT16 饱和结果 | 原有输出寄存器 |

输入 A、B 的低十六位按无符号扩展，高十六位保留符号。四个部分积按下式合并，计算结果保留全部六十四位：

\[
A B = A_{lo} B_{lo}
  + (A_{lo} B_{hi} + A_{hi} B_{lo}) 2^{16}
  + A_{hi} B_{hi} 2^{32}.
\]

合并 DSP 使用 A:B、C、PCIN 三个操作数。高低部分积直接从相邻乘法 DSP 的 PCOUT 连接至 PCIN。低十六位在同一使能边沿保存，与高四十八位来自同一次输入。

量化实例的所有输入寄存、PREG 和低位寄存都由 `!init_cfg` 使能。暂停时所有阶段保持；配置恢复后继续原有采样顺序。`rst_n` 对有效位和输出的处理保持原有行为。完整量化仍为十二个寄存阶段，支持每周期接收一组输入。标量实例使用 `p_input_register=0`，维持两个寄存阶段。

## 形式验证

`run_formal.py` 从实际共享 RTL 和官方 `DSP48E1` 模型展开设计，覆盖通用、FPGA 两种实现，以及有无输入寄存的两种参数。

- 无输入寄存时，两种实现分别证明 338 位算术寄存结果与参考四部分积实现一致。
- 有输入寄存时，先比较输入保存行为。通用实现比较 64 位；FPGA 实现比较四组 AREG/BREG 的全部 192 位，覆盖所有符号扩展和重复保存的位。
- 输入保存行为证明通过后，将这些对应的寄存输出作为后两级算术的公共自由输入，再分别证明 338 位结果。时钟使能在每个周期自由变化。
- 六项证明全部通过。公共标量接口另外以两个参数配置分别证明 242 位状态和结果，参考版本为 `b8b34d5`。
- 原有舍入加法的当前连接另外完成 36 位阶段输出证明。

## 完整结果与接口比较

`run.py` 从 `038a095` 的实际量化赋值和实例连接生成参考乘积流水，并与独立 INT64 乘法结果比较。测试包含正负边界、单比特组合、低半字全部取值、连续输入、暂停期间输入改变和连续暂停。

| 检查 | 通过数量 |
|---|---:|
| 两级完整 64 位乘积 | 1,200,072 |
| 三级完整 64 位乘积 | 1,200,070 |
| 使能边沿 | 863,954 |
| 暂停边沿 | 336,131 |
| BUS32 完整量化接口 | 256 个场景、528,662 个周期、206,800 组向量 |
| BUS64 完整量化接口 | 256 个场景、528,662 个周期、209,001 组向量 |
| 独立量化舍入结果 | 320,000 个输出、4 种配置 |

接口比较包含全部十八个输出和无效周期的数据，覆盖参数 DMA 装载、WS、IS、per-tensor、per-channel、INT8、INT16、输入间隔、尾部通道、配置刷新和运行期间复位。FPGA 测试使用官方 `LUT6_2` 和 `DSP48E1` 功能模型。

## 综合资源与组合路径

参考版本为 `038a095`。综合顶层为 `vec_requant`，保留完整公共输出，参数为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`。此次独立比较采用相同的普通 Xilinx 映射流程。

| 资源 | 参考实现 | 共享乘法实现 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 10,373 | 10,377 | +4 |
| 外部触发器 | 7,588 | 7,044 | −544 |
| DSP48E1 | 96 | 96 | 0 |
| PREG=0 的 DSP | 32 | 0 | −32 |
| PREG=1 的 DSP | 64 | 96 | +32 |
| CARRY4 | 423 | 423 | 0 |
| LUT RAM 的标称 LUT 数 | 1,120 | 1,120 | 0 |
| SRL 的标称 LUT 数 | 192 | 192 | 0 |
| RAMB18/RAMB36 | 0/0 | 0/0 | 0/0 |

乘积路径的每个乘法 DSP 都在 PREG 保存结果，乘法 DSP 与合并 DSP 之间由输出寄存器分隔。十六组高低部分积 PCOUT 到合并 DSP PCIN 的直接连接已从映射网表逐组检查。

| 外部组合路径 | 参考实现 | 共享乘法实现 |
|---|---:|---:|
| 寄存器至乘法 DSP 输入 | 6 | 6 |
| 完整乘积 PREG 至下一寄存器 | 5 | 5 |
| 舍入 PREG 至输出寄存器 | 6 | 6 |
| 模块最长寄存器路径 | 17 | 17 |

这些数值统计实际相连的外部组合单元。DSP 内部延时和布线延时需要器件时序分析；物理 LUT 数和 150 MHz 结果由完整 SoC 实现报告确定。此次修改保持 DSP 总数，全 SoC 的宽 ALU 预算映射仍需按集成后的网表重新执行。

## 复现命令

```bash
python test/requant_product/run_formal.py --out build/requant_product/formal
python test/requant_product/run.py --out build/requant_product/numeric --verilator verilator-modern
python test/vector_scalar/run.py --out build/requant_product/scalar
python test/requant_registered_sum/run_integration.py --out build/requant_product/rounding --reference-rev 1c081bc
python test/requant_pipeline/run_interface.py --out build/requant_product/interface --reference-rev 038a095 --bus-width 32 64 --verilator verilator-modern --jobs 2 --xilinx
python test/requant_rne/run.py --out build/requant_product/rne --verilator verilator-modern --xilinx
python test/requant_product/prepare_measurement.py --out build/requant_product --reference-rev 038a095
python scripts/fpga/open_fpga_synth.py --source-root . --case-config build/requant_product/cases.json --cases reference shared_product --out build/requant_product/synthesis --lock-file build/synth-small.lock
python test/requant_product/measure_paths.py --synthesis build/requant_product/synthesis --out build/requant_product/paths.json
```

`measurement.json` 保存源文件摘要、六项形式证明、完整结果比较、接口回归、资源和路径统计。
