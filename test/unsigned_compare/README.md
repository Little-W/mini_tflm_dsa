# 无符号关系比较

`unsigned_compare` 以正整数参数 `p_width` 指定操作数位宽，同时输出 `i_a < i_b` 和 `i_a == i_b`。模块使用 SystemVerilog 无符号关系运算，四态传播遵循相同运算符。

```bash
python3 test/unsigned_compare/run.py --out build/unsigned_compare
```

测试覆盖 1、8、16、17、24、29、32、33、47、48、64 位，共 11 组全部输入 SAT 和 164,736 次四态检查。四态测试在两个操作数的每一位分别插入 X/Z，并比较完整输出。
