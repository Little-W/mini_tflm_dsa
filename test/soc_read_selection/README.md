# SoC RAM 读取末拍选择

当前拍、下一拍、队列首项和新到达地址分别计算末拍条件。下一拍与长度的等式使用相邻位的进位一致性并行比较，再归约八个等式结果。响应握手选择已形成的一位结果，使字节计数和长度比较在请求选择之前完成。事件仿真对含未知值的来源选择使用完整字节比较，保持严格四态结果。

检查程序从实际 `soc_axi_ram.sv` 提取组合表达式，证明全部 35 位输入上与完整选择后比较相等，并执行 100,000 次四态比较。实际存储模块另通过 28 组 AXI 事务测试，包含窄传输、不同容量、不同首拍延迟、随机背压及错误响应。

```sh
python test/soc_read_selection/run.py --out build/soc_read_selection
python test/conv_soc_ram/run.py --rtl-source rtl/soc/soc_axi_ram.sv \
  --synthesis --jobs 1 --out build/soc_ram_protocol
```

[validation.json](validation.json) 保存源码散列、组合证明和协议测试结果。
