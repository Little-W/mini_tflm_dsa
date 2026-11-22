# 量化参数读取选择验证

`vec_requant` 将整张量参数广播到全部通道。WS 模式为每个通道选择其独立参数；IS 模式按输入行选择公共参数。原始参数观察输出与预处理计算参数分别选择，计算参数随同步存储结果进入运算。

```bash
python test/requant_parameter_read/run_formal.py --out build/requant_parameter_read
```

检查从实际源码提取公共选择和通道选择表达式，与直接模式选择模型比较。BUS32、BUS64、BUS96、BUS128 分别覆盖参数观察输出启用与禁用，共八个配置。每个配置比较 16 个通道的全部 1,648 位输出，所有参数数据、行索引与模式位均可自由变化。
