# 权重加载完成资格

`kernel_completion_check` 并行准备本周期有无加载完成的两种结果。每个结果同时检查全部加载是否已经完成，以及发送计数是否覆盖加载计数。完整发出计数的零值和一值标志保留低端回绕关系，最后由加载完成事件选择结果。

加载计数、发送计数、状态转换和公开完成事件仍在相同边沿更新。未知输入采用完整差值与条件表达式，保留四态控制语义。

## 验证

```bash
python3 test/kernel_completion/run.py --out /tmp/kernel_completion
python3 test/kernel_completion/measure.py --out /tmp/kernel_completion_mapping
python3 test/kernel_compare_stage/run_formal.py --out /tmp/kernel_comparison_stability
```

4 种分块大小和计数位宽分别通过通用与 FPGA 检查，共 8 项完整控制模块形式等价。外部输入没有附加限制，全部共有状态和公开输出逐周期一致。独立条件检查遍历全部 262,144 种四态输入组合。

16 个元素一块、29 位计数的完整控制模块使用 1,344 个逻辑 LUT，最长寄存器间组合路径为 10 级。加载完成事件到独立资格结果寄存器的路径为 1 级，完整独立条件模块的最长路径为 3 级。

`validation.json` 保存功能检查结果，`measurement.json` 保存源码摘要、资源和组合路径。描述符比较的稳定性检查保留当前完成资格的完整逻辑，验证比较输入的采样稳定性和预取等待状态。
