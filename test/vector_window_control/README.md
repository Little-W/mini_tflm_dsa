# 向量窗口与配置资格的组合路径

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

## 设计

窗口返回的有效位先按通道归并，再选择循环起点对应的非空结果。二的整数次幂银行数使用这一结构；其他银行数保持直接归并。八路窗口的银行有效位采用两组四路选择。索引继续参与 RTL 选择表达式，因此未知索引的四态行为与原表达式相同。数据、地址和有效位仍在原有时钟边沿保存。

输入扫描的四组区间分别用十八位有符号差值检查上下端点。十七位有符号操作数的完整差值可以由十八位表示，最高位直接表示大小关系。八个差值并行计算，使用普通的定宽减法表达式；区间端点、坐标位宽和有效范围保持完整。

配置检查器在 `CALCULATE` 的第一项后续乘积阶段保存 `kernel_limit_ok_q`，后面的 `FIELDS` 状态使用该结果。核尺寸已经在此前的 `CAPTURE` 阶段保存，配置检查的状态顺序和总周期保持相同。

`compute_pool_group` 与 `compute_index` 的全部十六处更新共同保存。每个标志表示一个 PE 组的起始下标，极值池化结果写入直接使用这些资格。生产配置增加两个组选择触发器。接收完成等式使用公共 `add_equal` 的逐位进位一致性实现，接收累计值仍保留完整三十二位回绕行为。

## 功能与周期检查

| 检查 | 结果 |
| --- | --- |
| 生产配置：16 通道、8 PE、64 位总线、8 路窗口、共享存储、独立量化 | 616 项任务，170,743 个数值输出通过 |
| 通用配置：16 通道、16 PE、32 位总线、4 路窗口、私有存储、共享量化 | 616 项任务，170,743 个数值输出通过 |
| 生产配置固定等待 | 40 项任务，103,743 个输出通过 |
| 窗口循环选择与有符号区间 | 10 项全部二值输入证明；400,000 次四态比较 |
| 配置上限保存 | 6 组参数的实际源码一步归纳证明 |
| 完整配置检查器公开输出 | 6 组参数各 2,048 项配置；786,438 次逐周期四态比较 |
| 计算下标与 PE 组资格 | 16 处更新检查；6 组实际源码一步归纳证明；393,222 次四态比较 |
| 接收完成等式 | 97 位输入的完整证明；100,000 次四态比较 |

生产、通用和固定等待测试的逐案例周期及全部统计与参考源码一致，总周期分别为 3,423,269、3,995,791 和 1,071,159。检查包括任务恢复、输入暂停、权重地址与数据、输出背压、请求与响应交叠以及全部数值结果。

配置证明只要求检查期间保持运算模式稳定，`IDLE` 与 `COMPLETE` 状态可以切换配置。其他配置字段、控制输入和后续复位均保持自由。组选择证明保留实际下标与资格寄存器，其余状态和存储输出作为自由输入，覆盖生产、通用、单 PE、非整数组及较大实例。

已有末项状态与预取地址证明继续保留实际时序逻辑。`engine_transform.json` 精确记录上述独立检查所覆盖的源码片段；恢复这些片段后，原有检查确认其余源码与参考版本相同。

## 生产参数综合

| 项目 | 参考源码 a03aa94a | 当前源码 69f181e3 |
| --- | ---: | ---: |
| 逻辑 LUT | 10,498 | 10,399 |
| LUT RAM 名义 LUT 数 | 176 | 176 |
| 名义 LUT 合计 | 10,674 | 10,575 |
| 触发器 | 6,417 | 6,420 |
| DSP | 73 | 81 |
| RAMB18 | 9 | 9 |
| 完整寄存器连接图最大组合级数 | 10 | 10 |

新增算术资源来自八个并行区间差值。三处新增寄存状态分别是配置上限资格和生产配置的两个 PE 组选择资格。

| 实际连接范围 | 参考级数 | 当前级数 |
| --- | ---: | ---: |
| 输入接口到 `window_write_pending` | 11 | 8 |
| 输入接口到 `window_response_count_ok_q` | 9 | 7 |
| 区间端点到 `dw_in_bounds` | 10 | 6 |
| 全部寄存器到配置检查状态 | 10 | 5 |
| 计算下标或组资格到累加结果 | 10 | 9 |

接口统计在分析网表中标记输入边界，不改变硬件。以上结果来自独立向量实例，完整 SoC 测量进一步检查外围控制与共享存储连接。

## 复现

从仓库根目录导出参考源码：

```sh
mkdir -p /tmp/vector_control_reference
git archive cfcc1a95 rtl include | tar -x -C /tmp/vector_control_reference
```

执行组合、计数、配置和组资格检查：

```sh
for check in run_comb run_count run_config run_group; do
  python test/vector_window_control/${check}.py --source-root . --reference-root /tmp/vector_control_reference --tool-root . --out /tmp/vector_control_${check}
done
python test/vector_window_control/run_config_four_state.py --source-root . --reference-root /tmp/vector_control_reference --out /tmp/vector_control_four_state
python test/vector_request_boundary/run_formal.py --out /tmp/vector_control_request
```

生产参数回归沿用 `test/vector_request_boundary/README.md` 中的命令。独立综合使用 `test/vector_engine/production_synthesis_cases.json` 的 `vector` 项，采用默认综合流程。`report_paths.py` 对综合目录进行连接检查，`validation.json` 保存源码、依赖、证明、周期和综合结果的 SHA256 校验值。
