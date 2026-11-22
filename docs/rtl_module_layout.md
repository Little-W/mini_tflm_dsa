# NPU 模块组织与流水信号

## 文件组织

设计源文件分别定义一个模块或一个 package。NPU 源文件按实际职责划分，物理行数包括端口、注释、空行和模块主体，最长文件为 1,488 行。

| 文件 | 职责 | 行数 |
| --- | --- | ---: |
| `rtl/npu/top/npu_top.sv` | 任务接收、矩阵与向量选择、共享接口和完成状态 | 1,483 |
| `rtl/npu/top/npu_task_configuration.sv` | 配置流水、容量计算、输出分组与资源预留 | 1,004 |
| `rtl/npu/top/npu_matrix_engine.sv` | 帧调度、操作数加载和阵列计算 | 1,382 |
| `rtl/npu/top/npu_output_pipeline.sv` | 偏置分组、量化、输出 FIFO 和写回请求 | 585 |
| `rtl/npu/top/npu_operand_cache_bridge.sv` | 操作数缓存的任务范围和读取接口 | 177 |
| `rtl/npu/conv/conv_im2col_frontend.sv` | 前端接口、任务状态与子模块连接 | 1,486 |
| `rtl/npu/conv/conv_im2col_geometry.sv` | 配置几何、边界及地址步长计算 | 1,021 |
| `rtl/npu/conv/conv_im2col_descriptor.sv` | 窗口描述符及相关状态 | 1,254 |
| `rtl/npu/conv/conv_im2col_stream.sv` | 输出数据流、窗口位置和接收状态 | 1,156 |
| `rtl/npu/conv/conv_im2col_prefetch.sv` | 预取位置、通道及有效条件 | 473 |
| `rtl/npu/conv/conv_im2col_frontend_pkg.sv` | 前端状态类型和公共定义 | 28 |
| `rtl/npu/conv/vector_engine.sv` | 向量算术、结果槽位和写回组装 | 1,488 |
| `rtl/npu/conv/vector_engine_control.sv` | 任务状态、循环位置、计算阶段和错误排空 | 1,102 |
| `rtl/npu/conv/vector_engine_address.sv` | 坐标、窗口请求、DMA 地址和范围检查 | 1,208 |
| `rtl/npu/conv/vector_engine_operand_store.sv` | 输入、权重、偏置、量化参数和累加结果存储 | 986 |
| `rtl/npu/conv/vector_engine_control_pkg.sv` | 向量状态类型和状态资格函数 | 39 |
| `rtl/npu/dma/cache/conv_windowed_cache.sv` | 窗口缓存请求、替换、回填和响应 | 1,423 |
| `rtl/npu/dma/cache/conv_cache_metadata_way.sv` | 每路缓存元数据的存储与读写 | 382 |
| `rtl/npu/writeback/vec_requant.sv` | 量化参数访问、输入顺序、分时计算和输出组装 | 1,303 |
| `rtl/npu/control/ps_window_scheduler.sv` | 帧命令调度、存储预留和位置预测流水 | 798 |
| `rtl/npu/buffers/ps_buffer_wide_fifo.sv` | 帧数据保存、长度队列和同步回放 | 212 |
| `rtl/npu/writeback/vec_s8_to_fifo_linear.sv` | 八位行向量保存和线性总线输出 | 231 |
| `rtl/npu/writeback/vec_s8_fifo_row_ram.sv` | 输出 FIFO 的同步行存储接口 | 53 |
| `rtl/npu/ps_compact/ps_raw_address.sv` | 线性位置的常量除法商和余数 | 26 |

每个子模块拥有明确的状态和运算职责。模块接口使用具名连接，新增接口的输入、输出及实例边界信号分别使用 `i_`、`o_` 和实例名称前缀。组合与时序逻辑采用 `assign`、`always_comb` 和 `always_ff`，接口明确描述位宽、符号和数组维度。

## 流水信号数组

