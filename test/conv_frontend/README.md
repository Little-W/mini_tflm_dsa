# 硬件 im2col 前端独立验证

本目录使用直接数学公式生成期望值，并编译仓库 `rtl/npu/conv/` 中的生产模块进行 RTL 验证。

```bash
# 实际 RTL：8 组配置，以及 AXI span 和控制错误回归
python test/conv_frontend/tools/run_rtl_suite.py

# Native geometry：policy 1/2 的调度信息、预测器启动和 IA 写入
python test/conv_frontend/tools/run_native_geometry.py

# 独立的模型 / GCC C 直接卷积参考对照
python test/conv_frontend/tests/run_model_tests.py
```

输入、tile 描述符和直接数学公式期望值均在运行时生成。所有日志、状态、向量和编译目录默认位于仓库根目录的 `build/conv_frontend/`，不读取归档结果。

## RTL 覆盖

每组前端配置运行 40 个任务，覆盖矩形核、stride/dilation、padding、归约尾部、非对齐 p0/q0、乱序 tile、S8/S16 数值极值、非零 input_offset、缓存旁路、同地址换内容失效、读错误和下一任务恢复，以及接近 4 GiB 的读裁剪。通道分组任务逐组遍历空间位置，并跳过图像外的核位置，检查非零通道起点、顶部和左右边缘、跨输出行以及步长变化。配置握手后将外部 cfg 清零，确认正在执行的配置已经锁存。总线 AR/R 和 tile 写端有随机停顿，并核对实际 AXI 读字节与硬件统计值一致。

| SIZE | sets | ways | line bytes | 入口 |
|---:|---:|---:|---:|---|
| 4 | 128 | 2 | 16 | 直接 descriptor |
| 8 | 128 | 2 | 16 | 直接 descriptor |
| 16 | 128 | 2 | 16 | 直接 descriptor |
| 4 | 128 | 2 | 16 | `conv_ia_tile_path` + 写口适配器 |
| 4 | 2 | 1 | 8 | 直接 descriptor |
| 8 | 2 | 2 | 32 | 直接 descriptor |
| 16 | 2 | 1 | 32 | `conv_ia_tile_path` + 写口适配器 |
| 16 | 2 | 2 | 256 | 直接 descriptor |

另外，AXI span testbench 检查 251 个请求，覆盖 65535 字节长度、首尾非对齐、4 KiB 分段、高地址、AR/R/响应端等待和 RRESP 传播；实际检查 913763 个读取字节、2043 个 burst。控制 testbench 检查 23 个配置/描述符与恢复事件，包括溢出、非法 offset、S16 对齐、运行中配置等待和失败后恢复。

## 读取宽度与连续窗口

`LANES` 决定每拍输出的有符号 16 位元素数。缓存原始数据的读取宽度为至少 32 位、覆盖 `LANES` 个字节的最小二次幂宽度，并限制在单个缓存行内。`LANES=16` 且 `LINE_BYTES>=16` 时一次读取 128 位，最多输出 16 个 S8 元素或 8 个 S16 元素；外部 AXI 总线宽度由 `BUS_WIDTH` 独立决定。

`tile_narrow` 随描述符保存。该位为一时，每拍有效元素数量不超过 `NARROW_LANES`，默认值为 `BUS_WIDTH/8`。同一缓存字可分多拍输出，元素位置和尾部有效掩码由实际输出数量推进。读取地址按原始数据字宽选择自然地址分组，非零字节偏移、通道边界和归约尾部均由有效掩码处理。

默认 `REGISTER_CACHE_REQUEST=0` 使用缓存自身的请求寄存器，并配置单个在途需求请求。同步 RAM 命中可在下一周期返回，连续命中每周期返回一个原始数据字。末拍输出与下一行或下一描述符的请求可以在同一周期发生。设置 `REGISTER_CACHE_REQUEST=1` 可使用独立请求寄存器及四项需求队列。

相邻空间分块、同一输出位置的连续核位置、左右边缘的有效核位置跳转以及顶部边缘到下一输出行的跳转使用已保存的坐标递推。其余描述符使用通用坐标解码。配置变更、任意 `q0`、乱序空间位置和错误恢复仍遵循相同的描述符检查。

在 `windowed=1` 且输入通道数不少于 16 时，预取距离为四个缓存行对应的像素数量，最长限制为一个输入行。垂直步长和膨胀均为一时，预测目标选择当前窗口最下方的输入行；其余情况沿当前核行预测。跨输入行时保留横坐标余量，并按垂直步长推进。预取的坐标、物理地址、缓存索引与有效范围按同一流水保存。

```bash
python3 test/conv_frontend/tools/run_rtl.py \
  --bus-width 64 --lanes 16 --narrow-mode 2 \
  --cache-bytes 8192 --line-bytes 128 --windowed --prefetch \
  --out build/frontend_wide

python3 test/conv_frontend/tools/run_rtl.py \
  --bus-width 32 --lanes 4 --cache-bytes 4096 --line-bytes 16 \
  --windowed --prefetch --out build/frontend_axi32
```

