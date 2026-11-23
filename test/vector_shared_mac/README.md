# 向量 PE 的共享乘加验证

`vector_pe` 使用同一条行为级乘加表达式处理乘加与求和。求和将乘数固定为一，比较操作保留完整 32 位累加值的有符号次序。

`run_formal.py` 使用统一 PE 的完整算术证明和输入寄存状态证明，覆盖八种操作码和两种 `ENABLE_EXTENDED_MULTIPLY` 配置。16 位输入 `a`、`b` 和 32 位 `acc` 不施加数值约束，比较全部 32 位结果。寄存状态归纳证明覆盖输入选择、操作码切换和任意使能暂停。

```sh
python test/vector_shared_mac/run_formal.py \
  --reference-rev caace9471dafe0236f0e2a9a40b8ddb48bdb844d \
  --out build/vector_pe_shared_mac_formal
```

数值回归同时覆盖 PE 运算和完整标量乘积：

```sh
python test/vector_engine/run_pe.py --out build/vector_pe_shared_mac --jobs 1
```

形式检查输出保存源码 SHA256 和完整证明结果摘要。`--arithmetic-summary` 可复用输入文件哈希相符的已完成证明。
