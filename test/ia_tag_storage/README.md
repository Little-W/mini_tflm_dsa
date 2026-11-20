# IA 标签块存储

`ia_loader` 的标签数组使用块存储属性。请求读取和预取读取继续在原有时钟沿采样，标签写入、有效位、缓存刷新和查询冲突处理保持原有周期。

生产参数使用 64 个标签，每个标签 61 位，逻辑容量为 3,904 位。两个同步读取端口由综合工具分配为两个块存储副本，两个副本接收相同写入。有效位独立保存，因此复位和缓存刷新无需清除标签数据阵列。

## 检查结果

`measurement.json` 记录参考提交 `f0f83e1d` 和当前源码的同参数综合结果及源码散列值。完整 IA 加载器的 12,132 个状态和输出比较位通过形式验证，输入未施加约束。

| 资源或路径 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 5,913 | 5,821 |
| 分布式存储 LUT | 176 | 8 |
| 两类 LUT 合计 | 6,089 | 5,829 |
| 触发器 | 3,101 | 2,979 |
| DSP48E1 | 8 | 8 |
| RAMB36E1 | 0 | 2 |
| 寄存器间最大组合单元数 | 13 | 13 |
| 全部组合路径最大单元数 | 14 | 13 |

测量使用 Yosys 0.71+40、`synth_xilinx`、`xc7` 单元库及相同端口与参数。器件时序需要结合布局和布线延迟检查。

## 复现

```sh
python3 test/ia_tag_storage/prepare_measurement.py --reference f0f83e1d --out /tmp/ia_tag_storage
python3 scripts/fpga/open_fpga_synth.py --case-config /tmp/ia_tag_storage/cases.json --cases reference current --out /tmp/ia_tag_storage/native
python3 test/ia_arbiter_request/run_ia_formal.py --reference-rev f0f83e1d --cases soc --out /tmp/ia_tag_storage/formal
```
