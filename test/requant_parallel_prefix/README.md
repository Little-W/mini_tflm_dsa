# 量化并行前缀验证

`requant_round_add` 将四位组的完整传播条件独立归并，低段进位和各组结果位并行形成。`requant_group_last` 用三位比较产生分组相等条件，再归并行结束和复用组结束标志。两个模块保持接口、数值宽度和流水周期。

## 验证范围

`run.py` 比较提交 `d035fedc` 中的实现与当前 RTL。舍入加法覆盖八组总位宽和低段位宽，行结束比较覆盖五组坐标位宽；每组分别检查普通模式和 `SYNTHESIS` 模式。完整输入等价检查之外，还对零、全一、相同、相反以及含 X/Z 的操作数执行四态比较。

父模块逐周期检查覆盖两种参数读取时序的完整 `requant_compute_lane` 和四通道小容量的完整 `vec_requant`，比较全部公开输出，外部输入不附加约束。

十六通道生产配置采用组合替换证明：逐文件确认父模块与其余依赖保持相同，展开实际实例并确认两份舍入模块使用 35/18 位参数、行比较使用 16 位参数，且对应 helper 与递归依赖均为无状态组合逻辑。上述参数的完整输入证明覆盖各次调用，因此替换保持任意输入序列下的全部公开周期行为。生产配置保留两个物理量化通道、五百一十二行输入容量和全部参数存储。

异步复位转换后的原始寄存状态单独建立对应关系，每个对应关系也必须通过等价证明。组合信号 `row_offset_in_group` 的未使用高位可由综合删除，因此不将该内部别名作为独立比较端点；其所有公开使用结果仍在检查范围内。

## 运行方法

```bash
python test/requant_parallel_prefix/run.py --out build/requant_parallel_verified --jobs 2
python test/requant_parallel_prefix/measure.py --out build/requant_parallel_measure
python test/requant_compute_lane/run.py --out build/requant_parallel_numeric \
  --variants generic fpga --delayed-parameters 0 1 --jobs 2
```

`validation.json` 保存完整输入、四态与父模块检查结果及源码哈希。`numeric_validation.json` 保存独立量化通道的数值、暂停、清空、复位和尾部通道测试结果。`measurement.json` 保存相同工具配置下的完整模块资源和实际连接路径。

## 资源与组合级数

映射参数为 `physical-cost`、目标 6667 ps、布线代价 300 ps、最大 LUT 输入数 8。

| 完整模块 | 修改前逻辑 LUT | 当前逻辑 LUT | 修改前寄存器间最长级数 | 当前寄存器间最长级数 |
| --- | ---: | ---: | ---: | ---: |
| `requant_compute_lane` | 441 | 442 | 10 | 9 |
| `vec_requant`，两个物理通道 | 2362 | 2363 | 11 | 10 |

生产配置中，`s16_mode` 到 `rounded_q` 的路径由 11 级缩短到 6 级，`tile_row` 到 `load_offset` 的路径由 11 级缩短到 9 级。1290 个寄存器、14 个 DSP、64 个 LUTRAM、14 个 SRL 和 19 个 RAMB18 保持不变。