`--narrow-mode 2` 逐描述符交替使用完整输出宽度和受限输出宽度。缓存容量由 `--cache-bytes` 指定，组数据此结合缓存行大小和路数计算。

仿真附加参数 `+CONV_FRONTEND_PROFILE` 输出各状态驻留周期、坐标递推次数、缓存等待周期、连续输出拍数及预取活动周期。`+CONV_FRONTEND_TRACE` 输出前 64 个已接收描述符。统计逻辑位于独立观察模块中，不参与综合。

## Native geometry 检查

`run_native_geometry.py` 默认分别编译和运行 policy 1、policy 2。输入为 NHWC 1×1×16，卷积核为 1×1，输入基址为 `0x1000`，启用 windowed 和 prefetch。原生调度参数 `cfg_sched_r=1`、`cfg_sched_groups=1`，tile 参数为 `p0=q0=0`、一行、16 列。

测试比较全部 16 个 IA 输出值，检查 geometry predictor 恰好启动一次，并检查任务完成时外部读事务已结束。总仿真周期限制为 2000。默认结果目录为 `build/conv_frontend/native_geometry/`，其中 `summary.json` 包含各策略的执行命令、状态文件、源文件与向量 SHA-256。

```bash
python test/conv_frontend/tools/run_native_geometry.py --policies 1 2
```

`--out` 可指定结果目录。现有 testbench 的 `NATIVE_SCHED_R`、`NATIVE_SCHED_GROUPS` 默认值均为 0，`EXPECT_GEOMETRY_PREDICTIONS` 默认为 −1，表示不要求特定预测次数。通用 `run_rtl.py` 提供对应的 `--native-sched-r`、`--native-sched-groups` 和 `--expect-geometry-predictions` 参数，并支持 `--vectors`、`--max-cycles` 和 `--out`。

## 事务与编译检查

读错误用例选择中心核 `q0 = group_c * (kernel_w + 1)`，使该任务产生外部读取。测试检查读错误传播、任务恢复，以及外部事务结束状态。

测试包含缓存状态断言，并审查所有 Verilator 诊断。宽度、符号、锁存器、多驱动、组合循环等诊断会使测试失败。允许的诊断包括结构中的未使用字段、测试记分板赋值风格、同步断言观察异步复位。完整诊断保留在日志中。

每次执行生成 `build/conv_frontend/frontend_rtl_suite_status.json`，包括实际工具版本、每个测试命令、所有诊断和本次 PASS/FAIL 统计。

## 范围说明

本目录覆盖前端、缓存、精确范围读取器及两个适配模块。完整 NPU 的 IA 调度、脉动阵列、bias、逐通道量化、写回，以及 CPU/NMSIS 分发，由对应的 NPU/SoC 测试验证。模型/C 数值参考、实际 RTL 仿真与 NMSIS 二进制测试分别记录结果。

## 描述符行范围检查

描述符的行范围使用完整 33 位无符号语义检查 `tile_p0 + tile_rows <= position_count`。当 `RW < 32` 时，低 `RW` 位加法与高位大小、相等比较并行计算。配置完成时同时保存 `position_count` 和其高位减一值，使低位进位只参与最后的条件合并。复位、配置接受和配置完成的更新优先级保持一致。`RW >= 32` 使用完整 33 位表达式。

```bash
python3 test/conv_frontend/tools/row_range_equivalence.py \
  --measure --out build/frontend_row_range/arithmetic
python3 test/conv_frontend/tools/compare_frontend.py \
  --reference-ref f5b7573 --out build/frontend_row_range/compare
python3 test/conv_frontend/tools/synthesis.py \
  --reference-ref f5b7573 --out build/frontend_row_range/synth_reference
python3 test/conv_frontend/tools/synthesis.py \
  --out build/frontend_row_range/synth_current
```

算术检查从 RTL 提取实际分段表达式与配置预计算表达式，对 `RW=1/2/3/4/5/8/16/31/32/33` 的全部输入编码证明结果一致，包含位置为零、低位进位、32 位位置越界以及宽行计数截断。

公开输出比较在同一测试中运行修改前后的前端，共检查 1,665,368 个周期。数值测试包含 32/64 位总线、SIZE 4/8/16，以及 windowed 和 prefetch 配置，共 148 个任务；控制测试包含 23 项配置、非法描述符和恢复检查。所有返回数据、握手、写入位置、完成脉冲及错误状态均逐周期一致。

`SIZE=16` 的范围检查结构使用 5 位行计数，新增 27 个配置触发器。独立映射统计如下。

