# 前端坐标寄存器的并行写入选择

`conv_im2col_runtime_registers` 保存卷积前端的配置、描述符、坐标与地址计算状态。输出列、输出行、当前卷积核行列和初始卷积核行列共六个十六位字段，分别准备描述符、运行推进和状态解码候选。

`conv_runtime_coordinate_select` 选择各字段的数据和写入资格。描述符提交参与末级选择，运行错误优先于输出推进，配置接收保持全部坐标。寄存器仍使用原有时钟和复位边沿，公开端口、输出拍数及背压周期保持不变。

`conv_runtime_wrap_difference` 并行计算十六位低段差值与十七位高段候选，低段借位只选择最终高段结果。配置阶段仍保存完整三十三位回绕位移。

顺序条件保留 `if` 和 `case` 的四态规则。未知提交或接收控制跳过对应分支，已选择数据中的 `X`、`Z` 保持完整。状态候选保留空操作状态及原有匹配次序。

## 形式检查

```bash
python3 test/frontend_runtime_coordinates/run_formal.py --out build/runtime_coordinates/language

python3 test/frontend_runtime_coordinates/check_production_events.py \
  --out build/runtime_coordinates/production

python3 test/frontend_runtime_coordinates/run_synthesis_equivalence.py \
  --profile n16_l8_c35_r64_d1 \
  --production-report build/runtime_coordinates/production/summary.json \
  --out build/runtime_coordinates/synthesis
```

语言语义比较将两份模块的 `unique case` 提示展开为顺序 `case`，保留第一个匹配分支，覆盖任意输入和状态位组合。四种参数分别使用 16、16、8、4 的阵列尺寸，16、8、4、2 个保存通道，35、35、33、40 位坐标，以及直接和寄存描述符。generic 与 FPGA 宏条件共八项证明通过，完整公开输出及共有内部状态合计 17396 个比较点相同。

综合模型保留实际 `unique case`，检查生产前端所满足的两组事件唯一性：配置、描述符、运行接收和状态处理共 29 个条件；解码与地址计算保存共 22 个条件。每组最多允许一个条件为一，具体条件由实际 RTL 自动提取并保存在报告中。

生产检查使用完整 `conv_im2col_frontend` 的真实连接，并把当前状态作为任意独热输入。除当前状态独热外，所有配置、描述符、数据、接口输入和其他保存状态均保持自由。直接和寄存描述符两种配置均证明：两组运行事件满足唯一性，并且状态更新保持独热。复位检查保留真实前端状态寄存器及其驱动，在 `rst_n=0` 时通过 SAT 证明状态等于 `IDLE` 且独热；结合下一状态保持证明，该性质在复位后持续成立。

八通道 SoC 参数下，generic 与 FPGA 综合模型的全部公开输出和共有状态均通过一步无界归纳。事件唯一性条件来自上述生产连接证明。

## 四态与数值检查

```bash
python3 test/frontend_runtime_coordinates/run_four_state.py \
  --out build/runtime_coordinates/four_state

python3 test/frontend_pipeline/run_numeric.py \
  --target fpga --cache-response-depth 2 --size 16 --lanes 8 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 \
  --narrow-mode 2 --windowed --prefetch --out build/runtime_coordinates/numeric16
```

四态比较使用两个参数配置和四组宏条件，共 394240 次逐周期检查。每个输入条件取 `0`、`1`、`X`、`Z`；状态包括单个有效位、多个有效位及未知位。每次检查直接准备相同的自由保存状态，再比较更新后的全部 52 个公开输出。固定循环只为 Icarus 的打包数组索引支持展开为相同顺序的常量索引。

Verilator 5.054 在八通道 SoC 前端参数下完成 42 项数值任务和 1024 组配置检查，耗时 128089 个仿真周期。十六通道扩展配置另完成相同任务和配置检查，耗时 118862 个周期。两种配置与各自的参考结果相同。任务覆盖输出数据、槽位、行列位置、通道掩码、最后一拍、错误响应、请求顺序和输出背压。

## 器件映射

```bash
python3 test/frontend_runtime_coordinates/measure.py --out build/runtime_coordinates/mapping
python3 test/frontend_runtime_coordinates/inspect_paths.py \
  --mapping build/runtime_coordinates/mapping --out build/runtime_coordinates/paths
```

测量包含完整运行寄存器模块，并在所有输入增加相同的寄存器。连接分析展开保留的模块边界，统计所有寄存器与存储端点之间的路径，图完整且无组合环。

| 指标 | 参考结构 | 并行坐标与分段减法 |
|---|---:|---:|
| 逻辑 LUT | 1366 | 1480 |
| 包装后的寄存器位数 | 4222 | 4222 |
| `tile_commit` 到输出坐标 | 4 级 | 1 级 |
| `tile_commit` 到卷积核坐标 | 5 级 | 1 级 |
| 输出接收到输出坐标 | 4 级 | 2 级 |
| 输出接收到卷积核坐标 | 4 级 | 2 级 |
| 当前状态到输出坐标 | 3 级 | 5 级 |
| 当前状态到卷积核坐标 | 5 级 | 8 级 |
| 配置回绕减法 | 11 级 | 8 级 |
| 完整模块最长路径 | 11 级 | 10 级 |

完整模块的最长路径为 32 位解码计数器加一。十六通道扩展配置使用 1545 个逻辑 LUT，包装后的寄存器位数为 4413，最长路径同为 10 级。上述结果属于布局前映射；完整 SoC 的资源数量和 150 MHz 时序需要完整设计的综合与实现报告。具体参数、源码摘要和验证结果保存在 `validation.json`。
