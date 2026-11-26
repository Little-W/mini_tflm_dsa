# 分段直接减法

`parallel_prefix_add` 的 `p_direct_subtract` 参数默认关闭。启用后，在有效分段配置及输入进位为一时，将第二操作数的反码恢复为减数，使用两个普通减法表达式并行计算低段和高段。低段借位根据高段的零传播条件修正高段，最高借位取反后仍作为原加法接口的输出进位。输入进位为零或存在未知位时使用原分组加法表达式，完整和值、最高进位及四态传播均保留。

该参数位于已有参数列表末尾，现有位置参数顺序保持不变。`parallel_prefix_high_group` 同时支持按零条件传播借位。两个原生减法共用 `parallel_prefix_native_differences`，由综合工具推断算术资源。

当前启用位置为 `vector_engine_address.u_parameter_stride`、`conv_next_use_predictor.g_coordinate_difference[*].u_difference` 和 `conv_im2col_geometry.u_history_delta`。公开端口、寄存器阶段和吞吐率保持不变。

```sh
python3 test/vector_direct_subtracts/run.py --out build/vector_direct_subtracts
python3 test/vector_direct_subtracts/measure.py --out build/vector_direct_subtracts_measurement
```

验证覆盖 21 组宽度和分段参数，在普通编译及 `SYNTHESIS` 编译下执行 42 项无输入约束证明，每项比较全部和值及最高进位，并进行 344064 次四态结果比较。完整父模块包括生产地址配置、坐标预测器及 `p_lanes=2、8` 的几何模块，两种编译方式共执行 8 项无输入约束逐周期等价证明，比较全部公开输出。

使用相同的 6667 ps 延迟目标、300 ps 导线延迟权重及 LUT 资源权重，完整调用模块结果如下。

| 完整模块 | 参考逻辑 LUT | 当前逻辑 LUT | 减少数量 | DSP 数量 | 触发器数量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `vector_engine_address` | 1824 | 1810 | 14 | 7 | 260 |
| `conv_next_use_predictor` | 1784 | 1777 | 7 | 15 | 1177 |
| `conv_im2col_geometry` | 2989 | 2947 | 42 | 14 | 594 |

三个模块合计减少 63 个逻辑 LUT，DSP、触发器及存储资源数量保持不变。地址模块最长内部寄存器路径为 `output_last_column[0]` 到 `dw_in_bounds`，包含 10 个组合单元；该路径两端均为模块内部寄存器。几何模块最长路径为 8 个组合单元。坐标预测器完整模块的最长路径为 14 个组合单元，与参考实现相同。

`validation.json` 保存算术、四态及完整模块验证结果。`measurement.json` 保存相同配置下的资源、路径和源文件 SHA-256。
