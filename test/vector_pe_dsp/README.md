# 统一寄存向量运算验证

`vector_pe` 同时保存操作码、乘数和累加值。输入使能暂停时，这些状态共同保持。数值测试使用独立整数运算，检查全部八种操作码、符号边界、乘积低 32 位和暂停期间的输出。

```bash
python3 test/vector_pe_dsp/run.py --out build/vector_pe_numeric
python3 test/vector_pe_dsp/run_formal.py --out build/vector_pe_formal
python3 test/vector_pe_dsp/run_engine_formal.py --out build/vector_pe_connection
python3 test/vector_pe_dsp/run_capacity.py --pes 8 16 --out build/vector_pe_capacity
```

形式入口复用 `test/vector_extremum`，覆盖扩展乘法与累加预选的四种功能参数组合。接入检查直接提取实际 `vector_engine.sv` 中的操作数选择和 PE 实例，比较通道有效性、深度卷积反馈、使能、操作码、全部乘数与累加寄存状态以及结果。

结构检查按照实际配置核对矩阵单元数量、向量 PE 数量、存储容量和寄存状态。普通 RTL 综合输入由 `test/conv_portable/prepare_measurement.py` 生成，各输出目录保存参与检查的源码 SHA256 与结果。
