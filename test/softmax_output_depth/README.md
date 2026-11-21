# Softmax 输出舍入与组合路径

`vector_softmax` 在细移位后并行计算八位整数值的保持结果与递增结果，再由保护位、舍弃位和最低保留位选择最近偶数舍入结果。正向饱和资格直接比较舍入前的数值，与递增运算同时完成。负值饱和、输出写使能、状态转移和乘法结果等待周期保持原有定义。

零增量与单位增量均保留原生算术表达式。选择条件包含未知位时使用原生算术结果，使 `0/1/X/Z` 数据的传播与参考实现一致。生产代码采用普通可综合 SystemVerilog，由工具推断加法和选择逻辑。

## 功能检查

| 检查 | 结果 |
|---|---:|
| 完整状态与所有公开输出等价 | 12 种配置通过 |
| 严格四态舍入检查 | 80,896 组输入通过 |
| 实际整数 Softmax 场景 | 160,676 个通过 |
| 实际整数结果比较 | 15,031,388 个元素通过 |
| 数值回归周期 | 153,797,051 |

完整等价检查覆盖 `MAX_DEPTH=1/3/16/32/256`、`MULTIPLIER_LATENCY=0/1/2` 及通用、FPGA 两种编译分支。全部输入保持任意取值，逐周期比较所有公开输出和共有时序状态。

数值回归复用 `test/vector_softmax_normalize/run.py` 的实际测试，包含深度 16、32、256，直接乘法结果与两级乘法结果等待，查表错误、背压、复位和重新开始。所有数值场景使用 TFLM 整数计算作为参考，并启用 C++ 未定义行为检查。

## 完整模块结构测量

测量使用 `MAX_DEPTH=16`、`MULTIPLIER_LATENCY=2`、`XILINX_FPGA=1` 与统一 xc7 映射流程。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 551 | 558 |
| 寄存器 | 335 | 335 |
| 寄存器间最长组合单元数 | 10 | 10 |
| 内部寄存器至 `out_data` 的最长组合单元数 | 10 | 7 |

模块寄存器图完整。公开输出端口的测量单独记录边界范围；与上层结果寄存器连接后的路径通过完整 SoC 网表检查。150 MHz 与物理 Slice LUT 数量使用目标器件的布局布线报告确认。

## 复现

```bash
python3 test/softmax_output_depth/run.py \
  --baseline-ref aa0a169c --out build/softmax_output_validation --numeric

python3 test/softmax_output_depth/prepare_measurement.py \
  --baseline-ref aa0a169c --out build/softmax_output_inputs
python3 scripts/fpga/open_fpga_synth.py \
  --source-root build/softmax_output_inputs/current \
  --case-config build/softmax_output_inputs/cases.json \
  --cases reference current --out build/softmax_output_mapping \
  --lock-file /tmp/npu_synthesis_20261121.lock --max-register-path-cells 14
python3 test/ia_control_output_depth/measure_paths.py \
  --top vector_softmax \
  --reference-folder build/softmax_output_mapping/reference \
  --current-folder build/softmax_output_mapping/current \
  --out build/softmax_output_paths.json
python3 test/softmax_output_depth/collect_results.py \
  --validation build/softmax_output_validation/summary.json \
  --measurement build/softmax_output_paths.json \
  --out build/softmax_output_results.json
```

`measurement.json` 保存本轮实际通过的检查、源码 SHA256 和完整模块路径测量。
