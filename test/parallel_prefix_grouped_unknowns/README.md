# 分段算术的分组四态传播

`parallel_prefix_add` 的 `p_preserve_grouped_unknowns` 参数默认关闭。启用有效的 `p_dsp_split_width` 配置后，可同时将该参数置为 1：已知输入使用低、高两段普通算术及并行高段进位修正，含未知值或高阻态的输入使用原分组加法结果。

参照计算的组间产生、传播条件采用紧凑与或表达式，不保留额外组合节点。二态综合仅保留分段算术路径。默认分组实现、已有分段配置和进位选择配置的参数含义保持不变。

```sh
python3 test/parallel_prefix_grouped_unknowns/run.py --out build/parallel_prefix_grouped_unknowns
```

验证覆盖 21 种位宽、组宽及保留选项组合，包含 2 至 46 位操作数。普通编译与 `SYNTHESIS` 编译共完成 42 项无输入限制的完整和值及最高进位证明，并完成 344064 次四态比较。源码哈希、配置和验证状态保存在指定输出目录的 `summary.json`。
