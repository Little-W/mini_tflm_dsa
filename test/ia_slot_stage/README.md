# IA 槽号保存与控制条件验证

`ia_loader` 在接收分块描述符的边沿同时保存物理槽号。配置中的存储数量、紧凑格式和槽号掩码共同更新，控制模块和缓存管理模块使用同一份已保存掩码。两个子模块的 `p_precomputed_slot_mask` 参数默认关闭；上层 `ia_loader` 启用该参数并提供配置掩码。

缓存标签的比较分为每组三对输入位和后续归并两部分。有效位读取使用已经确认的查询槽号，配置字段及预取坐标分别比较。组起始和组内连续发送时需要的下一槽行数并行读取，发送状态选择完整行数结果。宽地址运算使用带 `use_dsp` 属性的普通加法表达式。

测试分别构造完整 `ia_loader`，展开子模块和存储后检查公开输出及匹配寄存状态。写入数据按端口写使能比较，共享数据按任一端口有效时比较；地址、掩码、写使能和其余公开输出逐周期比较。输入不添加功能限制，验证使用两拍组合展开和最多三拍时序归纳。

| 配置 | 主要参数 | 已证明的等价位 |
| --- | --- | ---: |
| 生产 | `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、外部存储、顺序任务、共享写数据 | 11,469 |
| 通用 | `SIZE=16`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=4`、外部存储 | 10,143 |
| 小容量 | `SIZE=4`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=2`、本地存储、顺序任务 | 6,127 |
| 合计 | 三种配置均通过 | 27,739 |

生产配置独立综合得到 5,552 个逻辑 LUT、2,847 个触发器、16 个 DSP、2 个 RAMB36 和 1 个 RAMB18。完整连接图中的寄存器间最长组合路径为 11 个单元，尚未满足 10 级要求。完整 SoC 的资源和频率以同一源码的整机综合与静态时序分析结果为准。

结果和源码散列保存在 [measurement.json](measurement.json)。完整模块的时序对应关系使用以下入口验证：

```sh
python3 test/ia_slot_stage/run_formal.py \
  --reference-root /path/to/fixed_reference \
  --source-root . \
  --out build/ia_slot_stage
```

共享写入的数据排列、四态传播和实际存储写入关系由 `test/ia_shared_write_stage` 与 `test/ia_shared/run_receive_write.py` 检查。
