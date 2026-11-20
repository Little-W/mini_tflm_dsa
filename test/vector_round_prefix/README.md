# 向量读取地址与舍入进位验证

## 实现

`vector_engine` 使用一个组合 `DSP48E1` 计算读取地址。两个 32 位地址分量和零扩展后的 16 位通道号先经过逐位压缩，得到异或结果 `sum_bits` 和多数值 `carry_bits`；DSP 计算 `sum_bits + (carry_bits << 1)`。每一位的两个压缩结果由同一个 `LUT6_2` 产生。加法保留完整 34 位结果，DSP 的输入、控制和输出寄存器均旁路，读取译码和请求周期保持不变。

`vector_round_shift` 保留低位移位、中间寄存器及高位移位。对于高于最低字节的部分，进位成立要求全部较低商位为一，因此最低商位已经满足最近偶数舍入中的奇偶条件。各高字节的进位可直接表示为保护位与低位全一条件的逻辑与。FPGA 实现将全一判断分为四位组、六组汇总和字节条件，最多经过三层 LUT。八个字节分别完成八位递增。

最低字节继续使用保护位、舍弃位和最低商位共同决定递增。通用实现与 FPGA 实现使用相同的舍入规则；`REGISTER_MIDDLE` 的两种配置保持原有周期。

## 完整向量映射

参考版本为 `e6fd2b1f`。参数为 `TILE=16`、`DMA_SIZE=64`、`BUS_WIDTH=64` 和 `PE_COUNT=8`。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 11,013 | 11,040 |
| 分布式存储 LUT | 248 | 248 |
| 触发器 | 6,029 | 6,029 |
| DSP48E1 | 16 | 17 |
| 完整模块最长同步组合级数 | 15 | 15 |
| 寄存器至读取地址端口的最长组合级数 | 17 | 11 |
| `state` 至读取地址端口的最长组合级数 | 16 | 8 |
| 舍入中间寄存器至 `q_rounded` | 15 | 9 |
| 舍入中间寄存器至 `add_rounded` | 15 | 9 |

地址端口的分析增加了采样终点，采样终点不增加组合逻辑，也不计入资源统计。对新增地址 DSP 的全部输入反向检查，未发现经过组合逻辑连接的其他 DSP。同步路径分析使用实际 DSP 内部寄存器参数。

上述资源来自完整向量模块的原生 Xilinx 映射。物理 LUT 占用和 150 MHz 器件时序由完整 SoC 的布局布线结果提供。

## 形式验证

- 地址加法覆盖全部 80 位输入组合，逐位比较完整 34 位结果。官方 `DSP48E1`、`LUT6_2` 模型和通用实现均通过。
- 实际读取译码对所有状态、操作类型及输入值比较全部输出。`BUS_WIDTH/TILE` 配置为 `32/16`、`64/16`、`128/16`、`32/3` 和 `64/32`，五组均通过。
- 源码比较确认地址加法实例及其实现之外的引擎内容保持不变。
- 舍入比较覆盖全部有符号 64 位输入、全部六位移位量及逐周期输入变化。官方 LUT 模型与通用实现分别验证 `REGISTER_MIDDLE=0/1`，四组均通过。
- 源码比较确认移位逻辑和中间寄存器保持不变。

以上检查均未对数据输入增加范围或数值限制。原有读取地址和舍入递增验证脚本也已通过。

## 完整事务数值与周期验证

测试使用八个 PE、实际 DMA 和官方 FPGA 原语。独立整数参考模型检查向量算术、量化 Add、深度卷积、池化、Softmax 及错误恢复。

| 总线宽度 | 任务数 | 检查输出数 | 任务周期总数 |
| --- | ---: | ---: | ---: |
| 32 位 | 592 | 169,487 | 3,017,541 |
| 64 位 | 592 | 168,601 | 2,979,488 |

两种总线宽度的全部任务统计和周期均与 `1dd73c74` 的银行共享验证结果逐项相同。输入银行观察器分别检查了 3,023,462 和 2,985,409 个周期。

`measurement.json` 保存源码摘要、形式验证结果、实际映射资源、连接路径、数值统计和构建文件摘要。

## 复跑

Python 环境需要包含支持 `read_slang` 的 `pyosys`。数值测试的 Verilator 需要支持 `--output-groups`。

```sh
python3 test/vector_address_dsp/run_formal.py --reference e6fd2b1f --out build/vector_paths/address_formal
python3 test/vector_round_prefix/run_formal.py --reference e6fd2b1f --out build/vector_paths/round_formal
python3 test/vector_dma_address/run_formal.py --reference-rev e6fd2b1f --out build/vector_paths/decode_formal
python3 test/vector_round_carry/run_formal.py --reference-ref e6fd2b1f --out build/vector_paths/carry_formal

python3 test/vector_input_banks/prepare_measurement.py --reference e6fd2b1f --out build/vector_paths/measurement
python3 scripts/fpga/open_fpga_synth.py --case-config build/vector_paths/measurement/cases.json --cases vector_reference vector_current --out build/vector_paths/synthesis --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock

python3 test/vector_address_dsp/inspect_paths.py --mapped build/vector_paths/synthesis/vector_reference/mapped.json --out build/vector_paths/address_reference.json
python3 test/vector_address_dsp/inspect_paths.py --mapped build/vector_paths/synthesis/vector_current/mapped.json --out build/vector_paths/address_current.json --require-address-dsp
python3 test/vector_round_prefix/inspect_paths.py --mapped build/vector_paths/synthesis/vector_reference/mapped.json --out build/vector_paths/round_reference.json
python3 test/vector_round_prefix/inspect_paths.py --mapped build/vector_paths/synthesis/vector_current/mapped.json --out build/vector_paths/round_current.json

python3 test/vector_engine/run.py --xilinx --bus-width 32 --pes 8 --jobs 1 --out build/vector_paths/bus32
python3 test/vector_engine/run.py --xilinx --bus-width 64 --pes 8 --jobs 1 --out build/vector_paths/bus64
```
