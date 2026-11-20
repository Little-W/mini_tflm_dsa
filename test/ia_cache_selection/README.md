# IA 缓存数据与行数选择

紧凑写入先生成各输入字节的模 256 偏移结果，再按列位置排列。排列后的写掩码选择对应字节；无效列输出零数据对应的紧凑字节。S16 数据、外部写入掩码、写入保持行为和接口周期保持一致。

行发射逻辑共享下一存储位置的行数选择结果。开始发射时选取起始位置的后继，连续发射时选取当前寄存位置的后继；已保存的发射状态和单行存储块切换行为保持一致。

## 检查结果

参考版本为 `f0f83e1d`，具体源码散列值、参数和命令保存在 `measurement.json`。

- 7 组形式检查通过，共 19,840 个状态和输出比较位，输入未施加约束。参数覆盖本地和外部存储、4/8/16 列、8/16 位数据以及 8/32/64/128/256 位总线。
- IA 加载器 39 个公开输出逐周期比较通过，共 180,122 周期和 903,952 个数值。
- 57,344 字节共享存储数值检查通过，共 4,681,255 周期、15,022,624 个数据数值及 74,900,080 次周期数据检查。包含 256 种 S8 偏移、全部 65,536 种 S16 位模式、交错 IA/PS 访问、写入掩码和跨字写入。

## 模块综合

同一生产参数、同一 Yosys 0.71+40 工具下，`ia_loader_cache_mgr` 的结果如下。

| 资源或路径 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,917 | 1,748 |
| 分布式存储 LUT | 8 | 8 |
| 触发器 | 354 | 354 |
| DSP48E1 | 8 | 8 |
| 寄存器间最大组合单元数 | 11 | 11 |
| 全部组合路径最大单元数 | 11 | 11 |

生产参数使用 16 列、64 位总线、32 个物理缓存块、外部存储和 9 位紧凑偏移。存储容量及输入输出并行规模保持一致。

## 复现

```sh
python3 test/ia_write_output_depth/run_formal.py --reference f0f83e1d --cases production generic_s4_b32_d8_c2_e0 generic_s8_b64_d16_c4_e0 generic_s16_b8_d16_c32_e1 generic_s16_b32_d16_c32_e1 generic_s16_b128_d16_c32_e1 generic_s16_b256_d16_c32_e1 --out /tmp/ia_cache_selection/formal
python3 test/ia_write_output_depth/run_numeric.py --reference f0f83e1d --cases interface shared --out /tmp/ia_cache_selection/numeric
python3 test/ia_write_output_depth/prepare_measurement.py --reference f0f83e1d --out /tmp/ia_cache_selection/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config /tmp/ia_cache_selection/inputs/cases.json --cases reference current --out /tmp/ia_cache_selection/native
```
