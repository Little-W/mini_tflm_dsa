# IA 槽号、行数存储与控制条件验证

`ia_loader` 在接收分块描述符的边沿同时保存物理槽号。请求槽号与槽号基值先完成定宽模加，再应用保存的槽号掩码；完整模和采用带 `use_dsp` 属性的普通 RTL 加法。12 种槽号位宽的完整二态输入证明与 446,304 次四态比较通过，其中 1 至 3 位覆盖全部四态输入组合。配置中的存储数量、紧凑格式和槽号掩码共同更新，控制模块和缓存管理模块使用同一份已保存掩码。两个子模块的 `p_precomputed_slot_mask` 参数默认关闭；上层 `ia_loader` 启用该参数并提供配置掩码。

缓存标签的比较分为每组三对输入位和后续归并两部分。有效位读取使用已经确认的查询槽号，配置字段及预取坐标分别比较。行数表采用普通可综合数组描述，分块完成时写入一个槽位。组起始、下一组和连续发送分别提供三个查询索引，表的输出保留完整行数结果，发送状态选择这些结果。`p_indexed_slot_rows` 参数默认关闭，顶层 `ia_loader` 启用索引接口；独立子模块也支持原有并行行数输入。行末条件直接比较行号加一与保存的行数。当前列、预取列与下一组首列分别完成坐标比较，控制条件选择一位比较结果。三个完整列比较结果保留计算边界。有序坐标比较在 FPGA 综合时先形成完整定宽模和，再按三个比特一组比较高位。低位进位包含在该算术结果中。事件仿真和通用配置使用分组进位及公共等式比较器。16 组参数的综合分支完整输入证明与 336,448 次四态比较均通过。宽地址运算使用带 `use_dsp` 属性的普通加法表达式。

配置比较先分别计算普通格式与紧凑格式的容量资格，以及当前组与下一组的物理槽号。模式只选择完整比较结果。紧凑偏移的有效范围通过符号扩展位和低位范围并行判断。综合条件启用这些表达式，事件仿真使用完整算术关系；十组位宽配置的全部二态输入证明和五种位宽共 100,000 次四态检查通过。

计数递增、行基值递增和三项末项索引各自形成完整定宽结果，采用普通算术表达式及 `use_dsp` 属性。寄存器使用既定的状态、握手和更新边沿保存结果；13 组寄存位宽与计数位宽组合的完整输入证明、260,000 次四态比较通过。

加载游标及其下一位置在同一边沿保存，普通组、尾组与预取组分别把下一位置与加载上限比较。复位、组切换和预取进入将游标置零、下一位置置一；分块完成时两者共同前进，并保持各自定宽模运算。普通行与尾行先分别比较查询行数，当前尾行标志只选择一位比较结果。请求、授予及分块启动周期保持不变。

首列标志与列计数器在同一边沿保存，`ps_frame_init` 和 `cache_l1_is_init` 直接读取该标志。复位、初始化与列组回绕共同置位，递增时检查当前计数是否为全一，以保留定宽计数器回绕后的首列语义。

测试分别构造完整 `ia_loader`，展开子模块和存储后检查公开输出及匹配寄存状态。写入数据按端口写使能比较，共享数据按任一端口有效时比较；地址、掩码、写使能和其余公开输出逐周期比较。输入不添加功能限制，验证先对实际游标更新源码证明下一位置等于当前游标加一的模关系，覆盖 1 至 9 位计数，执行两拍复位检查及一步无界归纳。在完整 IA 等价比较中用已证明的表达式代入该冗余状态，再执行两拍组合展开和最多三拍时序归纳。新增游标的状态关系与完整模块的端口及匹配状态分别构成证明的两部分。验证比较行数存储的内部状态和所有公开接口，未使用的并行行数接口不参与内部名称对应。

| 配置 | 主要参数 | 已证明的等价位 |
| --- | --- | ---: |
| 生产 | `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、外部存储、顺序任务、共享写数据 | 12,664 |
| 通用 | `SIZE=16`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=4`、外部存储 | 10,267 |
| 小容量 | `SIZE=4`、`BUS_WIDTH=32`、`COUNT_WIDTH=8`、`CACHE_BLOCKS=2`、本地存储、顺序任务 | 6,224 |
| 合计 | 三种配置均通过 | 29,155 |

生产配置独立综合得到 4,974 个逻辑 LUT、20 个用于分布式存储的标称 LUT，共 4,994 个 LUT，2,536 个触发器、28 个 DSP、2 个 RAMB36 和 1 个 RAMB18。完整连接图中的寄存器间最长组合路径为 10 个单元。相同公共依赖版本的参考实现使用 5,024 个标称 LUT、2,529 个触发器和 28 个 DSP，当前减少 30 个标称 LUT并增加 7 个触发器。完整 SoC 的资源和频率以同一源码的整机综合与静态时序分析结果为准。

结果和源码散列保存在 [measurement.json](measurement.json)。完整模块的时序对应关系使用以下入口验证：

```sh
python3 test/ia_slot_stage/check_load_boundary.py \
  --source-root . --out build/ia_load_boundary
python3 test/ia_slot_stage/run_boundary_formal.py \
  --reference-root /path/to/fixed_reference \
  --source-root . \
  --cursor-proof build/ia_load_boundary/summary.json \
  --out build/ia_slot_stage
```

共享写入的数据排列、四态传播和实际存储写入关系由 `test/ia_shared_write_stage` 与 `test/ia_shared/run_receive_write.py` 检查。

坐标比较器单独验证：

```sh
python3 test/ia_slot_stage/check_ordered_match.py --reference-root /path/to/fixed_reference --source-root . --out build/ia_ordered_match
```

配置比较条件单独验证：

```sh
python3 test/ia_slot_stage/check_configuration.py --source-root . --out build/ia_configuration_conditions
```

完整计数表达式单独验证：

```sh
python3 test/ia_slot_stage/check_counter_expressions.py --reference-root /path/to/fixed_reference --source-root . --out build/ia_counter_expressions
```

请求槽号的完整模加与掩码单独验证：

```sh
python3 test/ia_slot_stage/check_request_slot.py --source-root . --out build/ia_request_slot
```

加载边界的检查还包含 6 种尺寸与寄存位宽的完整二态行数比较，以及 144,000 次事件仿真四态比较。FPGA 综合使用已保存的下一游标和并行行数比较；事件仿真及其他综合配置保留完整行数选择与比较表达式。
