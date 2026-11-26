# 读取上下文的行末比较

`u_rsp_row_equal` 保留各位相等结果，再合并完整行末条件。上下文存储输出先进入独立的逐位比较，后级完成结果归并与读取事务结束判断。

生产参数下，完整线性 DMA 使用 1,403 个逻辑 LUT、763 个触发器，完整模块最长组合路径为 10 级。参考实现为 1,392 个逻辑 LUT。读取上下文至行末相等结果的组合路径从 4 级缩短到 3 级。读取事务结束信号的其他路径保持不变。

五组参数分别执行通用实现和 FPGA 综合实现的完整状态等价检查，共 10 组全部通过。两种实现模式还各自完成 30,001 个周期的四态测试，逐周期比较 37 个公开输出及保存的行末状态关系。

```bash
python test/linear_dma_row_finish/run.py --out build/linear_dma_row_finish
```

`read_comparison_measurement.json` 保存资源和路径结果，`read_comparison_validation.json` 保存完整状态及四态验证结果。
