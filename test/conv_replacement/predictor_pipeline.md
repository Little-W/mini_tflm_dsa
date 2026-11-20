# 下一次访问预测器的坐标预计算

`conv_next_use_predictor` 在接受 `start` 的时钟边沿保存输入坐标与填充量之和。候选流水线继续每周期处理一个卷积核位置，随后计算输出位置与访问顺序。配置处理、`busy`、`done`、`next_rank` 的更新周期保持不变。

## 位宽与运算

输入坐标为 32 位无符号数，前置填充为 16 位无符号数，两者之和使用 33 位寄存器。候选阶段用 34 位有符号减法扣除 32 位膨胀偏移。该范围能够完整表示从 `-(2^32-1)` 到 `2^32+65534` 的结果。移位前仍截取低 32 位；有效性检查继续要求坐标非负、满足步长整除条件且小于配置边界。

`predictor_arithmetic.py` 从当前与指定版本的 RTL 提取实际表达式，使用 Yosys SAT 对所有输入位模式证明两个坐标的完整有符号值、移位结果和有效标志逐位相同。坐标、填充、偏移乘积、步长掩码和范围均不施加输入限制。

## 执行检查

```bash
python3 test/conv_replacement/predictor_test.py \
  --reference-ref aa2ef9a3 \
  --build build/predictor_precompute/functional \
  --out build/predictor_precompute/functional/summary.json
python3 test/conv_replacement/predictor_arithmetic.py \
  --out build/predictor_precompute/arithmetic
python3 test/conv_replacement/predictor_synthesis.py \
  --reference-ref aa2ef9a3 --out build/predictor_precompute/synth_reference
python3 test/conv_replacement/predictor_synthesis.py \
  --out build/predictor_precompute/synth_current
```

功能检查包含 33 组配置、13,226 次预测，覆盖 14 组可用配置和 19 组禁止启用的配置。新增案例覆盖最大 16 位填充、膨胀与大步长。六个公开输出与 `aa2ef9a3` 在 206,076 个周期逐位相同。预测延迟仍为卷积核位置数加 7 个周期，最大为 32 个周期。

独立综合使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`，每次保存参与综合的源码和 SHA-256 摘要。

| 指标 | `aa2ef9a3` | 坐标预计算 |
|---|---:|---:|
| LUT 单元 | 1,801 | 1,764 |
| 触发器 | 1,126 | 1,128 |
| DSP48E1 | 13 | 13 |
| CARRY4 | 129 | 146 |
| 最长组合路径单元数 | 15 | 15 |

最长路径仍位于配置阶段的块数量计算。组合路径单元数用于检查结构深度；150 MHz 的建立时间检查由完整 SoC 的器件时序流程完成。
