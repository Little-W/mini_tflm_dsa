# 输出 FIFO 的末拍状态

FIFO 在保存行列配置时同时保存末拍索引。开始读取银行、首拍等待期间刷新配置以及完成银行读取时，末拍索引与对应行数、列数和转置模式一起更新。输出握手直接比较保存的索引，维持公开接口的逐周期行为。

九组完整模块形式比较覆盖全部公开输出、存储端口、有效银行计数及末拍状态。四态测试从实际 RTL 提取配置更新过程，使用七组向量长度和总线宽度，在 20,000 个周期中完成 700,000 次严格比较，覆盖未知输入、复位和任意控制组合。

生产参数独立综合得到 1,160 个逻辑 LUT、60 个分布式存储 LUT、165 个触发器和 8 个 RAMB18。完整寄存器连接图的最长组合路径为 10 级。器件时序应使用完整 SoC 的布局布线结果检查。

```bash
python test/fifo_last_beat/run_formal.py --out build/fifo_last_beat_formal
python test/fifo_last_beat/run_four_state.py --out build/fifo_last_beat_four_state
```

源文件散列值、形式比较及四态测试汇总保存在 `validation.json`。
