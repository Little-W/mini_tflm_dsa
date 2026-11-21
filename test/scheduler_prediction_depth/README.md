# 调度器预测准备与组合深度

预测准备的首级分别保存有效帧集合和起点之后的有效帧集合。下一寄存级并行编码两个集合，并分别比较候选是否为当前活动帧，随后选择帧编号和匹配结果。后续各级按照已有时序读取元数据、计算尾部尺寸。公开命令与预测输出的有效周期保持一致。

候选选择和预测选择共同使用四帧分组编码。组内编号与组间资格并行计算，实际的分组归并节点保留组合边界。含未知值的集合按逐帧优先条件计算编号，保持四态结果。

切片取整使用各位以下的非零条件并行计算模宽减一。完整操作数含未知值时使用 SystemVerilog 算术表达式，保留严格四态结果。

## 验证结果

- 5 组参数的完整状态、公开输出、元数据存储和 K 维度存储通过逐周期等价证明，相对提交 `415a70a` 的直接证明通过。
- 未分片和分片调度共 975 个用例、182,426 条命令通过独立软件模型检查，包含预测内容、压力处理、提前结束、尾部形状及物理存储容量；所有 C++ 编译单元启用 UBSan。
- 7 组参数执行 29,452 次严格四态检查，覆盖模宽减一、预测集合的保存与选择、帧编号编码及活动帧匹配。
- 在生产 FPGA 综合设置下，`SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32` 的逻辑 LUT 为 1,289，触发器为 966，DSP 为 7，RAMB36E1 为 2；完整寄存器路径图的最长路径为 9 级。预测集合至帧编号寄存器最长为 6 级，至活动帧匹配寄存器最长为 8 级。

`validation.json` 保存源文件散列值、参数和详细结果。完整 SoC 的外部控制输入仍使用完整 SoC 连接图进行检查。

```bash
python test/scheduler_column_depth/run.py \
  --reference 415a70a --relation-nets frame_open \
  --out build/scheduler_prediction_depth/formal
python test/ps_compression/run_window_scheduler.py \
  --out build/scheduler_prediction_depth/numeric
python test/scheduler_prediction_depth/run_four_state.py \
  --out build/scheduler_prediction_depth/four_state
```
