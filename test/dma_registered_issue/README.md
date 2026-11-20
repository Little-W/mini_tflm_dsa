# 普通 im2col 描述符的寄存启动

普通 im2col 命令在 DMA 接收边沿保存 `p0`、`q0`、`group`、行数、列数、槽编号和标签。合法命令置位 `conv_pending`，前端在后续就绪边沿接收保存的描述符。前端请求的字段与有效标志均由寄存状态产生。

前端在命令接收时已经就绪的情况下，前端接收边沿比 DMA 接收边沿晚一个周期。前端繁忙时，描述符持续等待就绪。DMA 接收之后的中止保持已接受事务的执行和排空行为；复位取消在途事务。非法行数的命令通过原有完成状态报告一次错误。

窗口队列仍提前提供下一项字段。窗口返回完成和新请求接收可以连续执行，普通命令与窗口队列使用各自的有效状态。

## 资源与接口组合路径

配置为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、`CONV_CACHE_SETS=128`。测量对象包括完整 `axi_dual_block_dma` 控制和 `conv_window_queue`；线性 DMA、im2col 前端、读取保护器、写入保护器和读取复用器以其实际端口作为模块边界。

| 指标 | 接收周期可直接启动的实现 | 寄存启动实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 462 | 417 |
| 分布式 RAM LUT | 76 | 76 |
| 触发器 | 134 | 134 |
| `rd_finish_beat` 至前端描述符及 `tile_valid` | 存在组合连接 | 无组合连接 |
| 前端 `tile_ready` 至描述符及 `tile_valid` | 无组合连接 | 无组合连接 |

两次综合使用相同脚本和参数，参考提交为 `ed458cee`。完整 SoC 的寄存器间路径由整机综合单独测量。

## 功能检查

实际 FPGA 分支使用官方 `LUT`、`MUXF`、`DSP48E1` 功能模型，C++ 驱动同时启用未定义行为检查。三个配置各完成 158 个场景、159 次命令接收、158 次完成、1 次复位取消，以及 10,250 次矩阵数值检查。151 个合法前端请求均在描述符接收后的下一周期启动。

| 配置 | 观察周期 | 矩阵数值检查 | 结果 |
| --- | ---: | ---: | --- |
| BUS64，64 个槽 | 18,790 | 10,250 | 通过 |
| BUS32，64 个槽 | 18,847 | 10,250 | 通过 |
| BUS64，1 个槽 | 18,790 | 10,250 | 通过 |

检查覆盖接收后输入立即变化、非对齐地址、4 KiB 边界、AXI 地址和数据停顿、启动等待期间中止、最后数据拍中止、复位后重新配置、错误响应、非法描述符、连续普通命令、线性与 im2col 交替使用，以及线性最后返回拍与新 im2col 命令同时接收。

窗口检查比较全部 49 个公开输出和完整 401 位队列状态，共 24,913 个周期。421 个窗口请求中，417 个完成、4 个被复位取消；检查 4,441 个元素及 19 次错误结果。连续命中场景的 128 个请求返回 512 拍和 2,048 个元素，最大返回间隔为 3 个周期，观察区间为 1,534 个周期，与参考实例相同。

矩阵 DMA 的 4 列和 16 列配置各完成 14 个描述符，分别检查 159 和 2,163 个元素。两个线性 DMA 原有测试通过。BUS32 和 BUS64 的读取仲裁中止测试各通过 21 个场景和 905 次检查，覆盖 15 个取消描述符、5 次同时释放及后续命令恢复。

`measurement.json` 保存全部测量结果、源码摘要、综合网表摘要、程序摘要和命令。普通命令增加一个启动寄存周期，使用事务顺序与数值检查；窗口接口使用逐周期比较。

## 复现

```sh
python3 test/dma_registered_issue/run.py --bus-width 64 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/control64
python3 test/dma_registered_issue/run.py --bus-width 32 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/control32
python3 test/dma_registered_issue/run.py --bus-width 64 --cache-blocks 1 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/control64_slot1
python3 test/dma_registered_issue/window_compare.py \
  --reference-ref ed458cee --verilator "$VERILATOR_BIN" \
  --out build/dma_registered_issue/window_compare
python3 test/conv_dma/run.py --sizes 4 16 --jobs 1 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/matrix
python3 test/conv_dma/run.py --legacy-only --jobs 1 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/legacy
python3 test/dma_abort/run_read_arbiter.py --bus-width 32 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/arbiter32
python3 test/dma_abort/run_read_arbiter.py --bus-width 64 \
  --verilator "$VERILATOR_BIN" --out build/dma_registered_issue/arbiter64
python3 test/dma_direct_offer/synthesis.py --reference-ref ed458cee \
  --out build/dma_registered_issue/synthesis/reference
python3 test/dma_direct_offer/synthesis.py \
  --out build/dma_registered_issue/synthesis/current
```
