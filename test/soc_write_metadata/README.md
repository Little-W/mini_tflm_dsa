# CPU 写地址目的标志缓存

`soc_cpu_write_address_metadata` 在写地址缓冲接收地址时计算 RAM、NPU、UART、SoC 控制寄存器和错误响应的目的标志。两个标志存储槽与两个地址存储槽共用接收、发送及复位事件。互连发送地址时直接读取已经保存的标志。

标志存储槽复位为零地址的译码值。地址尚未有效或缓冲刚完成发送时，目的标志仍与对应地址存储槽一致。该结构使用已有写地址缓冲的周期和容量。

## 验证

```bash
python3 test/soc_write_metadata/run.py --out build/soc_write_metadata
python3 test/soc_write_ready/run.py --predecoded \
  --reference 8b3728c0 --out build/soc_write_metadata/interconnect --verilator verilator
```

第一项检查比较实际标志缓存与两个完整地址存储槽。六组参数覆盖 32、40、64 位地址、不同 RAM 容量、非二次幂容量、非整数容量倍数的起始地址和重叠地址窗口。形式证明允许接收、发送、复位及地址输入自由变化；四态仿真共比较 300,000 个周期。

第二项检查使用标志等于当前缓存地址译码的输入关系，验证完整互连的全部公开输出和保存状态。第一项检查证明该关系在地址缓存中持续成立。互连证明覆盖 16 组参数，四态检查包含普通及 `SYNTHESIS` 编译，共比较 80,004 个周期；另有六组并发写事务回归。

模块验证结果保存在 `validation.json`，完整互连结果保存在 `test/soc_write_ready/validation.json`。
