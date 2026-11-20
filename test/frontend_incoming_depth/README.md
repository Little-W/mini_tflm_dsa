# 前端接收条件与通道更新路径

固定参考提交为 `7ef39f0101ebf39184d11dbdc80a4042faee75c2`。
当前前端源码 SHA256 为 `00a4dc75a47cb1581272132ebf7de1c5cc083e4af2401cbfae56f7f33a2eeee0`。
本项仅修改 `rtl/npu/conv/conv_im2col_frontend.sv`，配置、存储容量、寄存阶段和接口周期保持一致。

## 当前设计

组范围判断将低位进位、高位大小关系及模加等式合并为一个 LUT6。高位加一等式使用 `add_equal` 的固定比较结构；`incoming_group_fits` 直接进入快速接收的最终 LUT，坐标资格和单行条件并行准备。

描述符当前组等值比较由已有分组比较结果共用。两个字地址等式使用固定比较结构，普通步长和换行步长的低两位进位分别计算，描述符只选择已经完成的进位结果。全部地址仍保持 32 位模加语义。

通道位置先计算流式推进和 Q 解码结果，再选择同周期接受的快速描述符。`tile_ready_context` 保存组合的独立就绪条件，配置有效直接参与最后的接收判断；相邻两个数据位共用一个 LUT6_2 完成最终选择。接收只能发生在空闲状态或流式最后一拍，这些周期的普通通道位置更新保持，因此接收选择可以位于末级。复位、错误返回及无效描述符的处理由任意输入证明覆盖。

## 形式检查

共 37 项检查全部通过。

- 29 项组合检查直接提取当前及参考源码，包含真实的 `ch0_q`、`cols_q`、`group_c` 上游运算、描述符比较及两个字地址等式。覆盖 `TILE_COUNT_W` 为 1、2、3、4、5、6、8、15、16、32，四种缓存策略、多个行宽，以及通用逻辑和官方 FPGA LUT 模型。
- 8 项通道检查比较全部 16 位下一值和相关握手输出。采用实际 `cfg_ready`、`tile_ready`、`wr_valid`、`wr_last` 表达式，对状态、保存字段、通道前值、复位及其他输入均不施加约束。覆盖 SIZE/LANES/BUS_WIDTH 为 16/4/64、1/1/32、3/2/64、32/8/128，分别验证通用逻辑和官方 FPGA 模型。
- 源码组成检查确认其他状态更新的代码保持一致。接收有效性、无效周期和非法状态编码均参与上述组合与下一值比较。

## 局部映射

两份模型均采用 `physical-cost`、最大 8 输入 LUT、6667 ps 目标及 300 ps 连线参数。路径按实际引脚依赖计算，LUT、MUXF7 和 CARRY4 均计入级数，映射的 ABC9 功能检查及依赖图完整性检查全部通过。

| 实际表达式范围 | 参考逻辑 LUT | 当前逻辑 LUT | 两版 FF | 参考最长路径 | 当前最长路径 |
|---|---:|---:|---:|---:|---:|
| DMA 描述符字段选择、完整组范围与字地址比较 | 317 | 250 | 448 | 13 | 9 |
| DMA 配置接受、前端就绪与通道位置下一值 | 169 | 145 | 261 | 8 | 10 |

第二份模型当前最长 10 级从本地 `q0[7]` 到通道下一值。目标配置路径和其他相关路径如下。

| 起点与终点 | 参考级数 | 当前级数 |
|---|---:|---:|
| `ch0_q` → `incoming_fast` | 8 | 6 |
| `group_c` → `incoming_fast` | 8 | 6 |
| `win_busy` → 当前返回字地址等式 | 12 | 8 |
| `win_busy` → `incoming_word_hit` | 13 | 9 |
| `cache_cfg_ready` → `ch_q` 下一值 | 7 | 4 |
| DMA `conv_cfg_valid` → `ch_q` 下一值 | 6 | 3 |
| 前端 `state` → `ch_q` 下一值 | 8 | 7 |

第一份模型采用 RW=5、TILE_COUNT_W=5、CACHE_POLICY=3；第二份模型采用 SIZE=16、LANES=4、BUS_WIDTH=64，并保留实际 DMA 的 `cfg_fire` 与 `conv_enable` 连接。表中的 FF 包含用于测量的输入和输出寄存器。两份模型分别统计各自范围的资源，完整 SoC 的物理 LUT 数量和全部路径由整合后的固定版本测量。

## FPGA 窗口比较

实际 `axi_block_dma_arbiter`、DMA、窗口队列、前端、缓存和预测器采用官方 FPGA 原语模型运行。窗口配置为 SIZE=16、DMA_SIZE=64、BUS_WIDTH=32、LANES=4、4 项窗口请求及 4 KiB 缓存。

参考和当前版本均完成 422 次请求，其中 418 次正常或错误完成、4 次由复位取消；4,457 项数据检查和 19 项错误结果一致。连续驻留窗口返回 512 拍、2,048 个元素，用时 1,534 周期，最大返回间隔为 3 周期。1,545 行驻留窗口记录逐字节相同，全部事务统计相同。

测试包括随机坐标和背压、普通与窗口请求同时到达、窗口授予撤销、中止、配置切换、总线错误排空、无效列数、错误后恢复及存在未完成请求时复位。

## 复现

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/frontend_incoming_depth/formal.py --out build/frontend_incoming_depth/results/formal
python3 test/frontend_incoming_depth/channel_formal.py --repo . --candidate rtl/npu/conv/conv_im2col_frontend.sv --out build/frontend_incoming_depth/results/channel_formal
python3 test/frontend_incoming_depth/synthesis.py --proof build/frontend_incoming_depth/results/formal --out build/frontend_incoming_depth/results/local --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/frontend_incoming_depth/channel_synthesis.py --proof build/frontend_incoming_depth/results/channel_formal --out build/frontend_incoming_depth/results/channel_local --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/frontend_incoming_depth/window.py --proof build/frontend_incoming_depth/results/formal/summary.json --out build/frontend_incoming_depth/results/window --verilator verilator-modern
python3 test/frontend_incoming_depth/collect_report.py --results build/frontend_incoming_depth/results
```

`measurement.json` 保存固定源码、形式检查、网表、工具脚本和窗口模型的 SHA256，以及当前测量结果。
