# 尾行、尾列与块位置验证

`vec_requant` 计算当前块的有效通道、有效行和复用组所需行数。块起点保持完整位宽的左移与截断语义。通道数为二的幂次且寄存器宽度足够时，高位比较与尾部低位选择并行完成；其他参数采用饱和差值。

```bash
python test/requant_tail_count/run_formal.py --out build/requant_tail_count
python test/requant_tail_count/check_group_last.py --out build/requant_group_last
```

检查比较有效行列数、复用组基址、下一块坐标、块结束标志和参数复用条件。完整尺寸、块坐标、复用组配置与模式位均可自由变化。十五个配置覆盖二的幂次和一般通道数，以及 4、16、32、64 位寄存器宽度。

`run_formal.py` 按通道起点声明及 `lane_need_q` 的保存语句定位完整组合逻辑，并随同读取实际调用的完整辅助模块。综合定义 `SYNTHESIS=1` 参与检查，模块层次完整性由 `hierarchy -check` 验证。两份辅助模块分别命名，所有结果统一与参考表达式比较。

`--source-root` 可指定固定源码目录。参考源码默认使用提交 `2297cb12`，可用 `--reference-rev` 指定其他提交，或使用 `--reference-root` 读取独立目录。每次检查都保存源码摘要、参数配置和日志摘要。

`check_group_last.py` 读取独立的 `requant_group_last.sv` 及其完整模块依赖，逐个比较行结束和复用组结束两个输出。1、4、8、16 位坐标分别包含随机值、全零、全一、相等行及掩码边界，并注入 `X` 和 `Z`。固定种子为 `20261125`，共完成 160,000 次四态比较。

当前四种位宽的检查结果与输入文件摘要见 [group_last_validation.json](group_last_validation.json)。