同一字段在连续阶段中的保存值使用一个数组，数组下标表示阶段。阶段控制向量、数据数组与批次编号共同推进；每个元素的更新使能和复位条件由其所在阶段决定。横纵坐标使用按轴索引的数组，具体含义见表中说明。

| 所属模块 | 数组示例 | 含义 |
| --- | --- | --- |
| `requant_compute_lane` | `amount_q[p_amount_stages]`、`valid_q`、`lane_enable_q` | 移位参数、有效状态和尾部通道掩码 |
| `vec_requant` | `batch_pipe_q` | 分时计算批次编号 |
| `npu_task_configuration` | `cfg_mode_q[0:2]`、`cfg_k_q[0:2]`、`cfg_m_q[0:2]`、`o_cfg_n_q[0:2]` | 三个配置阶段中的模式和矩阵尺寸 |
| `npu_matrix_engine` | `base_q[3]`、`offset_q[2]`、`packed_q[2]`、`wide_q[2]` | 权重预取各阶段的地址与格式 |
| `ps_window_scheduler` | `prediction_depth_q[3]`、`prediction_column_q[3]` | 三个预测阶段的深度位置和列位置 |
| `ps_window_scheduler` | `prediction_reads_frame_q[2]` | 请求接收、帧选择两个阶段的元数据读取条件 |
| `vector_engine` | `q_right[3]`、`q_index[7]` | 本地量化的移位参数和输出元素编号 |
| `conv_im2col_prefetch` | `channel_q[3]`、`reference_retire_q[2]`、`epoch_q[2]` | 预取通道、缓存释放计数和任务编号 |
| `conv_im2col_prefetch` | `accepted_coordinate_q[2]`、`projected_coordinate_q[2]`、`output_coordinate_q[2]` | 各上下文的横纵坐标，下标 0、1 分别表示横轴、纵轴 |

算术中间结果的位宽或数值含义不同时分别声明，例如有符号乘积、移位后的商和舍入结果。这样可以直接检查截断位置、符号扩展和进位处理。

## 量化运算

矩阵结果经 `npu_output_pipeline.u_vec_requant` 进入 `requant_compute_lane`。逐张量参数广播至各通道，逐通道参数按元素索引读取，INT8 与 INT16 由模式输入选择。控制、存储、通用乘法和移位分别使用独立文件。

该单通道量化流水线为七个使能边沿：乘法三个阶段、移位两个阶段、舍入与偏移一个阶段、裁剪与输出一个阶段。生产矩阵路径使用两个算术通道分时处理 16 个元素，并保留 512 行输入容量。

向量 DW 仅在 `SHARED_QUANT_ENABLE=1` 时通过 `quant_req_*` 接口进入同一个 `vec_requant` 实例；顶层要求 `REQUANT_COMPUTE_LANES == SIZE` 才启用该方式。在两个矩阵量化通道的配置中，DW 复用向量引擎本地的 `vector_scalar_multiplier` 和 `vector_round_shift`，并由 `q_right`、`q_index` 和 `q_valid` 保存流水状态。`ADD_S8`、`AVGPOOL_S8` 和 `SOFTMAX_S8` 也按各自算法复用本地标量运算资源。详细接口和数值语义见 [统一量化运算](unified_requant.md)。

## 构建与检查

ASIC、Verilator、Makefile 和 Vivado 入口使用完整子模块清单，package 位于消费者之前。`scripts/rtl/source_files.py` 为局部测试解析工程内的模块依赖。

```bash
python3 test/rtl_layout/check.py --out build/rtl_layout
python3 test/fpga_integration/run.py --out build/fpga_integration --verilator verilator --jobs 1
python3 test/asic_integration/run.py --out build/asic_integration --verilator verilator --jobs 1
```

文件组织检查覆盖模块与文件名称、重复定义、NPU 文件长度、资源选择标志、显式 FPGA 原语和生产入口依赖。独立 PicoRV32 主核源文件为 2,201 行，其辅助模块分别使用独立文件。
