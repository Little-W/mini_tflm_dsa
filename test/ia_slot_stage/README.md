# IA 槽号、行数存储与控制条件验证

`ia_loader` 在接收分块描述符的边沿保存物理槽号。请求槽号与槽号基值先进行定宽模加，再应用已保存掩码。配置中的存储数量、紧凑格式和槽号掩码共同更新，控制模块与缓存管理模块读取同一份掩码。

`p_precomputed_slot_mask` 控制子模块是否使用提供的槽号掩码。`p_indexed_slot_rows` 控制行数表的索引接口；组起始、下一组和连续发送各自提供查询索引，发送状态选择完整行数结果。独立子模块保留对应的并行行数接口。

有序坐标比较由 `ia_ordered_coordinate_equal.sv` 实现。低位加法产生进入高位的进位，高位调用公共 `add_equal` 检查模加关系。全部配置采用相同功能结构，仿真保留通用分组进位的四态传播。

配置比较分别计算普通格式和紧凑格式的容量资格，以及当前组与下一组的物理槽号。计数递增、行基值递增和末项索引使用明确位宽的普通算术表达式。首列标志、加载游标及其下一位置与各自计数器共同更新；初始化、组切换和定宽回绕均参与验证。

## 当前独立检查结果

| 检查对象 | 形式证明 | 四态检查 |
| --- | ---: | ---: |
| 有序坐标高位比较 | 8 种位宽与低位参数，分别使用 ASIC 和 FPGA 配置，共 16 组 | 168,224 次 |
| 配置范围、容量与槽号 | 10 组位宽参数 | 100,000 次 |
| 7 个计数和索引结果 | 13 组寄存位宽与计数位宽 | 260,000 次 |
| 请求槽号模加与掩码 | 12 种槽号位宽 | 446,304 次 |
| 下一游标及行数关系 | 9 组游标位宽与 6 组行数参数 | 144,000 次 |
| 边界与行数选择 | 15 组参数 | 100,000 次 |

槽号检查在 1 至 3 位参数下遍历全部四态输入。其余检查覆盖随机输入、X/Z 控制与数据、窄计数、高位截断和模运算回绕。游标保存关系先检查复位，再执行一步无界归纳，后续外部输入保持自由。

```bash
python3 test/ia_slot_stage/check_load_boundary.py \
  --source-root . --out build/ia_load_boundary
python3 test/ia_request_stage/check_boundary.py \
  --source-root . --out build/ia_boundary_selection
python3 test/ia_slot_stage/check_ordered_match.py \
  --reference-root /path/to/reference --source-root . --out build/ia_ordered_match
python3 test/ia_slot_stage/check_configuration.py \
  --source-root . --out build/ia_configuration_conditions
python3 test/ia_slot_stage/check_counter_expressions.py \
  --reference-root /path/to/reference --source-root . --out build/ia_counter_expressions
python3 test/ia_slot_stage/check_request_slot.py \
  --source-root . --out build/ia_request_slot
```

参考目录需要包含所比较版本的实际 RTL；坐标检查同时读取该目录中的公共算术依赖。每项运行保存模型、完整参数、源码及日志摘要。当前结果汇总在 [validation.json](validation.json)。完整 IA 数据与状态检查见 [请求捕获验证](../ia_lookup_capture/README.md)，直接和寄存请求接口的条件验证见 [加载许可验证](../ia_reuse_admission/README.md)。
