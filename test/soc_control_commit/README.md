# SoC 控制寄存器的写入阶段

`soc_axil_ctrl` 分别接收并保存 AXI Lite 写地址和写数据。两个输入都已保存后，下一周期更新目标寄存器并产生写响应。写入内容、地址选择和字节使能均来自已有寄存器；写地址与写数据可以独立到达。读端口继续在接收地址的时钟边沿保存读取结果。

每笔写事务在最后一个请求通道完成握手后增加一个周期。写响应有效并等待接收期间，地址和数据通道停止接收，响应及寄存器值保持稳定。异步复位清除请求、响应和公开寄存器。

## 验证结果

三组地址／数据宽度配置为 32／32、40／32、64／64。每组完成 2,048 笔写事务、8,192 笔读事务和 37 次复位，检查地址与数据不同到达次序、随机等待、字节使能、只读地址写入、输入在握手后变化、响应背压，以及只收到一个请求通道和响应等待期间的复位。事务记分板按接收的地址、数据和字节使能计算公开寄存器及读回值。

三组测试均通过。每组测试相对于参考提交增加 2,048 个周期，对应 2,048 笔已完成写事务。

32 位生产端口的独立 Xilinx 7 系列映射使用 108 个逻辑 LUT 和 139 个触发器，完整寄存器连接图的最长组合路径为 1 级。同参数参考实现使用 115 个逻辑 LUT、139 个触发器，最长组合路径为 2 级。完整 SoC 的跨模块路径由完整设计综合报告记录。

## 重复运行

```sh
python test/soc_control_commit/run.py --out build/soc_control_commit
python scripts/fpga/open_fpga_synth.py \
  --case-config build/soc_control_commit/cases.json \
  --cases reference current --out build/soc_control_commit_synthesis \
  --max-register-path-cells 10 --require-register-path-limit
```

`validation.json` 保存受测源码摘要、各组事务统计和独立综合结果。
