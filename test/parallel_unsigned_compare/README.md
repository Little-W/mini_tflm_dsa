# 并行无符号比较器

`parallel_unsigned_compare` 同时输出完整的无符号小于关系和相等关系。输入按三位分组，每次合并最多三个分组。参数 `p_preserve_groups` 默认为 `0`；关键路径可以将其设为 `1`，保留分组比较及归并结果。两种配置使用相同的运算表达式和四态处理方式。

```bash
python3 test/parallel_unsigned_compare/run.py --out build/parallel_unsigned_compare
```

测试覆盖 1、2、3、7、16、27、28、32、35、64 位。每种位宽均证明默认配置和保留分组配置在全部二态输入下与 SystemVerilog 的 `<`、`==` 相同。四态测试使用固定种子 `20261125`，包含相等值、相邻值，以及两个操作数每一位的 X/Z 输入，并逐项检查两个配置的完整输出。
