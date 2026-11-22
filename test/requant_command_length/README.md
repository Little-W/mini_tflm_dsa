# 参数 DMA 长度计算验证

`vec_requant` 使用完整 33 位差值保留剩余字数及借位。装载偏移超过总数时返回零，其余情况按 `VLEN` 限制本次传输字数，再由总线宽度得到八位突发末拍编号。

```bash
python test/requant_command_length/run_formal.py --out build/requant_command_length
```

测试将实际 RTL 表达式与直接饱和减法、字数上限及除法模型比较。两个完整 32 位输入均不受限制。配置覆盖 32、64、96、128 位总线与 1、3、16、32、256、1024 个向量元素，共十二组组合检查。
