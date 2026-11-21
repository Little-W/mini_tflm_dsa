# 生产 DMA 的数据排列性质

`BUS_WIDTH=64`、`DATA_WIDTH=16` 时，实际 `axi_dual_block_dma` 在第一次复位采样之后的每个周期满足以下关系，包括输出无效的周期：

1. `wr_use_16bits=0` 时，`wr_col_base[2:0]=0`。
2. 线性 S16 读取每拍最多输出四个有效通道。
3. `WINDOW_LANES=4` 的 im2col 每拍最多输出四个有效通道；`WINDOW_LANES=8` 的宽 im2col 可以在任意列起点输出八个有效通道。

生产配置使用 `SIZE=64`、`IM2COL_SIZE=16` 和 `WINDOW_LANES=8`，输入激活端保留列起点低四位。`SIZE=16` 和 `WINDOW_LANES=4` 的独立配置也参与检查。输入激活缓存的八通道排列支持全部十六种列起点，保留非窗口 im2col 的逐列及不等长度通道输出。

## 证明范围

`prove.py` 直接读取当前 `axi_dual_block_dma`、`axi_linear_block_dma`、`regfile` 和 `add_equal`。测试副本只增加四个性质观察结果，其中两个观察实际双模式输出，另外两个观察线性引擎对应的不变量。RTL 文件保持原有功能。

前端、窗口队列、读写保护器和读选择器保留真实端口定义，其输出由每个周期独立、任意的布尔向量驱动。该处理扩大这些模块可能产生的输出集合，因此性质覆盖它们的全部可达状态及错误、复位、窗口、非窗口行为。证明不使用这些模块的内部状态或协议不变量，也不在输入激活缓存处假设数据排列。

所有寄存器在第一个采样时钟之前取任意确定值，只在第一个采样时钟令 `rst_n=0`，后续复位、命令、地址、格式、有效标志、总线数据与错误响应均可任意变化。两周期检查证明复位后的初始性质，一步时间归纳证明四个性质共同保持，得到无界结果。

## 运行

```sh
python3 test/dma_source_layout/prove.py \
  --sizes 16 64 --window-lanes 4 8 --out /tmp/dma_source_layout
```

四种配置执行复位起始检查和一步归纳。`measurement.json` 包含配置、原始源码及测试副本的 SHA-256、性质、外部输入条件和日志摘要。

## 八通道缓存写入排列

```sh
python3 test/dma_source_layout/cache_layout_formal.py \
  --out /tmp/cache_layout_formal
```

该证明提取 `ia_loader_cache_mgr` 实际的紧凑字节与宽数据排列表达式，与完整行移位进行组合 SAT 比较。128 位宽输入、64 位紧凑输入及四位列起点均不受约束，覆盖全部十六种起点与八个输入通道。越过第十五列的元素按行宽截断，保存的写掩码决定每个字节是否写入。

`test/ia_shared/receive_write_tb.sv` 进一步对实际模块执行 65,536 个字节/偏移组合和 20,000 个随机写周期，检查任意列起点、两种存储格式、完整八通道掩码、寄存写命令及共享存储写数据。
