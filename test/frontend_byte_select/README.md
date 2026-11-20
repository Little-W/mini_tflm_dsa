# 前端固定字节选择

`stream_word` 根据前端状态选择当前缓存响应或保存的字数据。
`selected_word` 使用两位字节偏移选择四种固定切片，并在高位补零。
这一结构使字内选择与卷积位置、卷积核位置的移位解码分别综合。
状态更新、请求接收和响应周期保持原有行为。

参考版本为 `2bd1d2b332874303b5ad39ea489fce44b336ac98`。
参考前端 SHA-256 为 `9f16374fe7fa83eff6dddb68ded984b12b89579d4b7f5241fc3394e0c11e7e1f`，
当前源码为 `5914cf37f8df124e31481f56eb0c54d34444f2bb39fb14b230b40474b04a16c3`。

## 验证

`run.py` 直接读取实际字选择表达式，并核对其余 RTL 的语法内容与参考版本相同。
形式证明允许缓存数据、保存数据、前端状态和字节偏移任意变化，覆盖全部 71 位输入和 32 位结果。

实际 FPGA 窗口测试使用官方原语模型，参数为 `BUS_WIDTH=32`、DMA 大小 64、前端大小 16、
`LANES=4`、128 个缓存集合和四个请求名额。配置、背压、撤销、中止、复位和错误恢复测试全部通过：
422 个请求接收，418 个完成，4 个复位取消，4,457 个数值检查，19 个预期错误。
连续驻留窗口包含 128 个请求、512 个响应和 2,048 个数值，耗时 1,534 周期，最大响应间隔为 3 周期。
驻留窗口的 1,545 行请求、响应、AXI 和忙状态记录与固定参考版本逐周期相同。

## 独立映射

测量范围包含实际窗口队列、DMA 描述符选择和完整前端。
线性 DMA、缓存、预测器及三个 AXI 保护和选择模块保留接口边界。
参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、
`CONV_CACHE_SETS=128`、`LANES=4`。路径分析保留逐位连接及 DSP 内部组合运算。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 8,008 | 8,025 |
| RAM LUT | 56 | 56 |
| 触发器 | 3,491 | 3,491 |
| DSP48E1 | 33 | 33 |
| CARRY4 | 858 | 858 |
| `q0` 到写入数据端口 | 16 级 | 无组合路径 |
| `tap0` 到写入数据端口 | 12 级 | 无组合路径 |
| 前端状态到写入数据端口 | 16 级 | 13 级 |
| 全部前端寄存器到写入数据端口 | 16 级 | 13 级 |
| 测量范围内最长寄存器路径 | 15 级 | 16 级 |

写入数据端口包括 `wr_data` 和 `win_rsp_data`。
路径脚本在这些公开端口上添加测量终点，终点本身不增加组合逻辑级数。
当前范围内的最长寄存器路径为 `q0[3]` 到 `group_range_q[3]`。
综合最大驻留内存为 471,152 KiB。
源码摘要、资源和完整连接路径保存在 `docs/data/fpga_frontend_byte_select.json`。

## 运行

```bash
python3 test/frontend_byte_select/run.py --reference 2bd1d2b3 --out build/byte_select/formal
python3 test/window_dma/run.py --out build/byte_select/fpga --verilator verilator-modern --jobs 1 --fpga --reference-ref 2bd1d2b3
python3 test/window_descriptor_stage/synthesis.py --reference 2bd1d2b3 --out build/byte_select/synthesis --cases reference current
python3 test/frontend_byte_select/paths.py --reference build/byte_select/synthesis/reference --current build/byte_select/synthesis/current --proof build/byte_select/formal/summary.json --out build/byte_select/paths.json
```
