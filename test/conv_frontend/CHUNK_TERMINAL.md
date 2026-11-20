# 前端末段判断

前端对每条输出通道直接检查输入字内的剩余字节。八位输入使用 `offset < 4-lane`，十六位输入使用 `offset < 3-2*lane`；超出输入字可容纳范围的通道固定为不可用。比较边界在生成阶段确定。

每条可用通道同时检查自己是否对应当前行的最后一列，各通道结果归并后生成 `chunk_reaches_end`。`wr_last` 和行状态更新共同使用该结果。通道数 `chunk_count` 继续用于位置递增和请求计算，末段判断直接使用通道条件。容量、端口和传输周期保持一致。

## 验证

参考提交为 `151b87d5`。形式验证包含真实缓存和预测器，对全部输入位模式比较完整状态与公开输出。五组参数覆盖 `SIZE=4/8/16`、`LANES=1/2/4`、32/64 位总线及四种缓存策略，共证明 196,101 位状态与输出相同。其中生产参数组为 `SIZE=16`、`LANES=4`、`BUS_WIDTH=64`、`CACHE_SETS=128` 和 `CACHE_POLICY=3`，单组证明 87,430 位。

逐周期数值测试覆盖 `LANES=2/4`，每种通道数分别测试 `SIZE=4/8/16` 以及窗口预取。296 项数值任务共完成 3,422,534 个周期；控制专项完成 23 项检查和 134 个周期。全部 19 项公开输出、矩阵数值和完成周期一致。

## 独立综合

采用 Xilinx 7 系列普通算术映射，配置为 `SIZE=16`、`LANES=4`、`BUS_WIDTH=64`、128 组两路缓存和 16 字节缓存行。缓存与预测器作为独立接口边界。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 6,586 | 6,503 |
| 触发器 | 3,236 | 3,236 |
| DSP48E1 | 30 | 30 |
| CARRY4 | 730 | 726 |
| 最长寄存器间组合单元数 | 21 | 20 |

源码摘要、参数、形式结果、逐周期记录和组合路径测量见 [frontend_chunk_terminal_validation.json](../../docs/data/frontend_chunk_terminal_validation.json)。完整 SoC 的物理 LUT 使用量和组合级数由整机流程测量。

## 重复运行

```bash
python3 test/conv_frontend/tools/run_state_equivalence.py \
  --reference-ref 151b87d5 --out build/frontend_chunk_terminal/formal
python3 test/conv_frontend/tools/compare_frontend.py \
  --reference-ref 151b87d5 --lanes 2 4 --out build/frontend_chunk_terminal/interface
python3 test/conv_frontend/tools/synthesis.py \
  --reference-ref 151b87d5 --lanes 4 --out build/frontend_chunk_terminal/reference
python3 test/conv_frontend/tools/synthesis.py \
  --lanes 4 --out build/frontend_chunk_terminal/current
python3 test/conv_frontend/tools/measure_descriptor_paths.py \
  --mapped build/frontend_chunk_terminal/current/mapped.json \
  --pre-lut build/frontend_chunk_terminal/current/pre_lut.il \
  --out build/frontend_chunk_terminal/current/paths.json
```
