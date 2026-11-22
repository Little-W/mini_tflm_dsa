# 完整读取地址运算验证

32 位基地址、32 位偏移和 16 位通道按无符号数相加，保留完整 34 位结果。所有输入编码均由 SAT 证明。实际读取状态译码和四态行为由 test/vector_dma_address 检查。

```bash
python3 test/vector_address_dsp/run_formal.py --out build/vector_address
```

统一综合输入可由 `test/conv_portable/prepare_measurement.py` 生成。源文件、验证日志与结果摘要保存在指定输出目录。
