# 向量读取地址加法验证

`run_formal.py` 比较实际 `vector_read_address_add` 的完整 34 位结果，并从 `vector_engine.sv` 提取读取译码，比较五组配置下的全部组合输出。DSP 和 LUT 均使用官方功能模型。

`inspect_paths.py` 从完整向量网表中提取读取地址的组合路径，并检查新增 DSP 的输入是否经过其他 DSP。它读取同目录的 `pre_lut.il` 恢复寄存器名称。

实现说明、完整模块资源和数值结果见 `test/vector_round_prefix/README.md` 与 `test/vector_round_prefix/measurement.json`。
