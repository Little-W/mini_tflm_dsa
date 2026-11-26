# NPU 模块组织与流水信号

## 文件组织

设计源文件分别定义一个模块或一个 package。NPU 源文件按实际职责划分，物理行数包括端口、注释、空行和模块主体，最长 NPU 文件为 1,500 行。

| 文件 | 职责 | 行数 |
| --- | --- | ---: |
| `rtl/npu/top/npu_top.sv` | 任务接收、矩阵与向量选择、共享接口和完成状态 | 1,488 |
| `rtl/npu/top/npu_task_configuration.sv` | 配置流水、容量计算、输出分组与资源预留 | 990 |
| `rtl/npu/top/npu_matrix_engine.sv` | 帧调度、操作数加载和阵列计算 | 1,384 |
| `rtl/npu/top/npu_output_pipeline.sv` | 偏置分组、量化、输出 FIFO 和写回请求 | 620 |
| `rtl/npu/top/npu_operand_cache_bridge.sv` | 操作数缓存的任务范围和读取接口 | 177 |
| `rtl/npu/conv/conv_im2col_frontend.sv` | 前端接口、任务状态与子模块连接 | 1,485 |
| `rtl/npu/conv/conv_im2col_geometry.sv` | 配置几何、边界及地址步长计算 | 1,406 |
| `rtl/npu/conv/conv_im2col_descriptor.sv` | 窗口描述符及相关状态 | 1,500 |
| `rtl/npu/conv/conv_im2col_stream.sv` | 输出数据流、窗口位置和接收状态 | 1,496 |
| `rtl/npu/conv/conv_im2col_prefetch.sv` | 预取位置、通道及有效条件 | 473 |
| `rtl/npu/conv/conv_im2col_frontend_pkg.sv` | 前端状态类型和公共定义 | 32 |
| `rtl/npu/conv/vector_engine.sv` | 向量算术、结果槽位和写回组装 | 1,492 |
| `rtl/npu/conv/vector_engine_control.sv` | 任务状态、循环位置、计算阶段和错误排空 | 1,120 |
| `rtl/npu/conv/vector_engine_address.sv` | 坐标、窗口请求、DMA 地址和范围检查 | 1,222 |
| `rtl/npu/conv/vector_engine_operand_store.sv` | 输入、权重、偏置、量化参数和累加结果存储 | 1,031 |
| `rtl/npu/conv/vector_engine_control_pkg.sv` | 向量状态类型和状态资格函数 | 55 |
| `rtl/npu/dma/cache/conv_windowed_cache.sv` | 窗口缓存请求、替换、回填和响应 | 1,430 |
| `rtl/npu/dma/cache/conv_cache_metadata_way.sv` | 每路缓存元数据的存储与读写 | 479 |
| `rtl/npu/writeback/vec_requant.sv` | 量化参数访问、输入顺序、分时计算和输出组装 | 1,354 |
| `rtl/npu/control/ps_window_scheduler.sv` | 帧命令调度、存储预留和位置预测流水 | 798 |
| `rtl/npu/buffers/ps_buffer_wide_fifo.sv` | 帧数据保存、长度队列和同步回放 | 212 |
| `rtl/npu/writeback/vec_s8_to_fifo_linear.sv` | 八位行向量保存和线性总线输出 | 231 |
| `rtl/npu/writeback/vec_s8_fifo_row_ram.sv` | 输出 FIFO 的同步行存储接口 | 53 |
| `rtl/npu/ps_compact/ps_raw_address.sv` | 线性位置的常量除法商和余数 | 27 |

每个子模块拥有明确的状态和运算职责。模块接口使用具名连接，新增接口的输入、输出及实例边界信号分别使用 `i_`、`o_` 和实例名称前缀。组合与时序逻辑采用 `assign`、`always_comb` 和 `always_ff`，接口明确描述位宽、符号和数组维度。

## 分层结构

顶层保存任务边界及共享接口，子模块分别拥有配置、运行状态、存储接口和数据运算，小模块实现独立比较、加法、选择与格式转换。每个 RTL 文件只定义一个模块或一个 package；公共算术模块也按这个规则组织。

| 上层模块 | 主要子模块 | 职责划分 |
| --- | --- | --- |
| `npu_top` | `npu_task_configuration`、`npu_matrix_engine`、`vector_engine` | 配置接收、矩阵计算和向量计算 |
| `conv_im2col_frontend` | `conv_im2col_geometry`、`conv_im2col_descriptor`、`conv_im2col_stream` | 配置几何、描述符准备和输入数据流 |
| `conv_im2col_frontend` | `conv_im2col_runtime_registers`、`conv_im2col_state_control`、`conv_im2col_request_index` | 运行寄存器、状态推进和请求索引 |
| `conv_im2col_descriptor` | `conv_descriptor_addresses`、`conv_descriptor_commit`、`conv_descriptor_extent`、`conv_descriptor_position` | 描述符地址、提交字段、范围及连续位置 |
| `conv_im2col_stream` | `conv_im2col_stream_control`、`conv_im2col_request_control`、`conv_tile_group_low`、`conv_descriptor_group_context` | 输出资格、缓存请求、通道低段和高段范围关系 |
| `conv_windowed_cache` | `conv_cache_request_path`、`conv_cache_metadata_way`、`conv_cache_rank_table` | 查询与响应计算、每路元数据和替换次序 |
| `vector_engine` | `vector_engine_control`、`vector_engine_address`、`vector_engine_operand_store`、`vector_activation_clamp` | 状态、地址、操作数存储和激活范围 |

模块头说明职责和状态行为，端口声明逐项附有中文功能注释。数组下标及 packed 字段的含义在定义或连接处说明。普通算术表达式和存储数组由综合器推断实现资源。`use_dsp`、`ram_style` 等推断属性用于描述综合选择；设计源文件不实例化 LUT、BRAM 或 DSP 原语。

