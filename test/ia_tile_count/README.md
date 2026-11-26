# IA 配置分块数验证

`ia_loader` 根据全局归约长度、当前输入长度和已保存长度选择取整来源。全局长度是否为零由六位分组分别计算，随后选择实际长度。移位后的整数部分通过四位分组的普通定宽加法接收余数进位，各组进位条件并行形成。分块数仍在原有配置边沿保存。

`conditional_increment` 的 `p_native_groups=1` 选择组内普通加法；默认参数保留逐位并行计算。`zero_reduce` 的 `p_group_width` 指定需要保留的分组宽度，默认参数直接归并全部输入。两个模块均使用可综合 RTL，由工具推断逻辑和进位资源。

## 验证

`run.py` 直接提取生产 RTL 的来源选择与完整定宽算术，证明全部输入位的结果相等，输出包含最高进位。同时检查父模块剩余功能文本完全一致，确保寄存器更新、接口和其他数据路径保持原有行为。

检查覆盖 7、16、17、32、64 位数据，以及 `SIZE=1/3/4/8/16/32` 的组合，共 8 组参数。每组运行 41,536 次四态比较，共 332,288 次，覆盖零值、上边界、所有来源状态及 `X/Z` 输入。共享条件加一模块的默认参数另由 `test/frame_row_tiles/run.py` 检查。

## 寄存器间完整表达式测量

测量包含实际来源选择、余数条件、分组进位和完整结果，输入、输出两侧采用相同寄存器。两份设计使用相同的 `physical-cost` 映射、6,667 ps 延迟目标和 300 ps 连线代价。

| 指标 | 参考实现 | 当前实现 |
|---|---:|---:|
| 名义 LUT 数量 | 51 | 69 |
| 最长寄存器间组合路径 | 13 | 8 |

完整 IA 模块与 SoC 的资源及路径由整机映射报告统计。组合级数描述连接图中的结构深度，目标器件的工作频率还需布局布线时序分析。

## 复现

```bash
python3 test/ia_tile_count/run.py --out build/ia_tile_count/verification
python3 test/ia_tile_count/measure.py --out build/ia_tile_count/measurement
python3 test/frame_row_tiles/run.py --out build/ia_tile_count/shared_increment
```

参考提交为 `1470a963`。`validation.json` 保存全部输入证明、四态测试和父模块检查结果；`measurement.json` 保存实际映射输入、资源、路径及文件摘要。
