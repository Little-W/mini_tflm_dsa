# 写回初始复用数量检查

输出写回模块用独立的 `zero_reduce` 组合层次检查初始复用数量。全部输入位同时参与零值归约，完整行数比较使用已经形成的一位结果。输入为零时选择一个复用分块，其余输入保持类型转换后的数量。状态、寄存器更新边沿和公开输出保持一致。

## 验证

```bash
python3 test/oa_initial_reuse/run.py --out /tmp/oa_initial_reuse
python3 test/oa_initial_reuse/measure.py --out /tmp/oa_initial_reuse_mapping
```

4 种行宽、总线宽度及计数位宽组合分别进行通用与 FPGA 形式检查，共 8 项。全部共有状态和公开输出在任意外部输入下逐周期等价。两种规模的实际写回模块进一步通过 2,048 个四态场景、102,778 次公开输出比较。

16 列、64 位总线、29 位计数的完整模块映射使用 1,254 个逻辑 LUT、929 个触发器和 4 个推断 DSP，模块内部最长寄存器间组合路径为 10 级。跨模块输入到写回寄存器的路径由完整 SoC 单独检查。

验证结果保存在 `validation.json`，源码摘要及同设置映射结果保存在 `measurement.json`。
