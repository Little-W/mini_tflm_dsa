# 前端行尾并行比较

快速位置解码的行尾判断直接使用当前位置、历史位置和历史列数，
将模加法压缩为两个操作数后检查两种目标和值。
当模和值与目标相等时，历史列数与目标的大小关系给出最高位进位。
坐标数值和行尾判断分别计算，状态机继续在原有边沿接收结果。

`add_equal` 的 `p_use_lut` 参数控制并行位比较，默认值为零。
前端的两个行尾实例在 FPGA 模式下启用该实现。
每位使用一个六输入查找表检查本位和相邻低位的进位关系，随后按六位分组归约。
通用模式保留组合逻辑表达式。

参考版本为 `fa66f107ae53a35b0b8117c5af52cbbcc697f88b`。
参考前端 SHA-256 为 `5914cf37f8df124e31481f56eb0c54d34444f2bb39fb14b230b40474b04a16c3`，
当前前端为 `0800bdd88dcbccaca762a2daf985f84ad5e5710ca4d772baa3acaad528fb940d`。
当前 `add_equal.sv` 的 SHA-256 为 `ae8419319b2f63d1928c3e0c7ed4ea0f3e473076a9eaa2eaa00fee00e3d71d65`。

## 验证

实际前端源码的 112 位输入及三个比较结果在通用模式和官方 FPGA 原语模型下均通过全部输入证明。
其它前端语法内容与参考版本相同。
`add_equal` 的 1、6、7、16、32、33 位配置分别证明默认通用实现和 LUT 实现与参考模块等价。

| 检查 | 结果 |
|---|---|
| 配置、背压、撤销、中止、复位和错误恢复 | 422 个请求接收，418 个完成，4 个复位取消，4,457 个数值，19 个预期错误 |
| 连续驻留窗口 | 128 个请求，512 个响应，2,048 个数值，1,534 周期，最大响应间隔 3 周期 |
| 驻留窗口逐周期比较 | 1,545 行记录与固定参考版本相同 |
| 非幂次输出宽度、卷积核和组通道数 | 30 组配置，960 个请求，7,916 个数值，249,416 周期 |
| 非幂次配置逐周期比较 | 249,411 行请求、响应和 AXI 记录相同 |
| 连续短窗口 | 列数 1、2、3、4、5、7、8、12、15、16 各 64 个请求，共 4,688 个数值 |

短窗口最大响应间隔：列数 1 至 4 为 2 周期，其余已测列数为 3 周期。
测试使用实际 FPGA 原语模型并启用协议观察和未定义行为检查。

## 独立映射

测量包括实际窗口队列、DMA 描述符选择和完整前端。
线性 DMA、缓存、预测器及三个 AXI 保护和选择模块保留接口边界。
参数为 `SIZE=64`、`IM2COL_SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=64`、
`CONV_CACHE_SETS=128`、`LANES=4`。逐位路径统计包含 DSP 内部组合运算。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 8,025 | 8,061 |
| RAM LUT | 56 | 56 |
| 触发器 | 3,491 | 3,491 |
| DSP48E1 | 33 | 33 |
| CARRY4 | 858 | 866 |
| `last_p` 到 `row_wrap_q` | 15 级 | 10 级 |
| `p0` 到 `row_wrap_q` | 15 级 | 11 级 |
| 全部前端寄存器到 `row_wrap_q` | 15 级 | 13 级 |
| 测量范围内最长寄存器路径 | 16 级 | 15 级 |

当前综合最大驻留内存为 450,428 KiB。
源码摘要、验证结果和完整连接路径保存在 `docs/data/fpga_frontend_row_wrap.json`。

## 运行

```bash
python3 test/frontend_row_wrap/run.py --reference fa66f107 --out build/row_wrap/formal
python3 test/frontend_row_wrap/helper.py --reference fa66f107 --out build/row_wrap/helper_formal
python3 test/window_dma/run.py --out build/row_wrap/fpga --verilator verilator-modern --jobs 1 --fpga --reference-ref fa66f107
python3 test/frontend_row_wrap/numeric.py --model build/row_wrap/fpga --proof build/row_wrap/formal/summary.json --verilator-include "$VERILATOR_ROOT/include" --out build/row_wrap/numeric
python3 test/window_descriptor_stage/short_windows.py --model-dir build/row_wrap/fpga --out build/row_wrap/short --verilator-include "$VERILATOR_ROOT/include"
python3 test/window_descriptor_stage/synthesis.py --reference fa66f107 --out build/row_wrap/synthesis --cases current
python3 test/frontend_row_wrap/paths.py --reference "$REFERENCE_FRONTEND_SYNTH" --current build/row_wrap/synthesis/current --proof build/row_wrap/formal/summary.json --helper-proof build/row_wrap/helper_formal/summary.json --out build/row_wrap/paths.json
```

`REFERENCE_FRONTEND_SYNTH` 指向 `fa66f107` 工作树中以同一参数生成的映射目录，
其中包含原有 `add_equal.sv` 的源码摘要。
