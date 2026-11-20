# DW 与 GEMM 共享量化验证

测试直接实例化生产代码中的 `vec_requant`，设置十六个并行量化通道。
每轮依次执行 GEMM、DW、GEMM，使用独立整数除法和余数计算参考结果。

```sh
python3 test/vector_shared_quant/run.py --out build/vector_shared_quant
```

共执行 240 个任务、7,680 个向量和 122,880 个输出通道，检查以下行为：

- GEMM 与 DW 结果分别返回相应客户端，DW 标签保持完整。
- 累加值和乘数包含 `INT32_MIN`、`INT32_MAX`、零、正负一及随机有符号值。
- DW 各通道独立使用 0 至 63 位右移，覆盖最近偶数舍入和正负饱和。
- 完整通道、单个有效通道和随机通道掩码均逐项比较。
- 连续输入和随机空拍均保持十二周期量化延迟。
- 一个任务的全部结果返回后，立即切换到下一任务的参数与客户端。

`summary.json` 保存源码与可执行文件 SHA-256、运行命令及数值检查结果。
完整 DW 计算、参数 DMA、随机 AXI 等待和共享流水错误处理由
`test/vector_engine/run.py --shared-quant` 与
`test/vector_engine/run_window_error.py --shared-quant` 验证。
