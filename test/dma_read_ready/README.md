# DMA 读取模式与返回就绪选择

## 实现

`axi_dual_block_dma` 在 `cfg_fire` 边沿保存 `job_read_guard`。其值为受支持的卷积使能与范围保护使能的逻辑或。读取保护器和读取请求复用器直接使用该寄存位；`job_conv` 继续用于卷积控制。配置接收边沿和模式生效周期保持一致。

`conv_axi_read_guard` 并行计算单字返回、整段返回与直通返回的就绪条件。FPGA 实现用一个 `LUT6_2` 完成最终选择，通用实现保留相同的布尔关系。支持和关闭 GEMM 跨页拆分的两种配置均保持完整行为。输入状态和模式不会经过串行条件选择后才到达 AXI 返回就绪端口。

## 联合测量

测量从生产 `axi_dual_block_dma` 中提取实际模式寄存表达式、读取保护器实例和读取复用器实例，使用完整实际模块进行联合综合。保留全部 AXI 端口和供其他 DMA 消费者使用的 `job_conv`，参数为 32 位地址、64 位数据及四个读取在途事务。参考提交为 `414099fa`。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT 原语 | 923 | 920 |
| 触发器 | 399 | 399 |
| DSP48E1 | 0 | 0 |
| RAMB18E1 / RAMB36E1 | 0 / 0 | 0 / 0 |
| 最长寄存器间组合路径 | 10 级 | 10 级 |
| 任务模式至 AXI `m_axi_rready` | 5 级 | 2 级 |
| 任意寄存器至 AXI `m_axi_rready` | 5 级 | 2 级 |
| 任务模式至 AXI 错误接收条件 | 6 级 | 3 级 |
| 任意寄存器至 AXI 错误接收条件 | 6 级 | 3 级 |

错误接收条件为 `m_axi_rvalid && m_axi_rready && m_axi_rresp[1]`。端口路径仅增加分析终点，资源统计取原始网表。完整 SoC 的跨模块路径和物理 LUT 数由相应整机测量报告提供。

## 形式与数值验证

模式控制证明直接使用生产 DMA 的完整描述符时序控制块，并比较所有共有寄存状态和读取保护使能关系。卷积支持开启、关闭两种配置均通过，外部输入未增加取值限制。脚本另确认双路 DMA 的其余内容保持相同。

真实读取保护器与读取复用器在 BUS32、BUS64 下完成 FPGA 分支的完整状态和输出等价比较。独立读取保护器完成七组参数检查，覆盖两种跨页拆分设置、16/32/33/40 位地址和 16/32/64/128/256 位数据。复位、配置、模式、地址、数据、错误返回和反压输入均参与比较。

FPGA 实际逐周期测试覆盖 BUS32/BUS64 与两种跨页拆分设置，共四组配置，每组 50,000 个周期，全部公开输出一致。

完整窗口 DMA 的 FPGA 事务测试在当前实现和参考版本分别通过 422 次接收、418 次完成、4 次复位取消、4,457 个返回元素和 19 次错误处理。测试覆盖连续命中、普通请求与窗口请求并发、寄存授予撤销、随机坐标、输出反压、错误排空与恢复、无效描述符、边界配置接收及运行中复位。两份连续命中周期记录共 1,545 行，内容逐项相同。

既有 im2col 完成归属检查也已复跑。该检查保留原环境条件：卷积事务活动期间不会收到线性事务完成事件。生产模式和返回就绪的等价检查不使用该条件。

`measurement.json` 保存生产源码、输入快照、形式结果、数值结果和综合网表的 SHA-256。

## 运行

```sh
python3 test/dma_read_ready/run_formal.py \
  --reference 414099fa --out build/dma_read_ready/formal
python3 test/conv_guard/run_control_formal.py \
  --reference-ref 414099fa --fpga --out build/dma_read_ready/guard_formal
python3 test/conv_guard/compare.py --reference-ref 414099fa --fpga \
  --verilator verilator-modern --out build/dma_read_ready/guard_numeric
python3 test/kernel_pending_counts/run_formal.py --reference 8d7dc595 \
  --groups image --out build/dma_read_ready/image_owner
python3 test/window_dma/run.py --fpga --jobs 1 --reference-ref 414099fa \
  --verilator verilator-modern --out build/dma_read_ready/window_numeric

python3 test/dma_read_ready/prepare_measurement.py \
  --reference 414099fa --out build/dma_read_ready/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/dma_read_ready/inputs/cases.json \
  --cases reference current --out build/dma_read_ready/synthesis
python3 test/dma_read_ready/measure_paths.py \
  --synthesis build/dma_read_ready/synthesis --out build/dma_read_ready/paths.json
```