| 检查结构指标 | 修改前 | 分段比较 |
|---|---:|---:|
| 描述符输入到范围结果的组合单元数 | 13 | 6 |
| 包含配置预计算的最长组合单元数 | 13 | 8 |
| LUT 单元 | 27 | 51 |
| 配置触发器 | 32 | 59 |
| CARRY4 | 12 | 12 |

独立前端综合保留真实缓存、预测器端口，并将这两个子模块作为黑盒。使用 `SIZE=16`、64 位总线时，前端为 6,485 个 LUT、3,148 个触发器、30 个 DSP 和 720 个 CARRY4；修改前分别为 6,435、3,121、30 和 708。完整前端的最长组合路径为 26 个单元，位于行坐标更新；修改前最长路径为 25 个单元，位于输入坐标计算。整机时序检查继续使用完整的模块连接和器件约束。

## 坐标更新边界判断

配置接受时保存 16 位卷积核末列。运行阶段通过当前 `kx_q` 与末列相等关系确定卷积核换行；`kernel_w` 为零时该关系保持无效。更新后的 35 位坐标通过高 19 位为零、低 16 位小于对应图像尺寸判断是否有效。完整坐标加法、符号扩展、溢出截断和所有公开接口周期保持一致。

```bash
python3 test/conv_frontend/tools/coordinate_boundary_equivalence.py \
  --reference-ref b8b34d5 --out build/frontend_coordinate_boundary/arithmetic
python3 test/conv_frontend/tools/compare_frontend.py \
  --reference-ref b8b34d5 --out build/frontend_coordinate_boundary/compare
python3 test/conv_frontend/tools/synthesis.py \
  --reference-ref b8b34d5 --out build/frontend_coordinate_boundary/synth_reference
python3 test/conv_frontend/tools/synthesis.py \
  --out build/frontend_coordinate_boundary/synth_current
```

算术检查直接提取 RTL 的两种换行条件、四个坐标更新表达式和两种边界判断，并检查配置阶段的末列计算。SAT 证明覆盖全部 16 位几何参数、33 位增量和 35 位坐标编码，包括零尺寸、负坐标以及最高位溢出。公开输出比较检查 1,665,368 个周期，包含 148 个数值任务和 23 项控制、错误恢复检查。

独立前端使用 `SIZE=16`、64 位总线，缓存和预测器保持相同接口黑盒。

| 指标 | 提交 `b8b34d5` | 当前坐标边界结构 |
|---|---:|---:|
| LUT 单元 | 6,485 | 6,583 |
| 触发器 | 3,148 | 3,164 |
| CARRY4 | 720 | 719 |
| DSP48E1 | 30 | 30 |
| 最长寄存器间组合路径单元数 | 26 | 24 |
| `kx_q` 到状态寄存器的组合路径单元数 | 26 | 21 |
| `ox_q` 到状态寄存器的组合路径单元数 | 26 | 24 |

综合脚本保存源码快照、SHA-256、映射后 JSON 和 `pre_lut.il`。后者保留映射前的寄存器名称，供寄存器间连通路径分析使用。这里的单元数用于比较组合结构；器件频率由完整 SoC 的布局布线时序报告确定。

## 共享索引和输出格式化检查

直接接收描述符时，前端先选择完整像素坐标，再共用缓存索引移位。流式输出先选择数据字和字节位置，各通道随后完成八位符号扩展、九位偏移加法或十六位数据提取。这两部分均使用原有时钟边界和传输条件。

`compare_complete_frontend.py` 分别读取参考目录与当前目录的全部 RTL 依赖，并为参考模块、包和观察模块使用独立名称。测试逐周期比较全部公开输出，包括无效周期的数据、各通道掩码、存储请求、完成状态和错误状态。以下参数对应八通道、64 位总线和 4 KiB 窗口缓存。

```bash
python3 test/conv_frontend/tools/compare_complete_frontend.py \
  --reference-source-root /path/to/reference \
  --out build/frontend_shared_selection/compare \
  --size 16 --slot-width 5 --lanes 8 --bus-width 64 \
  --cache-sets 16 --line-bytes 128 --register-descriptor 0 \
  --cache-response-depth 1 --windowed --fpga --synthesis --jobs 1
python3 test/conv_frontend/tools/check_shared_index.py \
  --reference-source-root /path/to/reference \
  --out build/frontend_shared_selection/index
python3 test/conv_frontend/tools/check_return_formatter.py \
  --reference-source-root /path/to/reference \
  --out build/frontend_shared_selection/formatter
```

索引检查从实际 RTL 提取表达式，证明关闭移位及全部 32 种移位量下的逐位等价性。数据、选择位和上下文条件保持自由输入，并另外检查包含未知态和高阻态的仿真样本。格式化检查覆盖 1、2、4、8、16、20 个输出通道及 4、8、16 字节读取宽度的八种组合，同时比较参考实现和数学结果。每次运行保存源码摘要、证明日志和结果汇总。
