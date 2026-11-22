# 参数控制与存储接口验证

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`run_formal.py` 从实际 `vec_requant` 源码提取配置保存、DMA 控制和全部参数存储。量化行消费、参数读取地址及串行元素选择作为独立输入，因此可以在算术流水级数变化时检查相同的参数控制行为。

WS 存储保留完整内容和全部读取端口。IS 存储的对应字段接收共同的任意读数据，全部写入数据、地址、使能、读取地址和时钟端口均参与比较。输入数值与控制时序不附加功能限制。

```bash
python test/requant_parameter_ports/run_formal.py \
  --reference-root <参考源码目录> --out build/requant_parameter_ports
python test/requant_parameter_ports/check_four_state.py \
  --source-root . --reference-root <参考源码目录> \
  --out build/requant_parameter_ports_four_state
```

配置覆盖 1、2、4、16 个计算通道，32、64、128 位总线，逐张量和逐通道参数。四态检查补充未知数据、未知地址、未知写入资格以及任意串行读取位置。
