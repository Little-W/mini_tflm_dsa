# 向量量化偏移与归约加法

`run_formal.py` 从当前 `vector_engine.sv` 和附件版本 `2f06471c` 提取完整量化偏移、符号范围、激活限幅与归约输出逻辑，分别比较全部输入编码。量化相加采用四个八位段并保留第 33 位进位；归约相加保留完整三十二位回绕。最大值和最小值归约的有符号选择保持相同。

```sh
python3 test/vector_parallel_add/run_formal.py --out build/vector_timing/arithmetic
```

完整模块的状态、周期和资源检查见 [向量控制与分段算术](../vector_control_bounds/README.md)。
