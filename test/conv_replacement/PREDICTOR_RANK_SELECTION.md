# 预测器候选位置选择

`conv_next_use_predictor` 直接比较候选位置与已保存的最早位置，将候选有效标志用于最终结果选择。位置比较和有效性判断并行执行。无效候选保留已有结果，全部寄存器、配置处理和预测周期保持原有定义。

## 验证

参考提交为 `2f06471c`。完整预测器的形式比较覆盖 1,811 位寄存状态及公开输出，输入没有附加取值限制，全部通过。

数值测试包含 33 组配置、13,226 次预测，覆盖 14 组可用配置和 19 组禁止启用的配置。六项公开输出在 206,076 个周期与参考提交一致。预测延迟保持卷积核位置数加 7 个周期，最大为 32 个周期。

## 独立综合

采用 Yosys 0.71、Xilinx 7 系列映射和当前完整预测器 RTL。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,761 | 1,732 |
| 触发器 | 1,128 | 1,128 |
| DSP48E1 | 13 | 13 |
| CARRY4 | 139 | 139 |
| 最长组合单元数 | 15 | 15 |

结果和源码摘要保存在 [predictor_rank_measurement.json](predictor_rank_measurement.json)。完整 SoC 的实际物理位置数量与时序由整机布局和时序分析统计。

## 重复运行

```bash
python3 test/conv_replacement/predictor_rank_equivalence.py \
  --out build/predictor_rank/formal
python3 test/conv_replacement/predictor_test.py \
  --reference-ref 2f06471c --build build/predictor_rank/interface \
  --out build/predictor_rank/interface/summary.json
python3 test/conv_replacement/predictor_synthesis.py \
  --reference-ref 2f06471c --out build/predictor_rank/reference
python3 test/conv_replacement/predictor_synthesis.py \
  --out build/predictor_rank/current
```
