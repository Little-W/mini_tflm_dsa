# 最近偶数舍入数值验证

本测试同时检查支持逐通道配置的 INT8 实例、静态整张量 INT8 实例、INT16 控制模块实例和独立 INT16 算术通道。全部实例使用统一 `requant_compute_lane` 运算结构，输入累加值为 INT32。

```bash
python test/requant_rne/run.py --out build/requant_rne --verilator verilator
```

独立整数参考根据除法商、余数、符号和奇偶位计算最近偶数舍入，随后应用输出偏移和精度限制。测试覆盖正负半值、乘数准备边界和极值输入，共检查 320,000 个输出元素。运行结果保存源码散列、可执行文件散列和完整日志。
