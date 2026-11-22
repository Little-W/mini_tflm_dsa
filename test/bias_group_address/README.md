# 偏置组起始地址验证

`npu_output_pipeline.sv` 使用统一的分组借位运算生成偏置整组起始地址。低位计算行数差值，各高位字节并行准备减一结果，再根据低位借位及前序零组选择输出。目标掩码由每四位的零判断生成。

测试从实际 RTL 中抽取该组合逻辑，验证以下完整定宽结果：

```systemverilog
group_base = REG_WIDTH'(exec_m) - REG_WIDTH'(group_rows_target);
target_mask = REG_WIDTH'(group_rows_target) - REG_WIDTH'(1);
```

`exec_m` 保持实际接口的 32 位类型。参数测试覆盖 `REG_WIDTH` 为 1、2、3、4、7、8、9、15、16、17、31、32、33、47、48、63、64，以及 `IS_BIAS_VALID_W` 在短字段、4 位和 8 位边界、小于、等于、大于 `REG_WIDTH` 时的情况，共 110 组。

## 已完成结果

| 检查 | 结果 |
| --- | --- |
| 完整已定义输入证明 | 110 组参数通过；97 个外部输入位均无约束 |
| 地址与掩码结果 | 完整保留模减法结果 |
| 分组语句比较 | 标识符转换后，实际分组运算、类型与位选择保持相同 |
| 四态比较 | 11,240 组输入、5512 个并行输出位、61,954,880 个位比较通过 |
| 未知值覆盖 | 10,208 组输入含 X/Z，10,144 组参考输出含未知位 |

四态比较逐位使用 `!==`，参考对象为原分组借位运算。源码和日志 SHA-256 见 `validation.json`。

```bash
python test/bias_group_address/run.py \
  --reference-source /path/to/reference/npu_top.sv \
  --source-root . \
  --out build/bias_group_address
```
