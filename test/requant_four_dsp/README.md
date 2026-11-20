# 四 DSP 完整 INT32 乘法

`registered_multiplier_s32` 对两个完整三十二位有符号整数计算六十四位乘积。FPGA 实现使用四个 `DSP48E1`，支持每个使能周期接收一组操作数。运算部分包含两个寄存阶段，输入寄存器由 `p_input_register` 和 `p_b_input_register` 分别控制；右输入参数默认跟随左输入参数。`i_en` 为零时，输入、部分积及输出同时保持。

`vector_scalar_multiplier` 保持两周期输出和每周期输入能力。量化中的左输入在 AREG 采样，右输入取同拍保存的参数，完整量化保持十二个寄存阶段。

## 数据拆分与流水结构

每个操作数分为十七位无符号低段和十五位有符号高段：

```text
A = A_low + (A_high << 17)
B = B_low + (B_high << 17)
P0 = A_low  × B_low
P1 = A_low  × B_high
P2 = A_high × B_low
P3 = A_high × B_high
A × B = P0 + ((P1 + P2) << 17) + (P3 << 34)
```

四个部分积的有效宽度分别为 34、32、32、30 位。第一个运算边沿由首个 DSP 的 PREG 保存 `P0`，其余 DSP 的 MREG 保存 `P1`、`P2`、`P3`。

第二个运算阶段通过 PCOUT/PCIN 逐步计算：

1. `P1 + (P0 >> 17)`。
2. 在前一步结果上加 `P2`，低十七位形成中段。
3. 前一步结果算术右移十七位后加 `P3`，末级 PREG 保存高三十位。

首个 DSP 的低十七位和第二步的低十七位由显式 FDRE 在相同使能边沿保存。高三十位、中十七位、低十七位组成完整六十四位结果。各级不舍弃最终乘积所需的信息。

## 综合结果

采用 Yosys 0.71、ABC9 与 Xilinx 7 系列原语模型。表中的 LUT 为综合后的逻辑 LUT 数量；寄存器间组合单元数包含实际 DSP 内部寄存配置产生的组合段。

| 模块 | 指标 | 五 DSP 实现 | 四 DSP 实现 |
| --- | --- | ---: | ---: |
| 独立乘法器 | 逻辑 LUT | 0 | 0 |
| 独立乘法器 | 触发器 | 16 | 34 |
| 独立乘法器 | DSP48E1 | 5 | 4 |
| 独立乘法器 | 最长组合单元数 | 1 | 3 |
| 完整量化 | 逻辑 LUT | 7,601 | 7,600 |
| 完整量化 | 触发器 | 7,213 | 7,501 |
| 完整量化 | DSP48E1 | 96 | 80 |
| 完整量化 | 最长组合单元数 | 15 | 15 |
| 完整向量引擎 | 逻辑 LUT | 11,629 | 11,552 |
| 完整向量引擎 | 触发器 | 5,976 | 5,994 |
| 完整向量引擎 | DSP48E1 | 16 | 15 |
| 完整向量引擎 | 最长组合单元数 | 15 | 15 |

量化配置为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`，全部公开输出参与综合。两种实现均为 800 个分布式 RAM LUT、160 个 SRL LUT 和 2 个 RAMB18E1。量化控制逻辑包含 `34a90bab` 的装载完成条件。

向量引擎使用固定提交 `428c98ca` 的完整源码，只替换标量乘法器；两种实现均为 248 个分布式 RAM LUT。量化的十六个乘法器与向量的一个公共参数乘法器合计释放十七个 DSP。

单个乘法器的最长组合段经过三个 DSP 算术单元。目标 150 MHz 需要包含目标器件 DSP 寄存配置及布线延迟的时序分析。当前 nextpnr Xilinx 模型仅为全组合 DSP 提供完整端口时序路径，以上结果用于资源与结构检查。

## 功能与周期验证

`run_formal.py` 对全部四种 AREG/BREG 参数组合分别证明输入采样和四个部分积，再以不受约束的部分积证明完整结果拼接。两个 INT32 输入和每周期 `i_en` 均不受约束。最终正式 RTL 的所有证明通过。通用实现的输入寄存和完整乘积也通过形式比较。

同步参数组合另证明外部保存 B、内部 AREG=1/BREG=0 与 AREG=1/BREG=1 的完整输出一致。有效采样边沿、任意暂停及全部六十四位结果均参与比较。

| 检查项目 | 范围 | 结果 |
| --- | --- | --- |
| 完整乘积与综合网表 | 1,396,934 个比较周期，995,188 个使能周期，401,763 个暂停周期 | 通过 |
| 标量公开接口 | 1,134,340 次比较，两周期延迟，每周期可输入 | 通过 |
| 独立量化整数参考 | INT8/INT16 共 320,000 个输出，4 种配置 | 通过 |
| BUS32 完整量化接口 | 256 个场景、528,662 个周期、206,800 个输出向量 | 通过 |
| BUS64 完整量化接口 | 256 个场景、528,662 个周期、209,001 个输出向量 | 通过 |
| 完整向量引擎与 DMA | 592 项任务、169,361 个输出、2,995,967 个周期 | 通过 |

乘法数值测试同时检查通用 RTL、DSP RTL、五 DSP 参考及独立有符号整数结果。综合网表使用官方原语功能模型。测试覆盖极值、十七位分段边界、位组合、完整低十七位取值和随机暂停。完整量化接口比较全部 18 个公开输出，完整向量测试的逐任务统计与参考完全相同，包含 Add 143 项和 Softmax 273 项。

`measurement.json` 保存源码、原语库、功能检查、综合网表和实际最长路径的 SHA-256。正式 RTL 将通用算术的局部声明放在通用分支，FPGA 分支的寄存器配置和连接与完整模块测量一致。

## 复现命令

```sh
python3 test/requant_product/run_formal.py \
  --out build/requant_four_dsp/product_formal

python3 test/requant_sync_parameters/run_multiplier_formal.py \
  --out build/requant_four_dsp/sync_formal

python3 test/requant_four_dsp/run.py \
  --reference-rev 5d148afe --verilator "$VERILATOR_BIN" \
  --out build/requant_four_dsp/numeric

python3 test/requant_rne/run.py --xilinx --verilator "$VERILATOR_BIN" \
  --out build/requant_four_dsp/requant_rne

python3 test/requant_pipeline/run_interface.py \
  --reference-rev 5d148afe --xilinx --bus-width 32 64 \
  --verilator "$VERILATOR_BIN" --jobs 2 \
  --out build/requant_four_dsp/interface

python3 test/requant_four_dsp/prepare_measurement.py \
  --out build/requant_four_dsp/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_four_dsp/inputs/cases.json \
  --cases reference_multiplier candidate_multiplier reference_quant candidate_quant \
  --out build/requant_four_dsp/synthesis --lock-file "$SYNTHESIS_LOCK"

python3 test/requant_four_dsp/check_structure.py \
  --mapped build/requant_four_dsp/synthesis/candidate_multiplier/mapped.json \
  --out build/requant_four_dsp/structure.json

python3 test/requant_four_dsp/run.py --verilator "$VERILATOR_BIN" \
  --mapped-reference build/requant_four_dsp/synthesis/reference_multiplier/mapped.v \
  --mapped-candidate build/requant_four_dsp/synthesis/candidate_multiplier/mapped.v \
  --out build/requant_four_dsp/mapped_numeric
```
