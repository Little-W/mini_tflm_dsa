# Softmax 数值与累加器验证

`run.py` 将 `vector_softmax` 的 INT8 输出与 TFLM 的最近偶数舍入实现比较。测试覆盖 16 和 32 个元素、输入极值、相等输入、查表响应等待、错误响应、任务恢复与随机输入。

`vector_softmax_accumulator` 位于独立源文件中。指数响应在接收边沿保存，数据及有效标志在下一边沿参与三十二位模累加。清除和复位同时取消待处理有效标志；累计数据在时钟边沿清除。最后一个指数响应后，控制器经过累加完成周期再开始归一化。

```bash
python3 test/vector_softmax/run.py --out build/vector_softmax --depths 16 32
python3 test/vector_softmax/run_accumulator_formal.py --out build/softmax_accumulator_formal
```

累加器形式检查覆盖全部二十位指数整数部分、舍入进位及任意有效、清除和复位序列。独立参考先形成完整二十一位舍入值，再按模 `2^32` 累计。

全部目标使用相同的普通算术实现。`--xilinx` 可保留工程编译宏，数值模型和被测运算保持一致。完整引擎测试见 `test/vector_engine/README.md`，覆盖共享乘法器、生产 DMA 以及 32 位和 64 位 AXI 接口。

输出目录保存构建日志、运行日志、源文件摘要及结果汇总。
