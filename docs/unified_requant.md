# 统一量化运算与模块文件组织

## 运算结构

矩阵结果由 `npu_output_pipeline` 中的 `vec_requant` 接收，并使用 `requant_compute_lane` 完成单个元素的量化。逐张量模式将一组乘数和移位参数广播给各通道；逐通道模式从参数存储读取相应参数。两种模式进入相同的乘法、移位、舍入和裁剪流水线。`i_s16` 选择 INT8 或 INT16 的参数处理及输出语义。

`vec_requant` 负责参数加载、WS/IS 数据顺序、尾部通道掩码、分组接收和输出组装，其量化算术实现集中在 `requant_compute_lane`。`p_compute_lanes` 决定实例数量：等于 `VLEN` 时并行处理一行，小于 `VLEN` 时按批次复用运算单元。生产矩阵配置保留两个量化运算通道，并使用 512 行输入缓冲保存阵列输出。

| 文件 | 职责 |
| --- | --- |
| `rtl/npu/writeback/vec_requant.sv` | 配置、参数存储访问、DMA、WS/IS 顺序和输出组装 |
| `rtl/npu/writeback/requant_compute_lane.sv` | 单通道 INT8/INT16 量化运算及有效位控制 |
| `rtl/npu/writeback/requant_shift_pipeline.sv` | 乘积移位、舍入位和低位非零信息 |
| `rtl/npu/writeback/requant_group_buffer.sv` | 分时计算所需的输入分组存储 |
| `rtl/npu/writeback/requant_pkg.sv` | 参数转换函数和公共流水线延迟常量 |
| `rtl/npu/conv/registered_multiplier_s32.sv` | 向量标量运算和量化通道分别实例化的通用有符号乘法器 |

每个模块或 package 使用独立源文件。工程内的其他模块采用相同的文件组织，生产文件清单及本地测试入口包含各自需要的子模块。NPU 模块源文件以少于 1,500 行为维护目标，文件长度检查覆盖注释、端口和模块主体。

## 向量算术与量化接口

`vector_engine` 的 DW 运算有两种量化连接方式。`SHARED_QUANT_ENABLE=1` 时，完成的累加值、逐通道参数、有效掩码和结果槽位编号通过 `quant_req_*` 接口进入 `npu_output_pipeline.u_vec_requant`，由其中的 `requant_compute_lane` 处理，再通过 `quant_rsp_*` 返回向量结果槽位。顶层仅在 `REQUANT_COMPUTE_LANES == SIZE` 时启用该连接；`vec_requant` 的分时计算配置将 DW 接口的接收允许和返回有效信号置零。

当前两个量化通道处理 16 个矩阵元素的配置使用 `SHARED_QUANT_ENABLE=0`。DW 在向量引擎内部依次发射各通道，复用 `u_scalar_multiplier` 和 `u_rounding`，随后加入输出偏移并裁剪。`vector_engine_control` 中的 `q_right[3]`、`q_index[7]` 和 `q_valid` 保存这条本地流水线的参数、元素编号和有效状态。

向量引擎按当前操作选择本地标量算术的输入，实际复用范围如下。

| 操作 | 运算资源与结果处理 |
| --- | --- |
| DW，`SHARED_QUANT_ENABLE=0` | 标量乘法、移位舍入、输出偏移和激活裁剪 |
| `ADD_S8` | 同一标量乘法器和移位舍入单元依次处理两个输入及输出缩放，随后加入偏移并裁剪 |
| `AVGPOOL_S8` | 二次幂分母使用移位舍入；其他分母使用标量乘法器计算倒数乘积与商检查，并在本地完成余数修正和舍入 |
| `SOFTMAX_S8` | `vector_softmax` 通过 `mul_a`、`mul_b` 和 `mul_product` 复用标量乘法器，指数、归一化和输出处理由该模块控制 |
| `MAXPOOL_S8`、`MINPOOL_S8` | PE 计算极值，向量引擎按通道裁剪并保存输出字节 |

