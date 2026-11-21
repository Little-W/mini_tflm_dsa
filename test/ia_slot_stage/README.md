# IA 槽号、行数存储与控制条件验证

`ia_loader` 在接收分块描述符的边沿同时保存物理槽号。配置中的存储数量、紧凑格式和槽号掩码共同更新，控制模块和缓存管理模块使用同一份已保存掩码。两个子模块的 `p_precomputed_slot_mask` 参数默认关闭；上层 `ia_loader` 启用该参数并提供配置掩码。

缓存标签的比较分为每组三对输入位和后续归并两部分。有效位读取使用已经确认的查询槽号，配置字段及预取坐标分别比较。行数表采用普通可综合数组描述，分块完成时写入一个槽位。组起始、下一组和连续发送分别提供三个查询索引，表的输出保留完整行数结果，发送状态选择这些结果。`p_indexed_slot_rows` 参数默认关闭，顶层 `ia_loader` 启用索引接口；独立子模块也支持原有并行行数输入。行末条件直接比较行号加一与保存的行数。当前列、预取列与下一组首列分别完成坐标比较，控制条件选择一位比较结果。三个完整列比较结果保留计算边界。有序坐标助手使用公共逐位进位比较器，其 16 组参数的完整输入证明与 336,448 次四态比较均通过。宽地址运算使用带 `use_dsp` 属性的普通加法表达式。

首列标志与列计数器在同一边沿保存，`ps_frame_init` 和 `cache_l1_is_init` 直接读取该标志。复位、初始化与列组回绕共同置位，递增时检查当前计数是否为全一，以保留定宽计数器回绕后的首列语义。

测试分别构造完整 `ia_loader`，展开子模块和存储后检查公开输出及匹配寄存状态。写入数据按端口写使能比较，共享数据按任一端口有效时比较；地址、掩码、写使能和其余公开输出逐周期比较。输入不添加功能限制，验证使用两拍组合展开和最多三拍时序归纳。验证比较行数存储的内部状态和所有公开接口，未使用的并行行数接口不参与内部名称对应。

| 配置 | 主要参数 | 已证明的等价位 |
| --- | --- | ---: |
| 生产 | `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、外部存储、顺序任务、共享写数据 | 12,418 |
| 通用 | `SIZE=16`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=4`、外部存储 | 10,118 |
| 小容量 | `SIZE=4`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=2`、本地存储、顺序任务 | 6,081 |
| 合计 | 三种配置均通过 | 28,617 |

生产配置独立综合得到 5,124 个逻辑 LUT、20 个用于分布式存储的标称 LUT，共 5,144 个 LUT，2,528 个触发器、16 个 DSP、2 个 RAMB36 和 1 个 RAMB18。完整连接图中的寄存器间最长组合路径为 10 个单元。完整 SoC 的资源和频率以同一源码的整机综合与静态时序分析结果为准。

结果和源码散列保存在 [measurement.json](measurement.json)。完整模块的时序对应关系使用以下入口验证：

```sh
python3 test/ia_slot_stage/run_formal.py \
  --reference-root /path/to/fixed_reference \
  --source-root . \
  --out build/ia_slot_stage
```

共享写入的数据排列、四态传播和实际存储写入关系由 `test/ia_shared_write_stage` 与 `test/ia_shared/run_receive_write.py` 检查。

坐标比较器单独验证：

```sh
python3 test/ia_slot_stage/check_ordered_match.py --reference-root /path/to/fixed_reference --source-root . --out build/ia_ordered_match
```
