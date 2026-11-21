# 窗口接收元素计数

有效元素掩码通过平衡加法树生成本拍元素数。32 位累计值的低位直接相加，高位分别根据低位进位和原累计值的全一前缀生成新值。高位按三位分组，再逐层合并长度倍增的区间，保留各层组合节点和完整的 32 位模加法结果。

该结构保持原接收事件、寄存器更新条件和公开周期。辅助加法器使用普通可综合 RTL。

`run_formal.py` 从实际 `vector_engine.sv` 提取掩码计数和累计表达式，与参考提交 `dde5e7c9` 比较。已通过 `WINDOW_LANES=1、3、4、8、16、31、32` 七组全部输入等价检查，不限制掩码或累计值。

```bash
python test/vector_window_count/run_formal.py \
  --reference dde5e7c9 --out build/vector_window_count
```

输出目录保存每组参数的源码片段、证明脚本和日志。`summary.json` 记录当前 RTL、辅助加法器、参考源码及日志摘要。
