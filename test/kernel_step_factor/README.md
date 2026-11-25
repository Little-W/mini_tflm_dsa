# 权重加载器分组步长

`kernel_loader_ctrl` 使用十一位系数表示分组步长，系数覆盖 `1、2、4、8、16、25、32、64、128、256、512、1024`。其他计数值对应系数一。完整系数译码与定宽乘法放在纯组合模块 `kernel_group_step` 中，并保留该完整函数的综合边界。

当 `CNT_W >= 11` 且 `REG_WIDTH >= 11` 时，确定值输入使用该乘积。较小位宽继续使用原有定宽 `case`，包括常量截断后的匹配顺序；包含 `X/Z` 的列步长也保留各移位分支和二十五倍求和的四态传播。

步长寄存器仍由异步复位清零，在 `S_INIT` 状态捕获结果，其他状态保持。清空事件保持地址寄存器内容。组合函数没有增加寄存器或计算周期。

参考提交为 `ed5c58aba41671e4727e98d35a2fd635360656c8`。本次仅修改 `rtl/npu/loaders/kernel_loader_ctrl.sv`；综合和完整模块验证分别读取参考提交及当前实现的全部依赖。

## 完整 kernel 测量

实际展开参数如下；每个参数同时通过综合选项中的 `-G` 指定。

| 参数 | 数值 |
| --- | ---: |
| `SIZE` | 16 |
| `DATA_WIDTH` | 16 |
| `BUS_WIDTH` | 64 |
| `DMA_LANES` | 8 |
| `REG_WIDTH` | 32 |
| `COUNT_WIDTH` | 29 |
| `CACHE_BLOCKS` | 1 |

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 4,336 | 4,107 |
| INV | 38 | 39 |
| 触发器 | 2,339 | 2,343 |
| CARRY4 | 220 | 214 |
| DSP48E1 | 0 | 2 |
| RAMB18E1 | 16 | 16 |
| 寄存器之间最长组合级数 | 10 | 10 |
| 输入到寄存器最长组合级数 | 11 | 10 |
| 寄存器到输出最长组合级数 | 10 | 10 |
| 输入到输出最长组合级数 | 10 | 10 |

逻辑 LUT 减少 229 个。两个实现使用相同的 20 份依赖文件及综合设置，仅控制器文件内容不同，完整连接图检查通过。LUT、INV 和存储资源分别计数。结果来自 Yosys `0.71+40`、Slang 和 `synth_xilinx` 的 ABC9 映射；实际 150 MHz 时序需要目标器件的布局布线延迟分析。

## 独立步长及实际 DSP 验证

独立模型直接从控制器提取完整步长表达式，并接入相同的异步复位、清空保持和使能捕获寄存器。列步长与重用次数是公开输入，因此以下深度统计使用输入到寄存器的完整路径。

| 配置 | 逻辑 LUT：参考→当前 | 触发器：参考→当前 | DSP：参考→当前 | 输入到寄存器级数：参考→当前 |
| --- | ---: | ---: | ---: | ---: |
| `REG_WIDTH=32, COUNT_WIDTH=29` | 323→43 | 32→32 | 0→2 | 9→8 |
| `REG_WIDTH=64, COUNT_WIDTH=64` | 640→59 | 64→64 | 0→4 | 11→10 |

两份当前网表均装载完整的 Xilinx `cells_sim.v` 功能模型，分别证明 32 位和 64 位公开输出的无限时序等价。证明隐藏内部组合网名，只按公开接口建立对应，不增加输入范围限制。

## 功能与周期检查

| 检查 | 结果 |
| --- | --- |
| 完整步长全输入 SAT | 13 组位宽配置全部通过 |
| 步长捕获寄存器无限时序等价 | 相同 13 组全部通过 |
| 步长四态、复位与使能比较 | 156,013 个周期通过，包含数据、计数、复位、清空和使能的 `X/Z` |
| 完整 kernel 无限时序等价 | 5 组参数，54,893 个等价位全部通过 |
| 完整 kernel 四态比较 | 20,004 个周期，每周期比较 23 个公开输出 |
| 完整 kernel 异步复位比较 | 4,004 个周期，覆盖复位 `0/1/X/Z` |
| 完整事务逐周期比较 | 29,439 个比较周期，23 个公开输出全部一致 |
| 数值及传输检查 | 285 个 tile、72,960 个数值、312 次 DMA、1,649 个收发重叠周期全部一致 |

局部参数包括 `REG_WIDTH=2/4/7/8/10/11/32/64`，计数位宽覆盖 `0/1/3/8/10/11/16/29/32/64`，具体配对保存在 `validation.json`。完整 kernel 参数覆盖 64 位和 128 位总线、29 位和 32 位计数、较小计数、非二次幂通道数及单通道。事务测试启用 C++ 未定义行为检查，并覆盖 S8/S16、im2col、尾部补零、预取、丢弃和清空操作。

## 复现

在仓库根目录运行。环境需要包含 Slang 的 Pyosys、Icarus Verilog、支持 C++20 的 Verilator 和 C++ 编译器。

```sh
kernel_result=/tmp/kernel_step_factor
kernel_reference=ed5c58aba41671e4727e98d35a2fd635360656c8
kernel_verilator=verilator

python test/kernel_step_factor/check_step.py \
  --reference "$kernel_reference" --out "$kernel_result/arithmetic"

python test/kernel_step_factor/measure_step.py \
  --reference "$kernel_reference" --out "$kernel_result/step_mapping"

python test/kernel_row_feedback/run_formal.py \
  --reference "$kernel_reference" --out "$kernel_result/kernel_formal"

python test/kernel_prefetch/run_loader_four_state.py \
  --reference "$kernel_reference" --count-width 29 \
  --out "$kernel_result/kernel_four_state"

python test/kernel_row_feedback/check_reset_four_state.py \
  --prepared "$kernel_result/kernel_four_state" \
  --out "$kernel_result/reset_four_state"

python test/kernel_prefetch/run_reference_comparison.py \
  --reference "$kernel_reference" --bus-width 64 --count-width 29 \
  --verilator "$kernel_verilator" --out "$kernel_result/transactions"

python test/kernel_row_feedback/prepare_measurement.py \
  --reference "$kernel_reference" --out "$kernel_result/inputs"

for kernel_variant in reference current; do
  python scripts/fpga/open_fpga_synth.py \
    --source-root "$kernel_result/inputs/$kernel_variant" \
    --case-config "$kernel_result/inputs/cases.json" \
    --cases "$kernel_variant" --out "$kernel_result/kernel_mapping" \
    --lock-file "$kernel_result/kernel_mapping.lock" \
    --require-register-path-limit

  python test/output_configuration/analyze_interfaces.py \
    --top kernel_loader \
    --netlist "$kernel_result/kernel_mapping/$kernel_variant/mapped.json" \
    --pre-lut "$kernel_result/kernel_mapping/$kernel_variant/pre_lut.il" \
    --out "$kernel_result/kernel_mapping/$kernel_variant/interface_paths.json"
done
```

`check_step.py` 和 `measure_step.py` 支持 `--source-root` 指向固定源码目录。每项检查记录源码、脚本和结果的 SHA-256；综合清单记录实际参数、器件库和各阶段命令。大型网表与编译对象保存在指定输出目录，仓库保留测试源码及摘要。