上述本地操作的状态机、舍入和结果存储属于向量引擎。`requant_compute_lane` 的七级流水线用于 `vec_requant` 接收的矩阵数据及已启用共享接口的 DW 数据。

## 七级流水线

`requant_pkg::REQUANT_LATENCY` 为 7，控制部分通过该常量传递有效位、尾部标记和批次编号。

| 使能边沿 | 运算 |
| --- | --- |
| 1 至 3 | 保存操作数、计算部分积并形成有符号 64 位乘积 |
| 4 至 5 | 两级移位，保存有效商及最近偶数舍入条件 |
| 6 | 加入舍入增量和输出偏移 |
| 7 | 检查激活范围及输出精度范围，寄存结果 |

流水线每个使能周期可以接收一个元素。`i_en` 为零时，数据、有效位和尾部掩码共同保持；复位或 `i_clear` 清空有效状态。`p_delayed_parameters` 描述同步参数存储的返回周期，数据路径的七级延迟保持一致。

模式、输出偏移和激活范围属于任务配置，在本任务的运算流水线排空前保持稳定。INT16 使用零输出偏移。参数准备函数对完整 32 位输入定义转换结果，乘积移位同时处理 0 至 127 的输入移位量。无效尾部通道输出零，并随对应有效状态传递。

## 流水信号数组

同类数据与控制状态使用阶段索引访问。量化运算单元的 `amount_q` 保存移位量，各计算批次通过 `batch_pipe_q` 传递编号，有效位和尾部标记采用相同长度的阶段向量。配置流水的 `cfg_mode_q`、`cfg_k_q`、`cfg_m_q`、`o_cfg_n_q` 等字段按 `[0:2]` 保存三个阶段。向量路径使用 `q_right[3]` 和 `q_index[7]` 表示对应阶段的移位参数与元素编号。

数组中每个元素保留其所在阶段的更新条件、复位行为和数据类型。位宽或语义不同的中间结果分别声明，使截断、符号扩展和舍入位置保持明确。

## 参数与存储

逐张量模式直接广播配置寄存器中的处理后参数，逐通道模式选择同一运算入口所需的通道参数。WS 按输出列读取参数，IS 按当前组的行索引读取参数。同步读参数与相应输入数据在既有寄存边沿匹配。

`p_parameter_output` 控制公开的原始参数观察接口。需要该接口的实例可读取原始乘数和移位量；生产 `npu_top` 使用处理后参数进行计算，并关闭原始参数观察输出。分组缓冲的逻辑容量为 512 行，每行为 16 个 32 位元素和一个尾部标记。

RTL 使用有符号运算、显式位宽、参数化数组和同步读写描述硬件。综合工具根据目标器件和工艺库映射算术与存储结构。

## 文件依赖与检查

`scripts/rtl/source_files.py` 为本地测试补齐工程模块依赖，并将 package 排在使用它的模块之前。ASIC、仿真和 Vivado 的生产入口同时维护明确的源文件清单。`test/rtl_layout/check.py` 检查每个设计文件中的定义数量、模块与文件名、重复定义、资源选择标志、NPU 文件长度及生产文件依赖。

```bash
python3 test/rtl_layout/check.py --out build/rtl_layout
python3 test/requant_compute_lane/run.py --out build/requant_lane --verilator verilator
python3 test/requant_time_share/run.py --out build/requant_time_share --verilator verilator --vlen 16 --lanes 2 --reuse 32 --bus 64
python3 test/vector_shared_quant/run.py --out build/vector_shared_quant --verilator verilator
python3 test/asic_integration/run.py --out build/asic_integration --verilator verilator --jobs 1
python3 test/fpga_integration/run.py --out build/fpga_integration --verilator verilator --jobs 1
```

单通道测试使用独立的整数参考结果检查乘法极值、移位范围、最近偶数舍入、输出裁剪、暂停、复位和清空。集成检查覆盖 WS/IS、逐张量/逐通道、INT8/INT16、尾部通道、DMA 反压、分时运算及完整输入容量。综合面积与时序测量使用保存的源码副本及对应文件摘要。
