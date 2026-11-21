# SoC AXI 互连的请求选择

CPU 读地址进入两项队列时保存目的端口标志。写地址直接产生各目的端口的独立选择位，按原有地址窗口优先次序处理重叠区域；活动写命令和新地址分别生成选择位，再由活动状态选择。队列有效状态与 RAM 读写容量状态随对应计数器更新，仲裁直接读取保存的标志。计数器保持原有位宽和回绕行为。当前地址及首拍地址分别计算下一地址，宽加法采用行为级 RTL 和综合属性。

`p_cpu_read_overlap=1` 保留响应完成周期内发送下一地址的行为。完整 SoC 使用 `p_cpu_read_overlap=0`，在 CPU 读响应完成后发送下一地址，缩短从响应缓冲到仲裁状态的组合路径。NPU 的在途事务容量保持由读写参数控制。

## 验证

八组参数分别证明容量标志、目的端口标志与原始状态的关系，并在无公开输入限制的条件下比较完整模块状态与输出。参数覆盖 32、40、64 位地址、32、64 位数据、不同存储容量及地址起点。四态仿真比较 20,001 个周期中的 73 个公开输出和读事务状态。

写事务测试在 32、64 位数据接口、1、4 个在途请求和写入重叠开关的六种配置下完成 24,576 笔事务。测试检查背压、响应顺序、错误地址、复位和并发请求。并发读写事务测试入口另见 `test/soc_interconnect_transactions`。

生产参数独立综合为 662 个逻辑 LUT、227 个触发器和 3 个 DSP，完整寄存器连接图最长组合路径为 9 级。同参数参考提交为 661 个 LUT、225 个触发器、3 个 DSP 和 11 级。完整 SoC 的组合深度和布局布线时序分别测量。

## 复现

`--reference-ref` 支持 Git 提交或固定源码目录。正式结果同时保存被比较源文件的 SHA-256。

```bash
python test/soc_interconnect_depth/run_formal.py \
  --reference-ref cedf4ed33661a53c8194eca1d484cdc2279d7549 --out build/interconnect_formal
python test/soc_interconnect_depth/check_four_state.py \
  --reference-ref cedf4ed33661a53c8194eca1d484cdc2279d7549 --out build/interconnect_four_state
python test/soc_interconnect_writes/run.py --verilator verilator --out build/interconnect_writes
```

实际验证参数、状态关系证明、参考源码散列值和综合结果保存在 `measurement.json`。