## 请求与状态计算

`conv_im2col_request_index` 将十个描述符来源的像素位置和输入行坐标组成 packed 数组，共用描述符内部选择。随后与下一输出行、下一卷积核位置和当前像素三个来源一起完成请求选择。完整窗口索引保持共享移位计算。

`conv_descriptor_position` 在分块接收边沿保存后续位置。`conv_descriptor_group_context` 随通道和配置的原有更新事件保存三位高段范围关系，低段比较继续使用当前输入列数。新寄存器保存重复使用的派生值，输入接收、输出有效及完成事件沿用原有时刻。

`conv_cache_lookup_valid_select` 为队首请求、普通输入、需求缺失和预览请求分别完成有效位读取与同周期写入转发，再按来源选择结果。缓存容量、替换状态、返回队列和请求接收规则由上层缓存模块维护。

## 流水信号数组

同一字段在连续阶段中的保存值使用一个数组，数组下标表示阶段。阶段控制向量、数据数组与批次编号共同推进；每个元素的更新使能和复位条件由其所在阶段决定。横纵坐标使用按轴索引的数组，具体含义见表中说明。

| 所属模块 | 数组示例 | 含义 |
| --- | --- | --- |
| `conv_im2col_request_index` | `incoming_candidate`（十项）、`request_candidate`（四项） | 描述符候选及四个请求来源中的像素与行坐标 |
| `conv_im2col_runtime_registers` | `o_input_coordinate`、`o_row_coordinate`（各两项）、`o_descriptor_index`（三项） | 当前坐标、输出行起点，以及分块起始位置、归约位置和卷积核位置 |
| `conv_descriptor_group_context` | `compare_channel`、`compare_group`、`compare_flags`（各四项） | 当前状态、新配置、解码结果和保存窗口的高段比较 |
| `requant_compute_lane` | `amount_q`（`p_amount_stages` 项）、`valid_q`、`lane_enable_q` | 移位参数、有效状态和尾部通道掩码 |
| `vec_requant` | `batch_pipe_q` | 分时计算批次编号 |
| `npu_task_configuration` | `cfg_mode_q[0:2]`、`cfg_k_q[0:2]`、`cfg_m_q[0:2]`、`o_cfg_n_q[0:2]` | 三个配置阶段中的模式和矩阵尺寸 |
| `npu_matrix_engine` | `base_q`（三项）、`offset_q`、`packed_q`、`wide_q`（各两项） | 权重预取各阶段的地址与格式 |
| `ps_window_scheduler` | `prediction_depth_q`、`prediction_column_q`（各三项） | 三个预测阶段的深度位置和列位置 |
| `ps_window_scheduler` | `prediction_reads_frame_q`（两项） | 请求接收、帧选择两个阶段的元数据读取条件 |
| `vector_engine` | `q_right`（三项）、`q_index`（七项） | 本地量化的移位参数和输出元素编号 |
| `conv_im2col_prefetch` | `channel_q`（两项）、`reference_q`、`reference_retire_q` | 两个阶段的预取通道、参考请求字段及参考缓存释放计数 |
| `conv_im2col_prefetch` | `accepted_coordinate_q`、`projected_coordinate_q`、`output_coordinate_q`（各两项） | 各上下文的横纵坐标，下标 0、1 分别表示横轴、纵轴 |

算术中间结果的位宽或数值含义不同时分别声明，例如有符号乘积、移位后的商和舍入结果。这样可以直接检查截断位置、符号扩展和进位处理。

## 量化运算

矩阵结果经 `npu_output_pipeline.u_vec_requant` 进入 `requant_compute_lane`。逐张量参数广播至各通道，逐通道参数按元素索引读取，INT8 与 INT16 由模式输入选择。控制、存储、通用乘法和移位分别使用独立文件。

该单通道量化流水线为七个使能边沿：乘法三个阶段、移位两个阶段、舍入与偏移一个阶段、裁剪与输出一个阶段。生产矩阵路径使用两个算术通道分时处理 16 个元素，使用 256 行输入缓冲容量。

向量 DW 仅在 `SHARED_QUANT_ENABLE=1` 时通过 `quant_req_*` 接口进入同一个 `vec_requant` 实例；顶层要求 `REQUANT_COMPUTE_LANES == SIZE` 才启用该方式。在两个矩阵量化通道的配置中，DW 复用向量引擎本地的 `vector_scalar_multiplier` 和 `vector_round_shift`，并由 `q_right`、`q_index` 和 `q_valid` 保存流水状态。`ADD_S8`、`AVGPOOL_S8` 和 `SOFTMAX_S8` 也按各自算法复用本地标量运算资源。详细接口和数值语义见 [统一量化运算](unified_requant.md)。

## 构建与检查

ASIC、Verilator、Makefile 和 Vivado 入口使用完整子模块清单，package 位于消费者之前。`scripts/rtl/source_files.py` 为局部测试解析工程内的模块依赖。

```bash
python3 test/rtl_layout/check.py --out build/rtl_layout
python3 test/rtl_layout/check_prepared_tile_width.py --out build/prepared_tile_width
python3 test/fpga_integration/run.py --out build/fpga_integration --verilator verilator --jobs 1
python3 test/asic_integration/run.py --out build/asic_integration --verilator verilator --jobs 1
```

文件组织检查覆盖模块与文件名称、重复定义、NPU 文件长度、资源选择标志、显式 FPGA 原语和生产入口依赖，并单独记录资源推断属性。物理行数包括端口、注释、空行和模块主体，NPU 文件按不超过 1,500 行检查。独立 PicoRV32 主核源文件为 2,222 行，其辅助模块分别使用独立文件。
