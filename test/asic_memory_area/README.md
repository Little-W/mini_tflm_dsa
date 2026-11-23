# 完整 NPU 的原生 ASIC 面积比较

`scripts/asic/compare_memory_area.py` 对参考源码和当前源码分别运行 `IA_COMPACT_ENABLE=0`、`1`，共进行四次独立的 Design Compiler 综合。四项使用相同的标准单元库、SRAM 库、源文件准备程序、综合选项和 150 MHz 约束。计算阵列为 16×16，AXI 数据宽度为 64 位，共享存储为 7×8192 B，向量计算使用 16 个 PE。

每项先保存实际 DC 文件列表中的 RTL、头文件和 SRAM 封装，再执行 `prepare_dc_sources.py`。同一版本的两种 IA 配置必须具有相同的源文件摘要。输入文件、准备后的文件、统一综合流程、工艺库和输出报告均记录 SHA-256。综合读取保存的副本，源代码中的存储资源选择保持原样。

## 执行

```bash
python3 scripts/asic/compare_memory_area.py \
  --reference-root /path/to/source_820c \
  --source-root /path/to/current_source \
  --std-db /path/to/scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db \
  --libs /path/to/sram_databases \
  --out /path/to/results/memory_area
```

SRAM 目录需要包含 `RAMTP128X16_tt_1p10v_1p10v_25c.db` 和 `RAMTP1024X16_tt_1p10v_1p10v_25c.db`。也可以使用现有 ASIC 流程的 `STD_DB_PATH`、`STD_DB_LIST`、`MEM_DB_PATH`、`MEM_DB_LIST`、`SYN_STD_LIB_NAME` 和 `SYN_OPER_CONDITION` 环境变量。`--std-db` 可以重复传入；各项综合共享相同的库列表。默认使用 `compile_ultra -no_autoungroup`，`--compile-mode standard` 可选择仓库的普通综合设置。

约束沿用 `asic/synthesis/constraints/npu_top.sdc`：时钟周期为 6.666667 ns，建立时间不确定度为周期的 10%，输入和输出的最大延迟为周期的 20%。两个版本均使用同一份约束。

真实综合要求 `dc_shell` 和全部 `.db` 文件可用。工具或库缺失时，程序返回失败。`--prepare-only` 只保存输入和命令，输出状态为 `prepared`，不生成面积或时序数值。

## 输出

`comparison.json` 记录四项配置和同一 IA 模式下的版本差值。状态依次表示准备完成、正在综合和测量完成；执行失败时保存失败项、原因及已经完成的结果。`dc_executed` 记录综合调用情况。

每项必须保留 18 个非空产物，包括展开及映射后的 DDC、完整综合网表、SDC、面积报告、建立时间和保持时间报告、设计及约束检查、宏实例清单，以及 `memory_metrics.tsv`。

面积从实际映射叶单元的库属性逐个累计，包含以下范围：

| 范围 | 包含内容 |
| --- | --- |
| `whole` | 完整 NPU |
| `kernel` | `kernel_loader_buffer` 及其全部子模块 |
| `bias` | `bias_loader_buffer` 及其全部子模块 |
| `requant` | 完整 `vec_requant`，包括成对装载、读半字选择及相关控制 |
| `requant_group` | `requant_group_buffer`，包括 SRAM 读选择和队列控制 |
| `product_amount` | 两个量化移位参数存储实例及其内部读写逻辑 |

每个范围分别记录标准单元面积、SRAM 宏面积、总单元面积、叶单元数量及 SRAM 容量。面积单位采用加载工艺库的单位。完整 NPU 的累计值还须与 DC `report_area` 的总单元面积一致。缺少映射库单元、存储子层次、完整时序结果或时钟周期不一致时，程序返回失败。

`product_amount` 仅统计存储实例内部的单元。移位参数打包产生的装载寄存器、半字选择和写入控制由 `requant` 及 `whole` 统计。各范围存在包含关系，表中的子项用于定位面积变化，不应相加作为完整 NPU 面积。

时序裕量由工具返回的路径逐项比较并取最小值。`setup_met` 和 `hold_met` 分别表示 150 MHz 约束下的建立时间与保持时间结果。负裕量会作为实际测量结果保存，供版本比较使用。

## 入口检查

```bash
python3 -m unittest discover -s test/asic_memory_area -p 'test_*.py' -v
```

这些测试使用临时模拟报告检查四项任务调度、参数一致性、源码副本、报告解析、必需产物和执行状态。Tcl 测试执行真实的面积累计代码，并检查父子层次及多条乱序路径。临时目录在测试结束后删除，测试不执行 Design Compiler，也不提供 ASIC 面积结论。
