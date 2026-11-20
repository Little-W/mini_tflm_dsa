# 前端配置边界与位置解码时序优化

`conv_im2col_frontend` 在配置接收时保存输入末列、分组末通道和卷积核宽度有效标志。流传输中的通道选择及列递增判断使用这些寄存器，位置解码使用已接受的描述符位置 `p0`。描述符接收、数据写入、请求和错误响应保持原有周期。

## RTL 结构

`last_input_col_q` 和 `last_group_channel_q` 分别保存十六位配置宽度减一的结果，复位值为 `16'hffff`。`kernel_width_valid_q` 保存 `cfg.kernel_w != 0`，复位值为零。这些寄存器与配置寄存器 `c` 在同一接收边沿更新，配置未被接收时保持原值。

输入列递增判断并行处理符号位、三十五位有符号溢出和低十六位边界，保留原表达式 `ix + 1 < input_w` 的全部输入编码语义。两个写入通道分别检查当前通道是否等于组宽度及组末通道，避免分组余量减法继续串接通道比较。多通道分支显式计算低位加法和高位关系；所有生成分支均使用固定名称。

位置解码始终读取 `p0`。`P_DECODE` 和 `P_WAIT` 消费保存的描述符位置；快速请求的 `incoming_context` 由 `incoming_fast` 限定，后者包含 `tile_p0 == p0`。因此，`request_output_y` 使用快速解码结果时，外部输入位置与保存位置相同。该资格关系和所有解码结果的消费者均包含在形式比较中。

本项 RTL 使用显式位宽、组合赋值及配置寄存器，新增注释使用中文。

## 独立综合结果

比较版本为 `05be5b8`，其前端源码与完整 SoC 测量版本 `1c081bc` 相同。当前源码的 SHA256 为 `bfb600e8bbb07f727920610977abe468939322b85fef54e80ee91990d4cb685e`。

综合参数为 `SIZE=16`、`BUS_WIDTH=64`、`LANES=2`，目标为 Xilinx 7 系列。缓存和预测器保留为模块接口边界。

| 项目 | `05be5b8` | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 6,455 | 6,472 |
| 触发器 | 3,197 | 3,230 |
| DSP48E1 | 30 | 30 |
| CARRY4 | 715 | 720 |
| 模块内部最长组合单元数 | 22 | 21 |

这项修改增加 17 个逻辑 LUT 和 33 个触发器，缩短下列实际寄存器之间的组合路径。

| 起点寄存器 | 终点寄存器 | `05be5b8` | 当前版本 |
|---|---|---:|---:|
| `ix` | `state` | 22 | 19 |
| `ix` | `addr` | 18 | 9 |
| `c.group_c` | `addr` | 22 | 19 |
| `c.group_c` | `state` | 18 | 16 |
| `c.group_c` | `q_current` | 21 | 17 |

新寄存器到接收寄存器的最长路径也纳入统计：`last_input_col_q` 到 `state` 为 11 个单元，`last_group_channel_q` 到 `addr` 为 19 个单元，`kernel_width_valid_q` 到 `state` 为 19 个单元。`q0` 出发的最长路径保持为 15 个单元，到 `state` 为 14 个单元。

### 外部位置输入的传播

下表统计 `tile_p0` 输入端口到寄存器数据端的路径，包含位置解码及快速请求选择的组合逻辑。

| 终点寄存器 | `05be5b8` | 当前版本 |
|---|---:|---:|
| `oy_q` | 14 | 无数据路径 |
| `state` | 13 | 13 |
| `request_epoch_q` | 13 | 14 |
| `request_index_q` | 11 | 14 |
| `request_progress_q` | 14 | 8 |

`tile_p0` 到 `request_progress_q` 使能端的路径由 12 个单元缩短至 8 个单元。请求索引和纪元的数据路径仍需要在完整 SoC 中检查。

路径工具依据映射后的实际连线及寄存器原名确定起点和终点，按 `LUT6_2` 和 `CARRY4` 的逐位依赖统计。输入端口的分析起点只加入内存中的连接图，磁盘上的映射网表及资源统计保持原样。缓存和预测器的内部路径由完整 SoC 分析覆盖；这里的单元数量用于比较前端结构，150 MHz 由完整器件的布局布线时序报告检查。

## 功能与形式验证

公开输出逐周期比较以 `05be5b8` 为参考，包含配置和描述符握手、写入有效信号及全部载荷、完成和错误状态、忙状态、AXI 读地址和读响应握手。四组数值测试及控制测试均通过。

| SIZE | AXI 位宽 | 窗口预取 | 数值任务 | 比较周期 |
|---:|---:|---:|---:|---:|
| 4 | 32 | 关闭 | 37 | 779,154 |
| 8 | 64 | 关闭 | 37 | 374,717 |
| 16 | 64 | 关闭 | 37 | 259,661 |
| 16 | 64 | 开启 | 37 | 251,702 |
| 合计 | | | 148 | 1,665,234 |

另有 23 项控制检查，包含 16 次填充写入，共比较 134 个周期。测试覆盖输出暂停、总线等待、配置错误和复位。

组合形式验证直接提取 RTL 表达式，不限制算术输入编码。输入列比较覆盖三十五位坐标及十六位图像宽度；通道比较覆盖单通道、双通道和低位宽度 1 至 15 的分段算术。配置状态关系采用时间归纳，覆盖复位、配置接收和保持状态。

位置解码比较覆盖 `SIZE=4/8/16` 与策略 `0/1/2/3` 的 12 组组合，检查 100 位可观察结果，并证明 `incoming_context` 必然满足 `tile_p0 == p0`。脚本检查 `P_DECODE`、`P_WAIT` 和 `request_output_y` 的全部消费者，逐字检查相应选择表达式。组合证明同时包含既有的归约组末偏移状态关系及十项坐标判断；将已证明的改写归一化后，模块其余内容与比较版本相同。

机器可读结果、源码哈希、测试脚本哈希和路径摘要见 [`frontend_stream_timing_validation.json`](../../docs/data/frontend_stream_timing_validation.json)。

## 复现

先加载项目的开源 FPGA 工具环境，再从仓库根目录运行：

```sh
python3 test/conv_frontend/tools/group_successor_equivalence.py --out build/frontend_timing/formal
python3 test/conv_frontend/tools/compare_frontend.py --reference-ref 05be5b8 --out build/frontend_timing/compare
python3 test/conv_frontend/tools/synthesis.py --reference-ref 05be5b8 --out build/frontend_timing/reference
python3 test/conv_frontend/tools/synthesis.py --out build/frontend_timing/current
python3 test/conv_frontend/tools/measure_stream_paths.py --mapped build/frontend_timing/reference/mapped.json --pre-lut build/frontend_timing/reference/pre_lut.il --out build/frontend_timing/reference_metrics.json
python3 test/conv_frontend/tools/measure_stream_paths.py --mapped build/frontend_timing/current/mapped.json --pre-lut build/frontend_timing/current/pre_lut.il --out build/frontend_timing/current_metrics.json
python3 test/conv_frontend/tools/measure_group_successor.py --mapped build/frontend_timing/current/mapped.json --pre-lut build/frontend_timing/current/pre_lut.il --out build/frontend_timing/group_metrics.json
```

同一主机并行运行综合时，使用项目的小模块综合锁顺序执行两个综合命令。
