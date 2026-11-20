# DMA 描述符提前提供

DMA 使用 `direct_offer` 提供直发描述符的有效标志和字段，`direct_issue` 在前端就绪时表示实际接收事件。窗口队列在非空且没有待处理直发描述符时提前提供下一项字段，`win_frontend_valid` 继续决定该项描述符何时有效。队列深度、所有接收边沿、输出数据与完成周期保持一致。

## 形式验证

`equivalence.py` 从实际 RTL 提取接收条件和端口连接，对全部二进制输入位模式证明 `direct_issue`、前端接收事件和接收字段相同。验证同时使用实际 `conv_window_queue` 的有效条件，并逐字检查 DMA 的其他代码保持一致。四组参数覆盖 `IM2COL_SIZE=4/16/64`、2/6 位槽号和关闭卷积支持的配置，全部通过。

参考版本为 `151b87d5`，参考 DMA 源码 SHA-256 为 `d3736b7e3853d1cc1c94140aa58dadc5975126d9f8eb5d47fc7e3a67454796a5`，当前源码 SHA-256 为 `6730afb4940ed73d1b054f0cf3abe8185f4c4032ee4f076b34d960cb3faaef58`。

## 逐周期验证

`compare.py` 使用真实矩阵 DMA 和仲裁测试，比较全部 49 项公开输出，包括无效周期的数据字段，并比较 16 项 DMA 描述符状态与 14 项前端功能状态。32 位总线下的 `SIZE=4/8/16` 测试共完成 6,941 个周期，包含 14 项数值任务和 28 个矩阵描述符。

`window_compare.py` 在完整窗口 DMA 测试中同步运行当前和参考实例。24,913 个周期内，全部 49 项公开输出以及窗口队列的全部 401 位状态一致。检查覆盖四项在途容量、请求和响应重叠、随机坐标、响应背压、普通读取并发、错误响应、非法描述符、重配置及复位恢复。共接收 421 个窗口请求，完成 417 个请求，复位清除 4 个请求，核对 4,441 个数值元素和 19 个错误响应。

连续缓存命中测试包含 128 个请求和 512 次响应。当前与参考实例的最大响应间隔均为三个周期，首个响应至最后响应共 1,534 个周期。窗口字段提前提供的周期共 22,108 个。

完整窗口请求、响应、队列控制及每个存储槽的逐周期记录保存在 [window_cycles.csv.gz](window_cycles.csv.gz)。文件同时保存当前和参考值，连续编号覆盖全部 24,913 个周期。请求和响应采用端口顺序拼接的十六进制表示；队列控制字段依次为 `head`、`tail`、`count`、`active`、`failed`，每个槽依次为 `p0`、`q0`、`cols`、`tags`。

`frontend_backpressure.py` 在 `tile_ready=0` 时持续提供有效标志并改变描述符字段，同时保持所有实际接收的描述符相同。测试采用真实前端、缓存和预测器，比较全部 19 项公开输出及 16 项功能状态。生产接口参数 `LANES=4`、`BUS_WIDTH=64` 下，75 项数值任务共完成 508,498 个周期；控制专项完成 23 项检查和 134 个周期。共检查 505,463 个未就绪描述符周期，包含 81 个快速坐标条件有效的周期，输出、状态和错误行为全部一致。

## 独立综合

综合范围包含完整 DMA 描述符控制和窗口队列，五个下级模块作为接口边界。采用 Xilinx 7 系列映射，配置为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、`CONV_CACHE_SETS=128`。

| 资源 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 463 | 462 |
| 分布式存储 LUT | 76 | 76 |
| 触发器 | 134 | 134 |
| CARRY4 | 13 | 13 |

接口路径测量将下级模块端口作为观察端点，原始综合网表保持完整。

| 组合连接 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| `tile_ready` 到 `tile_p0/q0/rows/slot/group/valid` | 2 个单元 | 无组合连接 |
| `tile_ready` 到 `tile_cols` | 3 个单元 | 无组合连接 |
| `wr_last` 到 `tile_p0/q0/rows` | 4 个单元 | 无组合连接 |
| `wr_last` 到 `tile_cols` | 5 个单元 | 无组合连接 |
| `wr_last` 到 `tile_valid` | 4 个单元 | 4 个单元 |
| `linear.rd_finish_beat` 到 `tile_p0/q0/rows/slot/group/valid` | 5 个单元 | 4 个单元 |
| `linear.rd_finish_beat` 到 `tile_cols` | 5 个单元 | 5 个单元 |

完整参数、源码摘要、验证结果和实际连接路径保存在 [measurement.json](measurement.json)。完整 SoC 的物理 LUT 数量和时序由整机流程测量。

## 重复运行

```bash
python3 test/dma_direct_offer/equivalence.py --out build/dma_direct_offer/formal
python3 test/dma_direct_offer/compare.py --out build/dma_direct_offer/compare
python3 test/dma_direct_offer/window_compare.py --out build/dma_direct_offer/window
python3 test/dma_direct_offer/frontend_backpressure.py --out build/dma_direct_offer/backpressure
python3 test/dma_direct_offer/synthesis.py \
  --reference-ref 151b87d5 --out build/dma_direct_offer/reference_synthesis
python3 test/dma_direct_offer/synthesis.py --out build/dma_direct_offer/current_synthesis
```

仿真脚本的 `--verilator` 选项可指定外部 Verilator 可执行文件。综合和形式验证使用项目的 `open_fpga_synth.py` 及其 Python Yosys 运行环境。
