# 线性 DMA 行末状态

`axi_linear_block_dma` 在更新写拍计数的同一时钟边沿，保存当前拍是否为跨字行末拍。计数递增时，下一拍的跨字行末条件直接使用本拍的普通行末比较结果；复位、接收新命令、结束一行和空闲清零时同时保存对应条件。

写入数据、字节使能、握手、完成和错误输出保持逐周期一致。该结构增加一个状态位，不增加命令准备周期或数据传输周期。输入包含未知值时，下一状态使用完整定宽加法与相等比较。

## 验证

`run.py` 比较完整 DMA 模块。五组参数分别采用普通编译和 FPGA 综合编译条件，检查全部公开输出、匹配的内部状态以及行末状态与拍计数的关系。功能输入不施加限制。两种编译条件另各执行 32,202 个四态周期，包含未知控制、数据和复位。

四态刺激覆盖全部 429 位功能输入，每个输入位均独立经历 0、1、X、Z。两种编译条件各完成一笔读取、三笔写入、六个物理写地址、十四个写数据拍、四次普通行结束、两次跨字行结束和一次中止，握手及完成事件均独立计数。仿真副本将嵌套 packed 字段先赋给同位宽中间线，再执行原范围的位选择；数据位序及四态值保持一致。

事务检查覆盖 64 位 AXI、一个或四个未完成写事务、固定延迟和随机阻塞。四种组合各运行 276 条命令、1,919 个物理突发和 103,590 个总线数据拍。中止与恢复检查覆盖 24 种并发读写、错误响应、等待数据保持、准备阶段中止、复位和恢复场景。结果均通过。

## 独立综合

测量参数为 `SIZE=16`、`BUS_WIDTH=64`、`READ_OUTSTANDING=4`、`WRITE_OUTSTANDING=4`。源文件散列值、映射配置、完整验证结果及输出路径保存在 `validation.json`。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,400 | 1,392 |
| 触发器 | 762 | 763 |
| 完整寄存器间最长组合级数 | 10 | 10 |
| 寄存器到 `src_wready` 的组合级数 | 4 | 3 |
| 寄存器到 `m_axi_wvalid` 的组合级数 | 4 | 3 |

输出路径统计在公开输出处设置分析终点，路径包括其上游所有组合单元。150 MHz 的器件时序需要使用布局布线后的延迟进行检查。

```bash
python3 test/linear_dma_row_finish/run.py --out build/linear_dma_row_finish
python3 test/linear_dma_row_finish/run.py --section four_state --out build/linear_dma_row_four_state
python3 test/linear_dma_write_4k/run.py --fpga --bus-width 64 \
  --outstanding 1 4 --out build/linear_dma_row_write
python3 test/dma_abort_boundary/run.py --fpga --bus-width 64 \
  --size 16 --dma-size 16 --data-width 16 --outstanding 4 \
  --prepare-abort --out build/linear_dma_row_abort
```
