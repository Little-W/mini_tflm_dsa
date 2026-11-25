# 写回分组步长

`oa_writer` 将复用数量译为七位系数，通过完整定宽乘法计算每组的行地址步长。系数覆盖 `1、2、4、8、16、25、32、64`，其他复用数量对应系数一。普通乘法表达式由综合工具推断算术资源。

当 `COUNT_WIDTH` 和 `REG_WIDTH` 均不小于七时，确定值输入使用该乘积。较小计数位宽保留定宽常量的匹配顺序；行步长包含 `X/Z` 时，按移位和二十五倍乘法分别传播未知位。寄存器的复位、配置采样、使能和保持条件保持相同，计算周期不变。

参考提交为 `ed5c58aba41671e4727e98d35a2fd635360656c8`。本项 RTL 修改仅涉及 `rtl/npu/writeback/oa_writer.sv`。

## 资源与结构路径

全部测量采用 Yosys `0.71+40`、Slang 与 XC7 ABC9，实际参数由 `-G` 明确指定。逻辑 LUT 单独计数，完整输出模块另外使用 120 个分布式 RAM LUT 和 14 个移位寄存器 LUT。

| 完整模块及参数 | 逻辑 LUT：参考→当前 | 触发器：参考→当前 | DSP：参考→当前 | 寄存器最长组合级数：参考→当前 |
| --- | ---: | ---: | ---: | ---: |
| 写回控制器，`COUNT_WIDTH=29` | 1,427→1,352 | 944→929 | 2→2 | 10→10 |
| 写回控制器，`COUNT_WIDTH=16` | 1,121→1,048 | 803→788 | 2→2 | 9→9 |
| 输出模块，当前 SoC 配置 | 6,195→6,155 | 3,094→3,079 | 32→32 | 10→10 |
| 输出模块，默认扩展容量 | 5,943→5,879 | 2,976→2,961 | 32→32 | 10→10 |

写回控制器的两组参数均使用 `VLEN=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`。两种完整输出配置见 `test/output_timing/cases.json`，其 RAMB36E1/RAMB18E1 数量均保持 `4/27`。

当前 SoC 输出模块的输入到寄存器、寄存器到输出、输入到输出最长路径分别为 `9/7/4` 级；默认扩展容量分别为 `10/7/4` 级。所有完整连接图均可遍历，没有未分类单元。结构级数不包含器件和布线延迟，150 MHz 需要目标器件的布局布线时序分析。

## 功能与周期检查

| 检查 | 结果 |
| --- | --- |
| 完整写回控制器时序归纳证明 | 8 组参数通过，每周期比较全部公开输出及全部状态寄存器 |
| 完整写回控制器四态比较 | 5 组参数，128,475 个周期、256,945 次检查通过 |
| 实际组步长表达式时序归纳证明 | 12 组计数/数据位宽通过，覆盖 1 至 64 位及七位启用边界 |
| 组步长四态、复位和使能 | 144,048 个周期通过，包含数据、计数、复位与使能的 `X/Z` |
| 实际映射后的组步长输出 | 使用完整 FPGA 单元功能模型，32 个输出位的无限时序等价证明通过 |

验证不增加输入取值或握手限制。`validation.json` 保存源码、脚本、网表摘要和参数信息。

## 复现

环境需要 Slang/Pyosys、Icarus Verilog，完整输出模块综合使用仓库的 FPGA 流程。

```sh
writer_result=/tmp/oa_writer_group_step
writer_reference=ed5c58aba41671e4727e98d35a2fd635360656c8

python test/oa_writer_group_step/run_step.py \
  --reference "$writer_reference" --out "$writer_result/step_validation"

python test/oa_writer_row_count/run_formal.py \
  --reference "$writer_reference" --out "$writer_result/controller_formal"

python test/oa_writer_geometry/run_four_state.py \
  --reference "$writer_reference" \
  --profiles 4:32:4 8:64:6 16:64:7 16:64:29 32:64:32 \
  --out "$writer_result/controller_four_state"

python test/oa_writer_group_step/prepare_measurement.py \
  --reference "$writer_reference" --out "$writer_result/inputs"

python scripts/fpga/open_fpga_synth.py \
  --source-root . --case-config "$writer_result/inputs/cases.json" \
  --cases step_reference_29 step_current_29 \
    writer_reference_29 writer_current_29 writer_reference_16 writer_current_16 \
  --out "$writer_result/mapping" --abc9-batch-size 64 --abc9-isolate-leaves

python test/oa_writer_group_step/check_mapped.py \
  --source "$writer_result/inputs/step_current.sv" \
  --mapped "$writer_result/mapping/step_current_29/mapped.json" \
  --out "$writer_result/mapped_validation"

python scripts/fpga/open_fpga_synth.py \
  --source-root . --case-config test/output_timing/cases.json \
  --cases output_production output_default --require-register-path-limit \
  --out "$writer_result/output" --abc9-batch-size 64 --abc9-isolate-leaves
```
