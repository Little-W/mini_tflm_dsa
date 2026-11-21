# SoC AXI 互连的请求选择

CPU 地址进入两项队列时保存目的端口标志。队列有效状态与 RAM 读写容量状态随对应计数器更新，仲裁直接读取保存的标志。计数器保持原有位宽和回绕行为。当前地址及首拍地址分别计算下一地址，宽加法采用行为级 RTL 和综合属性。

`p_cpu_read_overlap=1` 保留响应完成周期内发送下一地址的行为。完整 SoC 使用 `p_cpu_read_overlap=0`，在 CPU 读响应完成后发送下一地址，缩短从响应缓冲到仲裁状态的组合路径。NPU 的在途事务容量保持由读写参数控制。

## 验证

八组参数分别证明容量标志、目的端口标志与原始状态的关系，并在无公开输入限制的条件下比较完整模块状态与输出。参数覆盖 32、40、64 位地址、32、64 位数据、不同存储容量及地址起点。四态仿真比较 20,001 个周期中的 73 个公开输出和读事务状态。

并发事务测试另行检查生产设置，四种配置共完成 19,200 个 CPU 与 DMA 事务。测试及统计见 `test/soc_interconnect_transactions`。

生产参数独立综合为 658 个逻辑 LUT、225 个触发器和 3 个 DSP，完整寄存器连接图最长组合路径为 10 级。完整 SoC 的组合深度和布局布线时序分别测量。

## 复现

`--reference-ref` 支持 Git 提交或固定源码目录。正式结果同时保存被比较源文件的 SHA-256。

```bash
python test/soc_interconnect_depth/run_formal.py --reference-ref 415a70a --out build/interconnect_formal
python test/soc_interconnect_depth/check_four_state.py --reference-ref 415a70a --out build/interconnect_four_state
```

实际验证参数、状态关系证明、参考源码散列值和综合结果保存在 `measurement.json`。
