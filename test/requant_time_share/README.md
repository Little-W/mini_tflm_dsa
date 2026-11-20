# 分时量化与整组输入缓存

## 生产结构

`vec_requant` 保留每行 16 个 INT32 输入和 16 个 INT8、INT16 输出。生产 `npu_top` 的六、七个共享存储银行配置实例化两个 `requant_compute_lane`，每行分八批运算。16×16 阵列、8 个向量 PE、WS/IS、逐张量与逐通道量化、INT8/INT16 数值规则均保持完整。

独立 `vec_requant` 默认 `p_compute_lanes=VLEN`，使用原有并行接口时序。八、九个共享银行的 `npu_top` 配置同样使用完整并行量化。分时配置要求物理通道数为正且整除 `VLEN`。

### 输入组的预留

IA 数据源在开始一个输出组后连续发送整组行，PS replay 同时保持既定行序。`npu_top` 仅在最终输出组开始前增加容量条件：

1. 普通 WS/IS 组在 `send_ia_trigger && ia_output_pending` 时预留 `ps_frame_rows` 行。
2. 帧命令在 `send_ia_trigger && frame_command_final` 时预留 `frame_command_rows` 行。
3. 预留立即覆盖尚在阵列中的行、RAM 中的行、同步读出的行以及量化算术流水中的行。
4. 每产生一个完整量化输出行才释放一行预留。整组输出完成后，`o_group_ready` 允许下一最终输出组开始。

原有 OA 输出 FIFO 的整组空间检查继续参与任务启动。中间累加组按照原有 PS 调度执行。同步复位与任务清空同时取消队列内容和相关有效状态。

`requant_group_buffer` 使用一个同步读 `regfile` 保存输入行。生产每行宽度为 `16×32+1=513` 位，最后一位保存 `in_tile_done`。容量为 `IA_REUSE_NUM_MAX×SIZE`，生产七银行配置对应 512 行。存储器类型由综合工具选择。

### 参数生命周期

参数状态机在一行最后一个批次发射时推进行、列与 tile 坐标。排队中的输入行因此继续引用当前组的参数存储。

WS 模式按批次选择当前 16 个通道参数。IS 模式在最后一个批次发射边沿提前读取下一行参数，使同步参数读出结果与下一行数据同时可用。参数装载完成后保留一个同步读边沿，覆盖只有一行参数的短组。逐通道配置标志与其他组配置在 `init_cfg` 时保存。

每个算术通道同时采样 INT32 数据、预处理乘数和移位量，并经过 12 个使能边沿输出。批次编号、有效位和 tile 结束标志经过相同的流水阶段。输出寄存器按批次组装整行，只在最后一个批次写入时产生 `out_valid`。

队列与参数持续就绪时，2 通道配置每 8 个周期输出一行；4、1 通道配置分别每 4、16 个周期输出一行。输入等待还包含同步 RAM 读取、队列排队和参数 DMA 的实际周期。下一最终输出组等待本组输出完成。

## 完整模块资源

参数为 `BUS_WIDTH=64`、`VLEN=16`、`MAX_IA_REUSE=32`、`ENABLE_S16=1`、`p_input_rows=512`。使用同一 RTL 和原生 DSP 映射方式，完整量化模块的结果如下。

| 物理通道 | 逻辑 LUT | RAM LUT | SRL | FF | DSP48E1 | RAMB18E1 | 最长组合路径 | 持续输出间隔 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 7,404 | 800 | 160 | 7,501 | 80 | 2 | 15 | 1 周期 |
| 4 | 4,490 | 800 | 48 | 3,805 | 20 | 17 | 15 | 4 周期 |
| 2 | 3,825 | 800 | 24 | 3,248 | 10 | 17 | 15 | 8 周期 |
| 1 | 3,474 | 800 | 12 | 2,976 | 5 | 17 | 15 | 16 周期 |

2 通道相对完整并行实例减少 3,579 个逻辑 LUT、136 个 SRL、4,253 个 FF 和 70 个 DSP，新增 15 个 RAMB18E1。路径计数包含 DSP 内部实际寄存边界之间的组合运算，所有映射单元均已分类。150 MHz 的器件时序结论需要进一步使用目标器件的完整延迟模型和布线结果。

表中为模块映射资源。全 SoC 的逻辑共享、宽运算 DSP 选择和物理 LUT 合并使用整机测量结果。

## 缓存容量

`scripts/capacity/model.py` 与实际展开清单均按相同的银行数量条件选择分时缓存。生产缓存新增 `512×513=262,656` 位，即 32,832 字节。参数存储继续保留原有完整容量，WS 参数在组内共用，IS 参数按消费行读取。

| 共享银行数 | 银行大小 | 量化通道 | 最大输入组行数 | 新增输入缓存 | 全部缓存数组用量 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 6 | 8,192 字节 | 2 | 512 | 32,832 字节 | 116,121.5 字节 |
| 7 | 8,192 字节 | 2 | 512 | 32,832 字节 | 124,313.5 字节 |
| 8 | 8,192 字节 | 16 | 1,024 | 0 | 119,147.5 字节 |
| 9 | 8,192 字节 | 16 | 1,024 | 0 | 127,339.5 字节 |

