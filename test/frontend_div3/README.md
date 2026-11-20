# 前端五位商余数表

快速三通道组解码使用 `q0[4:0]` 查出除三的商和余数。
两个双输出查找表给出四位商，第三个双输出查找表给出两位余数。
完整的 16 位通道结果由 `q0[15:5]`、三个零位和低位余数组成。
该拼接保留原有截断表达式对任意 32 位位置输入的结果。
卷积核索引、当前通道、初始通道及通道范围状态继续在原有边沿更新。

参考版本为 `fa66f107ae53a35b0b8117c5af52cbbcc697f88b`。
参考前端 SHA-256 为 `5914cf37f8df124e31481f56eb0c54d34444f2bb39fb14b230b40474b04a16c3`，
当前源码为 `9b210b96544977227e2bea6b25a30db4b42b9432f48edadf3f1ef3293b00f524`。

## 验证

`run.py` 直接读取实际查找表和三个通道消费者，并核对其余前端语法内容相同。
通用模式及官方 `LUT6_2` 模型均通过全部输入证明，覆盖 32 位位置和 53 位结果。

| 检查 | 结果 |
|---|---|
| 配置、背压、撤销、中止、复位和错误恢复 | 422 个请求接收，418 个完成，4 个复位取消，4,457 个数值，19 个预期错误 |
| 连续驻留窗口 | 512 个响应，1,534 周期，最大响应间隔 3 周期 |
| 驻留窗口逐周期比较 | 1,545 行记录相同 |
| 非幂次输出宽度、卷积核和组通道数 | 30 组配置，960 个请求，7,916 个数值，249,416 周期 |
| 非幂次配置逐周期比较 | 249,411 行记录相同 |
| 连续短窗口 | 十种列数各 64 个请求，共 4,688 个数值 |

短窗口列数为 1、2、3、4、5、7、8、12、15、16。
列数 1 至 4 的最大响应间隔为 2 周期，其余已测列数为 3 周期。
全部接口周期与固定参考版本一致。

## 独立映射

测量包括实际窗口队列、DMA 描述符选择和完整前端，保留线性 DMA、缓存、预测器及 AXI 保护和选择模块的接口边界。
参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、
`CONV_CACHE_SETS=128`、`LANES=4`，路径统计保留 DSP 内部组合运算。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 8,025 | 8,004 |
| RAM LUT | 56 | 56 |
| 触发器 | 3,491 | 3,491 |
| DSP48E1 | 33 | 33 |
| CARRY4 | 858 | 853 |
| `q0` 到 `group_range_q` | 16 级 | 12 级 |
| `q0` 到 `ch_q`、`ch0_q` | 11 级 | 10 级 |
| `q0` 到 `tap0` | 12 级 | 11 级 |
| 测量范围内最长寄存器路径 | 16 级 | 15 级 |

当前综合最大驻留内存为 464,272 KiB。
源码摘要、完整路径和验证记录保存在 `docs/data/fpga_frontend_div3.json`。

## 运行

```bash
python3 test/frontend_div3/run.py --reference fa66f107 --out build/div3/formal
python3 test/window_dma/run.py --out build/div3/fpga --verilator verilator-modern --jobs 1 --fpga --reference-ref fa66f107
python3 test/frontend_div3/numeric.py --model build/div3/fpga --proof build/div3/formal/summary.json --verilator-include "$VERILATOR_ROOT/include" --out build/div3/numeric
python3 test/window_descriptor_stage/short_windows.py --model-dir build/div3/fpga --out build/div3/short --verilator-include "$VERILATOR_ROOT/include"
python3 test/window_descriptor_stage/synthesis.py --reference fa66f107 --out build/div3/synthesis --cases reference current
python3 test/frontend_div3/paths.py --reference build/div3/synthesis/reference --current build/div3/synthesis/current --proof build/div3/formal/summary.json --out build/div3/paths.json
```
