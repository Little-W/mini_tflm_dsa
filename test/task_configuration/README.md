# 任务配置等价验证

测试将当前 `npu_task_configuration` 与提交 `2247144937c2fd04039b9b005151f371d6b51f8f` 中的模块进行比较，使用相同的公共算术依赖。默认参数和 `p_size=8、p_size_shift=3` 参数分别执行验证。

```bash
python test/task_configuration/prove_equivalence.py --out build/task_configuration_formal
python test/task_configuration/compare_four_state.py --out build/task_configuration_four_state
```

形式验证需要 Pyosys 和 `read_slang`，证明任意二态输入、配置启动序列和暂停条件下的全部输出等价。四个部分积寄存器使用相同的比较点；部分积归并表示中的中间信号分别命名，由完整输出关系验证其等价性。

四态仿真需要 Icarus Verilog 12。每组参数运行 40,000 个周期，在时钟边沿前后各比较一次全部 45 个公开输出，并比较内部完整的 `rhs_allocation_bytes`。输入覆盖复位、重叠启动、暂停、尺寸边界以及 X/Z。后 16,000 个周期直接驱动四个部分积寄存器，覆盖独立部分积的进位组合和单个位未知值传播。

输出目录保存所使用的源码、源码摘要、参数、日志和 JSON 结果。测试脚本以非零退出状态报告编译、证明或逐周期比较失败。
