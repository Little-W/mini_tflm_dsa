# 向量 PE 的共享乘加验证

`vector_pe` 使用同一条行为级乘加表达式处理乘加与求和。求和将乘数固定为一，比较操作保留完整 32 位累加值的有符号次序。

`run_formal.py` 对八种操作码和两种 `ENABLE_EXTENDED_MULTIPLY` 配置逐一证明 32 位结果与参考版本相等。16 位输入 `a`、`b` 和 32 位 `acc` 不施加数值约束。比较仅连接模块输入与输出，内部辅助变量可采用各自的实现结构。

```sh
python test/vector_shared_mac/run_formal.py \
  --reference-rev 415a70a \
  --out build/vector_pe_shared_mac_formal
```

已有数值回归同时覆盖 PE 运算和完整标量乘积：

```sh
python test/vector_engine/run_pe.py --out build/vector_pe_shared_mac --jobs 1
```

形式检查输出包含源码、参考源码和每次证明日志的 SHA256，以便将结果对应到实际验证的实现。
