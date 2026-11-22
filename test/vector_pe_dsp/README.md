# 寄存向量运算验证

寄存向量单元在 i_en 有效时保存操作数，当前操作码选择完整乘加与极值结果。形式与四态检查复用 test/vector_extremum，数值测试使用独立整数模型检查全部操作码及使能暂停。

```bash
python3 test/vector_pe_dsp/run_formal.py --out build/vector_pe_formal
python3 test/vector_pe_dsp/run.py --out build/vector_pe_numeric
```

统一综合输入可由 `test/conv_portable/prepare_measurement.py` 生成。源文件、验证日志与结果摘要保存在指定输出目录。
