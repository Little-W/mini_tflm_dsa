# DMA 接收资源与仲裁授予

`axi_dual_block_dma` 使用 `rd_resource_ready` 输出当前命令需要的资源是否可用，
`rd_start_ready` 同时检查配置请求。图像命令继续检查活动命令、保存命令、线性读取和窗口队列；
线性命令同时检查前端及实际 AXI 读取是否已排空。

`axi_block_dma_arbiter` 在选择下一请求方时统一检查配置有效信号，并使用独立的资源条件。
保存的授予编号无需再经过配置有效计算和 DMA 接收资格后返回授予寄存器。
请求优先顺序、命令接收边沿、取消处理和完成标签保持一致。

## 验证

`check.py` 提取两个生产模块的实际表达式，执行以下比较：

- DMA 图像与线性命令接收资格的任意输入形式证明及 270,336 次四态比较。
- 32、64、128 位总线，量化请求方开启和关闭，以及通用实现，共 7 组完整仲裁状态比较。
- 完整仲裁器的 15,388 个状态和接口比较点全部通过。DMA 接收资格按实际配置表达式连接，
  其余 DMA 返回信号及所有外部输入不受限制。
- 自动核对仲裁模块其余功能代码，确认资源资格只影响已包含配置检查的后续授予选择。

真实 RTL 仿真使用 Verilator 5.054：32、64 位取消与反压测试各通过 21 项场景和 1,069 次检查，
分别覆盖 15 次描述符取消、5 次同时释放和 5 次授予撤销。普通命令的最小接收间隔为 2 周期。
SIZE 为 4 和 16 的图像 DMA 测试各完成 14 个描述符、7 个任务，分别比较 159 和 2,163 个元素，
覆盖填充、归约尾部、读取错误、非法描述符及矩阵/图像命令切换。

## 组合路径

`measure.py` 从生产代码提取完整资源资格、请求优先选择和授予更新，将全部输入及输出寄存。
同一 Xilinx 映射设置下，连接逻辑为 27 个 LUT，完整组合路径最长 7 级；
授予状态到下一授予状态的路径由 7 级缩短为 5 级。整颗 SoC 单独测量跨模块连接与器件时序。

```bash
python test/dma_resource_ready/check.py --out build/dma_resource_ready/formal
python test/dma_resource_ready/measure.py --out build/dma_resource_ready/mapping
python test/dma_abort/run_read_arbiter.py --bus-width 32 --out build/dma_resource_ready/abort32
python test/dma_abort/run_read_arbiter.py --bus-width 64 --out build/dma_resource_ready/abort64
python test/conv_dma/run.py --sizes 4 16 --out build/dma_resource_ready/conv_dma
```

`validation.json` 保存源码摘要、形式比较、数值测试和完整映射结果。
