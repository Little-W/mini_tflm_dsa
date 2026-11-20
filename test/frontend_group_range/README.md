# 前端通道范围状态

`LANES <= 4` 时，`group_range_q` 保存当前通道距离组末是否大于0、1、2、3。
配置接收、快速窗口接收、换行、通道递增和两类译码都在更新 `ch_q` 的同一边沿更新范围状态。
六种通道来源分别计算范围关系，时序逻辑选择相应结果；幂次组的译码直接使用已保存的 `last_group_channel_q`。
`group_lane_allowed` 读取这些寄存结果，供写入通道数和行结束判断使用。

参考源码为 `3587da4318f0533f57ba43bb9ec787551debfb39`。
参考前端 SHA-256 为 `982d174690dc90640b9aa5245577667a951453849c4a4a9d7b44d91308c9fdb2`，
当前前端为 `9f16374fe7fa83eff6dddb68ded984b12b89579d4b7f5241fc3394e0c11e7e1f`。

## 验证

`run.py` 读取实际范围表达式、九处通道更新、十处范围更新及配置阈值更新。
除这些新增范围状态外，前端源码的语法内容与参考版本相同。
配置仅在 `IDLE` 接收，译码状态的通道更新与配置接收互斥；其它更新继承原有配置分支的优先次序。
状态证明允许每次通道更新选择任意一个来源，并允许来源数据和配置值任意变化。
`LANES=1、2、3、4、8` 均通过归纳证明。

实际FPGA模型采用官方原语模型，并启用协议观察和未定义行为检查。
窗口配置为 `BUS_WIDTH=32`、DMA大小64、前端大小16、`LANES=4`、`CACHE_SETS=128`、`CACHE_BLOCKS=4`。

| 检查 | 结果 |
|---|---|
| 配置、背压、撤销、复位和错误恢复 | 422个请求接收，418个完成，4个复位取消，4,457个数值，19个预期错误 |
| 连续驻留窗口 | 128个请求，512个响应，2,048个数值，1,534周期，最大响应间隔3周期 |
| 驻留窗口逐周期比较 | 1,545行记录与固定参考版本完全相同 |
| 非幂次输出宽度、卷积核和组通道数 | 30组配置，960个请求，7,916个数值，249,416周期 |
| 译码逐周期比较 | 249,411行记录与固定参考版本完全相同 |
| 连续短窗口 | 列数1、2、3、4、5、7、8、12、15、16各64个请求，共4,688个数值 |

短窗口的最大响应间隔：列数1至4为2周期，列数5至16为3周期。
上述修改保持接收、响应和公开状态的周期关系。

## 独立映射

测量包含实际 `conv_window_queue`、DMA描述符选择和完整前端。
线性DMA、缓存、预测器及三个AXI保护和选择模块保留接口边界。
参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、`CONV_CACHE_SETS=128`、`LANES=4`。
路径工具统计逐位连接，并计入DSP内部未寄存的组合运算。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑LUT | 7,795 | 8,008 |
| RAM LUT | 56 | 56 |
| 触发器 | 3,487 | 3,491 |
| DSP48E1 | 33 | 33 |
| CARRY4 | 855 | 858 |
| 最长寄存器组合路径 | 15 | 15 |
| `group_c[10]` 到描述符状态 | 14 | 13 |
| 全部 `group_c` 位到描述符状态 | 15 | 14 |
| `group_minus_two_q` 到描述符状态 | 14 | 无组合路径 |

当前 `group_c[10]` 的最长路径通过 `ch0_q` 的输入组范围判断。
新增范围寄存器到描述符状态的最长路径为13级。
综合进程的最大驻留内存为472,352 KiB。
完整资源、源码摘要和连接路径保存在 `docs/data/fpga_frontend_group_range.json`。

## 运行

```bash
python3 test/frontend_group_range/run.py --reference 3587da43 --out build/frontend_group_range/formal
python3 test/window_dma/run.py --out build/frontend_group_range/fpga --verilator verilator-modern --jobs 1 --fpga
python3 test/frontend_group_range/numeric.py --model build/frontend_group_range/fpga --proof build/frontend_group_range/formal/summary.json --verilator-include "$VERILATOR_ROOT/include" --out build/frontend_group_range/numeric
python3 test/window_descriptor_stage/short_windows.py --model-dir build/frontend_group_range/fpga --out build/frontend_group_range/short --verilator-include "$VERILATOR_ROOT/include"
python3 test/window_descriptor_stage/synthesis.py --reference 3587da43 --out build/frontend_group_range/synthesis --cases reference current
python3 test/frontend_group_range/paths.py --reference build/frontend_group_range/synthesis/reference --current build/frontend_group_range/synthesis/current --proof build/frontend_group_range/formal/summary.json --out build/frontend_group_range/paths.json
```
