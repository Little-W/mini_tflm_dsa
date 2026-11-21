# IA 槽号保存与控制条件验证

`ia_loader` 在接收分块描述符的边沿同时保存物理槽号。配置中的存储数量、紧凑格式和槽号掩码共同更新，控制模块和缓存管理模块使用同一份已保存掩码。两个子模块新增的 `p_precomputed_slot_mask` 参数默认关闭；上层 `ia_loader` 启用该参数并提供配置掩码。

缓存标签的比较分为每组三对输入位和后续归并两部分。有效位读取使用已经确认的查询槽号，配置字段及预取坐标分别比较。组起始和组内连续发送时需要的下一槽行数并行读取，发送状态只选择完整行数结果。宽地址运算使用带 `use_dsp` 属性的普通加法表达式。

上述处理保持各个公开输出和状态寄存器的周期关系。测试从固定参考版本和待测版本分别构造完整 `ia_loader`，展开子模块和存储后检查全部匹配信号；使用一拍组合等价检查和最多三拍时序归纳，输入不添加功能约束。

| 配置 | 主要参数 | 已证明的等价位 |
| --- | --- | ---: |
| 生产 | `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、外部存储、顺序任务、共享写数据 | 14,038 |
| 通用 | `SIZE=16`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=4`、外部存储 | 10,054 |
| 小容量 | `SIZE=4`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=2`、本地存储、顺序任务 | 5,960 |
| 合计 | 三种配置均通过 | 30,052 |

生产配置独立综合得到 6,455 个逻辑 LUT、3,137 个触发器、16 个 DSP、2 个 RAMB36 和 1 个 RAMB18。完整连接图中的寄存器间最长组合路径为 11 个单元，尚未满足 10 级要求。实际完整 SoC 的资源和频率以同一源码的整机综合与静态时序分析结果为准。

结果和源码散列保存在 [measurement.json](measurement.json)。完整模块的时序等价验证使用以下入口：

```sh
python3 test/ia_slot_stage/run_formal.py \
  --reference-root /path/to/fixed_reference \
  --source-root . \
  --out build/ia_slot_stage
```

共享写入的数据排列、四态传播和端口保持由 `test/ia_shared_write_stage` 与 `test/ia_shared/run_receive_write.py` 检查。
