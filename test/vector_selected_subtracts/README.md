# 地址与坐标差值的并行分段算术

向量参数行跨度、帧调度剩余列数、预取坐标差值及历史位置差值采用两段普通算术与并行高位进位修正。实例继续计算原有宽度的全部结果和最高进位，输入进位固定为一，输入反码的含义保持不变。`p_preserve_grouped_unknowns` 保留含未知值和高阻态输入的原分组四态传播。

| 调用实例 | 结果宽度 | 低段宽度 | 高段宽度 |
|---|---:|---:|---:|
| `vector_engine_address.u_parameter_stride` | 32 | 16 | 16 |
| `ps_window_scheduler.u_remaining_columns`，`SIZE=16` | 29 | 16 | 13 |
| `conv_next_use_predictor.g_coordinate_difference[*].u_difference` | 34 | 20 | 14 |
| `conv_im2col_geometry.u_history_delta` | 33 | 17 | 16 |

## 功能验证

```sh
python3 test/parallel_prefix_grouped_unknowns/run.py --out build/parallel_prefix_grouped_unknowns
python3 test/vector_selected_subtracts/run_formal.py --out build/vector_selected_subtracts
```

父模块验证比较全部公开输出，并使用时序归纳检查内部状态关系。输入不附加数值或握手限制。普通编译和 `SYNTHESIS` 编译分别覆盖六种配置：完整向量地址模块、两种复用容量的帧调度器、完整坐标预测器，以及二通道和八通道的卷积几何模块。十二项完整模块证明与通用算术的四十二项证明、344064 次四态比较共同检查数值和状态行为。

## 完整父模块资源测量

测量采用 Xilinx 7 系列、6667 ps 延迟目标、300 ps 连线代价与最多 8 输入逻辑分解。

| 完整模块 | 分组算术逻辑 LUT | 分段算术逻辑 LUT | 减少数量 | 新增 DSP |
|---|---:|---:|---:|---:|
| `vector_engine_address` | 1849 | 1827 | 22 | 1 |
| `ps_window_scheduler` | 1852 | 1819 | 33 | 1 |
| `conv_next_use_predictor` | 1902 | 1784 | 118 | 2 |
| `conv_im2col_geometry` | 3069 | 2989 | 80 | 1 |

向量地址模块使用 16 个向量通道、8 个计算单元、64 位总线、8 个窗口通道、共享量化与共享存储，并启用寄存读取阶段。调度器使用 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=0`，几何模块使用 `p_lanes=2`，其余参数使用模块默认值。

以上独立完整模块合计减少 253 个逻辑 LUT，FF、LUTRAM、BRAM、接口周期和存储容量保持相同。整机资源结果由集成后的固定源码和相同映射设置确定。各模块原有的其他组合路径继续由整机时序分析检查。