这些配置均满足 `CAPACITY_BUDGET_BYTES=131072`、`CAPACITY_BUDGET_SCOPE=buffer-ram`。用量由展开后的数组声明位数计算，包含现有缓存元数据。生产结构同时检查 256 个阵列单元、8 个向量 PE、共享存储分区及完整参数存储。

## 验证范围

`measurement.json` 保存源码摘要、各次测试结果与综合报告摘要。

| 配置与检查 | 结果 |
| --- | --- |
| 4 通道，512 行，通用 RTL | 96 场景，576,352 个 INT8/INT16 元素 |
| 4 通道，512 行，Xilinx 原语模型 | 96 场景，576,352 个 INT8/INT16 元素 |
| 2 通道，512 行，Xilinx 原语模型 | 96 场景，528,384 个 INT8/INT16 元素 |
| 1 通道，512 行，Xilinx 原语模型 | 96 场景，577,888 个 INT8/INT16 元素 |
| 4 通道，1,024 行，通用 RTL | 96 场景，903,744 个 INT8/INT16 元素 |
| `VLEN=2`、1 通道、BUS32、2 行 | 96 场景，4,480 个 INT8/INT16 元素 |
| 默认 16 通道接口 | 256 场景、528,662 周期、209,001 行，所有既有公开输出逐周期相同 |
| 整组缓存计数形式检查 | 深度 1、3、16、512、1,024 全部通过 |
| 容量模型单元测试 | 83 项通过 |
| 4 通道完整生产 NPU | 86 项任务、216,348 个 INT32 参考结果通过 |
| 2 通道完整生产 NPU | 86 项任务、216,348 个 INT32 参考结果通过 |

模块数值测试覆盖 WS/IS、逐张量/逐通道量化、S8/S16、尾行与尾列、完整容量组、任意输入间隔、DMA 等待、配置清空和复位恢复。每个配置分别检查 INT8 与 INT16 输出、tile 标志、参数 DMA 地址和突发顺序。整数参考使用 128 位中间计算，测试程序启用 UBSan。

缓存形式检查在整组合法预留、输入不超过预留行数、输出仅消费已发射行三个条件下，证明：

`未完成预留 = 尚未抵达的输入 + RAM 中的行 + 已读出的行 + 已发射且尚未输出的行`

证明还检查计数上下界、地址范围和整组就绪时的空状态。输入、发射和输出等待时间、复位与清空均可任意变化。

完整生产 NPU 的 2 通道实例使用提交 `e6fd2b1f`，检查了 742 组、17,360 个输入与输出行，最大组为 512 行。86 项任务总计 961,873 个周期。记录包含功能、容量、写回及打包输入，额外检查权重提交、DMA归属和帧地址准备。正常任务的输入、发射和输出行数分别相等；取消任务同时清空尚未抵达的行预留。

`npu_configuration_observer.sv` 检查生产命令初始化时整组已完成，并检查有未完成输出时的精度、数据流、逐通道标志、偏移、激活范围和逐张量参数保持稳定。实际生产测试覆盖 163,340 个有未完成输出的周期，全部检查通过。

| 生产测试部分 | 任务数 | 周期数 | INT32参考结果 |
| --- | ---: | ---: | ---: |
| functional | 38 | 143,037 | 11,118 |
| capacity | 21 | 663,521 | 173,642 |
| output | 15 | 45,446 | 11,392 |
| packed | 12 | 109,869 | 20,196 |

完整生产结果和源码清单保存在 [production_two_lane_validation.json](../../docs/data/production_two_lane_validation.json)。这些周期数由实际任务开始至完成计数，涵盖分时计算等待和各模块的数据传输。

## 运行命令

工具的 `PYTHONPATH` 需要包含提供 `pyosys` 的 Python 环境，`--verilator` 使用支持当前 SystemVerilog 源码的 Verilator。

```sh
python3 test/requant_time_share/run.py \
  --out build/requant_time_share/lanes2_fpga \
  --verilator verilator-modern --lanes 2 --xilinx

python3 test/requant_time_share/run.py \
  --out build/requant_time_share/rows1024 \
  --verilator verilator-modern --reuse 64

python3 test/requant_time_share/run.py \
  --out build/requant_time_share/minimal \
  --verilator verilator-modern --vlen 2 --lanes 1 --reuse 1 --bus 32 --xilinx

python3 test/requant_time_share/run_formal.py \
  --out build/requant_time_share/buffer_formal

python3 test/requant_pipeline/run_interface.py \
  --out build/requant_time_share/default_interface \
  --reference-rev f037e9af --bus-width 64 \
  --verilator verilator-modern --jobs 1 --xilinx

python3 test/requant_time_share/prepare_measurement.py \
  --out build/requant_time_share/inputs --lanes 16 4 2 1
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/requant_time_share/inputs/cases.json \
  --cases lanes16 lanes4 lanes2 lanes1 \
  --out build/requant_time_share/synthesis \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 test/ps_channels/run_npu_structure.py \
  --out build/requant_time_share/production_structure \
  --verilator verilator-modern

python3 -m unittest discover -s test/capacity -p 'test_*.py'

python3 test/requant_time_share/run_npu.py \
  --out build/requant_time_share/npu \
  --verilator verilator-modern --jobs 1 --build-timeout 7200
```
