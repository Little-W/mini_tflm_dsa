# 高段进位的并行分组修正

`parallel_prefix_add` 的 `p_parallel_high_prefix` 参数默认关闭。
当该参数和 `p_preserve_groups` 同时为 1，且 `p_dsp_split_width` 选择有效的分段算术时，
每四个高段结果位由一个 `parallel_prefix_high_group` 组合模块计算。
各模块直接读取全部较低组的传播条件，独立完成进位与本组结果的异或修正。

低段编码进位在组内恢复极性，最高输出进位与普通结果位采用相同的计算方式。
全部输入、输出位宽和寄存器保持原有定义。实现使用普通布尔表达式和已有的算术推断，
`keep_hierarchy` 用于保留各个组合计算模块。

32 位加法的调用参数示例：

```systemverilog
parallel_prefix_add #(
    .p_width(32),
    .p_preserve_groups(1'b1),
    .p_dsp_split_width(16),
    .p_parallel_high_prefix(1'b1)
) u_add (
    .i_a(add_i_a), .i_b(add_i_b), .i_carry(add_i_carry),
    .o_sum(add_o_sum), .o_carry(add_o_carry)
);
```

## 验证结果

参考提交为 `777634ba768c03f59aa319fd854170dc835f9721`。

- 64 组参数通过完整结果的无约束算术证明，覆盖高段宽度 1 至 23、完整最高进位、
  两种 `p_preserve_groups` 设置，以及分段参数不启用时的原有计算方式。
- 默认编译方式与 `SYNTHESIS` 编译方式分别完成 394,240 个四态完整结果比较。
  测试包含所有输入位的 X/Z 注入、未知输入进位、零值、全一值和随机输入。
- 使用实际映射网表和完整 `DSP48E1` 功能模型，对全部 33 个结果位完成无约束顺序等价证明。

固定 32 位输入、16 位分段、输入进位为 1，输入和完整输出各设置一级寄存器时：

| 指标 | 参考实现 | 并行修正 |
|---|---:|---:|
| 逻辑 LUT | 28 | 27 |
| 触发器 | 97 | 97 |
| DSP | 1 | 1 |
| 寄存器间最长组合单元数 | 4 | 4 |

以上数据来自 Yosys 的 Xilinx 7 系列映射及完整连接分析。
组合单元数用于检查结构深度；器件布线后的工作频率仍需实现工具测量。
每个调用位置应结合其完整父模块测量后启用此参数。

## 复现

在仓库根目录运行，`OUT` 为自选结果目录。需要带 `read_slang` 的 Pyosys 和 Icarus Verilog。

```bash
python test/parallel_high_carry/run_unit.py --reference 777634ba --out "$OUT/unit"
python test/parallel_high_carry/prepare_arithmetic.py --reference 777634ba --out "$OUT/inputs"
python scripts/fpga/open_fpga_synth.py \
  --source-root "$OUT/inputs/reference" --case-config "$OUT/inputs/reference/cases.json" \
  --cases arithmetic --out "$OUT/reference"
python scripts/fpga/open_fpga_synth.py \
  --source-root "$OUT/inputs/current" --case-config "$OUT/inputs/current/cases.json" \
  --cases arithmetic --out "$OUT/current"
python test/parallel_high_carry/run_mapped.py --mapped "$OUT/current/arithmetic" --out "$OUT/mapped_proof"
```

`common_validation.json` 保存参数、源码摘要、资源计数及验证结果。
