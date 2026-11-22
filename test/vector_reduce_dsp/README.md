# 向量归约验证

归约单元执行 INT32 模加法、极大值或极小值。极小值选择优先，形式检查覆盖全部两个输入数值与两个选择条件。

```bash
python3 test/vector_reduce_dsp/run_formal.py --out build/vector_reduce
```

统一综合输入可由 `test/conv_portable/prepare_measurement.py` 生成。源文件、验证日志与结果摘要保存在指定输出目录。
