# IA 配置坐标和预取范围比较

`ia_ordered_coordinate_same` 使用分组的常量加一相等检查，独立处理相邻高位关系。`ia_ordered_coordinate_update` 并行比较当前基值和新配置基值，由 `init_cfg` 在最终结果处选择当前分块匹配状态。加载器在原时钟边沿保存该结果，缓存查询、配置接收、DMA 请求及返回周期保持一致。

输入包含未知值时，配置选择与坐标运算按完整四态表达式传播。通用编译使用完整坐标和值，FPGA 编译使用低位进位和高位关系。预取范围中的高位加一比较采用相同的分组结构。

## 完整模块测量

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`COMPACT_S8=0`、`ORDERED_JOB=1`，启用生产 DMA 数据布局、共享写数据寄存和 DMA 请求寄存。参照提交为 `c22af198f70d71881b6d8ceceedd89f43733e1b9`，两次测量使用相同的依赖文件和映射选项。

| 指标 | 参照实现 | 当前实现 |
|---|---:|---:|
| 名义 LUT，含 LUTRAM | 4,138 | 4,094 |
| 逻辑 LUT | 4,126 | 4,082 |
| LUTRAM | 12 | 12 |
| FF | 2,381 | 2,381 |
| DSP48E1 | 10 | 10 |
| RAMB36E1 / RAMB18E1 | 2 / 1 | 2 / 1 |
| 完整模块最长寄存器路径 | 11 | 10 |
| 坐标基值到 `demand_lookup_match_q` | 7 | 7 |
| `global_reduction_q` 到 `prefetch_prepare_in_range` | 6 | 4 |

采用 `physical-cost` 映射，最大 LUT 输入数为 8，较小 LUT 的面积权重为 1，连线延迟参数为 300 ps，延迟目标为 6,667 ps。资源、路径、源码与网表校验值保存在 `measurement.json`。这些数字来自完整 IA 加载器，整机连接后的结果由 SoC 综合报告记录。

## 验证范围

- 4 种完整加载器参数配置分别使用显式通用宏和 FPGA 宏，8 项证明共完成 80,424 个等价位。检查全部公开输出、共同状态寄存器和存储内容，外部输入及握手均未添加取值限制。
- 13 组坐标位宽及分块低位宽分别在两种编译模式下完成 SAT 证明，并执行 7,865,856 次四态结果比较。检查原坐标比较、配置使能选择和预取高位加一；较小位宽穷举 `0`、`1`、`X`、`Z` 的全部组合。
- 实际 DMA 测试在两种编译模式下运行有序预取和 32 块缓存复用，共 361,376 个周期、1,807,904 次数据检查。每个时钟周期比较加载器全部公开输出，并检查实际缓存返回数值。
- 配置分块数量计算的 8 组 SAT 与 332,288 次四态检查通过。其父模块词元检查对已经单独证明的坐标实例使用固定表示，其余功能语句继续逐项比较。
- 当前设计的 335 个模块及 5,896 个端口通过中文模块说明和端口功能注释检查。

完整结果和源文件校验值保存在 `validation.json`。

## 运行方法

运行环境需要提供 Yosys/Slang、Icarus Verilog 和支持当前测试入口的 Verilator。

```sh
python3 test/ia_coordinate_groups/run_formal.py --out build/ia_coordinate_groups/formal
python3 test/ia_coordinate_groups/check_coordinates.py --out build/ia_coordinate_groups/coordinates
python3 test/ia_coordinate_groups/run_numeric.py --out build/ia_coordinate_groups/numeric
python3 test/ia_coordinate_groups/measure.py --profiles production --out build/ia_coordinate_groups/measurement
python3 test/ia_tile_count/run.py --out build/ia_coordinate_groups/packed_tiles
```
