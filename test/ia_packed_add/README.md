# IA 紧凑读写的分段加法

`select_add` 的 `p_split_12bit` 参数在 48 位端口上启用四个独立的 12 位模加通道。FPGA 实现使用 DSP48E1 的 `FOUR12` 模式；通用 RTL 分别计算四个通道。参数默认关闭，原有调用保留整字模加语义。

IA 紧凑写入将四个输入字节分别零扩展到 12 位，再把各通道结果的低八位写回原有字节排列逻辑。每组无符号八位加法的完整和不超过 510，通道中的高位足以保存进位。

紧凑读取先分别把有符号字节与有符号偏移扩展到 12 位，计算后按结果位宽扩展到阵列数据位宽。生产配置使用九位偏移，完整和为十位。四个通道的进位及未知位传播彼此独立。结果位宽超过十二位的参数继续使用完整宽度加法。

所有加法保持组合输出，写入命令寄存、读出数据周期、有效信号及 16 列并行规模保持一致。

## 模块综合

参考提交为 `9ef04420`。生产参数使用 16 列、64 位总线、32 个物理缓存块、外部存储与九位紧凑偏移，工具为 Yosys 0.71+40。

| 资源或路径 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,748 | 1,560 |
| 分布式存储 LUT | 8 | 8 |
| 触发器 | 354 | 354 |
| DSP48E1 | 8 | 6 |
| CARRY4 | 70 | 22 |
| 寄存器间最大组合单元数 | 11 | 10 |
| 全部组合路径最大单元数 | 11 | 12 |

写入使用两个分段 DSP，读取恢复使用四个分段 DSP。`measurement.json` 保存每次运行的源码散列值、模型来源、参数和结果。

## 功能检查

- 十二组全输入 SAT 检查通过。独立加法覆盖八位和十二位操作数的全部组合，恢复加法覆盖一位、八位、九位和十一位有符号偏移，均检查 DSP 与通用 RTL。
- 四态仿真完成 100,002 组输入、400,008 次结果比较，包含同时进位、符号边界、独立通道中的未知位和高阻位。
- 原有 `select_add` 默认模式的位宽 1、17、32、48 通过全输入 SAT。
- 七组完整 IA 缓存状态等价通过，共 19,840 个状态与输出比较位。参数覆盖本地及外部存储、4/8/16 列、8/16 位数据，以及 8/32/64/128/256 位总线。
- IA 的 39 个公开输出逐周期检查通过，完成 180,122 周期和 903,952 个数值比较。
- 57,344 字节共享存储检查通过，完成 4,681,255 周期和 15,022,624 个数据数值比较，覆盖全部 S8 偏移和全部 S16 位模式。

## 复现

```sh
python3 test/ia_packed_add/run.py --out /tmp/ia_packed_add/unit
python3 test/select_add/run_formal.py --out /tmp/ia_packed_add/default
python3 test/ia_write_output_depth/run_formal.py --reference 9ef04420 --cases production generic_s4_b32_d8_c2_e0 generic_s8_b64_d16_c4_e0 generic_s16_b8_d16_c32_e1 generic_s16_b32_d16_c32_e1 generic_s16_b128_d16_c32_e1 generic_s16_b256_d16_c32_e1 --out /tmp/ia_packed_add/formal
python3 test/ia_write_output_depth/run_numeric.py --reference 9ef04420 --cases interface shared --out /tmp/ia_packed_add/numeric
python3 test/ia_write_output_depth/prepare_measurement.py --reference 9ef04420 --out /tmp/ia_packed_add/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config /tmp/ia_packed_add/inputs/cases.json --cases reference current --out /tmp/ia_packed_add/native
```
