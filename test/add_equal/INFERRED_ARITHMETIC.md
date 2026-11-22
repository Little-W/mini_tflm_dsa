# 模加等式的编译配置检查

`add_equal` 在通用、ASIC 与 FPGA 编译配置下采用同一份并行进位一致性逻辑，全部输入按 `p_width` 定宽解释，输出保留模加结果的相等关系。

`run_inferred.py` 对 1、2、16、23、24、28、32、33、47、48、64 位分别运行三种编译配置，共 33 组完整二态输入证明。所有比较输入均自由取值。

同一批位宽和编译配置完成 211,920 次四态比较。1 位与 2 位遍历全部 `0/1/X/Z` 输入组合，其余宽度各执行 6,000 次比较；参考表达式检查完整进位向量的一致性。

```bash
python3 test/add_equal/run_inferred.py --out build/add_equal_configurations
```

源文件摘要、比较模型摘要和各项结果保存在 [inferred_validation.json](inferred_validation.json)。
