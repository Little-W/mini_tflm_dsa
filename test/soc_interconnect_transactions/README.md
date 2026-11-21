# SoC 互连并发读取

测试连接实际 `soc_axi_interconnect`，分别驱动 CPU 与 DMA 请求，并提供独立的 RAM、NPU、UART 和控制寄存器响应模型。每种配置在四次复位之间完成 2,400 个 CPU 事务和 2,400 个 DMA 事务。

四种配置覆盖 32/64 位数据总线、一或四个在途事务，以及 CPU 响应完成周期内发送下一地址的两种参数设置。检查固定地址与递增突发、首地址未按数据字排列的读取、目的地址译码、错误返回、响应顺序、结束标记、数据内容和接收端背压。测试使用 C++20 与 UndefinedBehaviorSanitizer。

```bash
python test/soc_interconnect_transactions/run.py --out build/interconnect_transactions
```

`validation.json` 保存参数、实际源码散列值及各配置的检查数量。
