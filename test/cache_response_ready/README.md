# 缓存响应队列的寄存分隔

多项请求队列将每个完成结果写入已有响应队列。预读在正式接收之前同步读取标签和数据，正式请求的完整地址、组号和快照条件匹配后，将命中数据及错误状态保存到响应队列。返回数据和有效信号由保存的队列状态产生。

响应队列同时支持出队和入队。持续预读命中流每个周期接收一项正式请求，并每个周期返回一项结果；每项命中结果在接收后的一个周期返回。反压期间，响应顺序、数据和错误标志保持稳定。实际 SoC 继续使用两项队列，容量及外部端口保持原有定义。

## 正确性与性能检查

完整缓存与既有寄存预读版本 `0d437ded9299a7ad5ab70f30884b5344399d4d22` 做逐周期比较，覆盖全部公开输出和共有保存状态。参数包含请求深度 1、2、4，以及实际 SoC 的 16 组、2 路、128 字节缓存行、64 位总线和两项请求队列。预读开启和关闭均分别检查 generic 与 FPGA 宏模式，输入不增加约束。

```sh
python3 test/cache_queued_preview/check_parent.py --preview 1 --jobs 1   --out build/cache_response_ready/parent
python3 test/cache_queued_preview/check_parent.py --preview 0 --jobs 1   --out build/cache_response_ready/preview_off
python3 test/cache_queued_preview/check_properties.py   --out build/cache_response_ready/properties
python3 test/cache_response_ready/check_return.py   --out build/cache_response_ready/return
```

`check_properties.py` 从真实复位状态证明预读地址身份、正式接收资格及响应队列相关的十四项性质。返回过程测试从生产代码和参考代码提取组合过程，比较每个数据位、有效信号、错误信号、成功及失败资格、响应队列写入事件。四态输入宽度由参数显式计算，并检查有效返回、错误返回和入队事件的实际覆盖次数。

协议和数值检查使用 Verilator 5.054：

```sh
python3 test/cache_pipeline/run_queued_preview.py --no-direct-response   --mode fpga --cache-sets 16 --depth 2 --read-width 64 --jobs 1   --out build/cache_response_ready/protocol
python3 test/frontend_pipeline/run_numeric.py --target fpga   --cache-response-depth 2 --size 16 --lanes 8 --bus-width 64   --cache-sets 16 --cache-ways 2 --line-bytes 128 --narrow-mode 2   --windowed --prefetch --out build/cache_response_ready/numeric
```

实际配置的 26 项协议场景通过，包括连续预读、每周期接收与返回、随机反压、响应保持、取消、重新配置、地址及组号不匹配、越界和同步读写冲突。前端的 42 项独立方程数值检查和 1024 组配置检查通过。

相同前端版本 `51f725d020a390aeda7d1f79af3a1f19e9e161b6` 的参考运行是 140765 周期，寄存返回运行是 144428 周期，增加 3663 周期，约 2.60%。两次运行使用相同参数、测试向量与 Verilator 版本。

## 完整连接分析

```sh
python3 test/cache_response_ready/measure.py   --out build/cache_response_ready/mapping
python3 test/cache_response_ready/measure.py --dma   --out build/cache_response_ready/dma_mapping
```

缓存映射保留全部端口和内部寄存器。分析图可为返回端口添加观察寄存器，检查就绪信号及保存计数到输出的实际连接，资源统计使用原始网表。`--dma` 包含窗口队列、完整图像前端、缓存及输出保存寄存器。

以 `51f725d0` 的完整 8 通道前端为基础，寄存返回后的映射为 15827 个逻辑 LUT，最长组合路径为 15 级。预读地址匹配到前端请求接收的路径由响应队列寄存器分隔；该版本最长路径来自描述符地址运算和准备数据字的比较。完整 SoC 的时序与资源需结合后续前端优化测量。

`validation.json` 保存源码、证明、仿真和映射报告的校验值。映射采用 6667 ps 目标周期和 300 ps 线延迟模型；150 MHz 的器件时序使用布局布线报告确认。
