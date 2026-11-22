# 向量算术与写回组合逻辑

`run_formal.py` 检查实际生产表达式和完整寄存模块。结果偏移保留六十四位模运算，在配置允许的 S8 偏移与激活范围内，与独立的完整加法和有符号限幅模型比较。最近偶数舍入保留保护位、舍弃位的非零状态和输入、中间寄存器的功能参数。

读取地址由三项输入生成完整三十四位结果。写回检查同时覆盖公开握手、地址、数据、掩码和内部状态的周期关系。

## 检查范围

| 检查对象 | 配置与范围 | 形式检查数量 |
| --- | --- | ---: |
| 结果偏移及限幅 | 64 位有符号结果、三个 S8 配置字段，共 88 位输入和 34 位输出 | 1 |
| 最近偶数舍入 | 输入寄存和中间寄存的全部四种组合 | 4 |
| 完整写回模块 | TILE/总线宽度为 8/32、16/32、16/64、16/128、32/64 | 5 |
| 读取地址 | 32 位基地址、32 位偏移、16 位通道，共 80 位任意输入，完整 34 位结果 | 1 |

偏移阈值使用同一已接受配置的保存关系。舍入和写回使用指定参考提交比较完整模块；地址使用独立数学模型。输出目录的 `summary.json` 保存源文件、参考文件、证明脚本和日志的 SHA256。

## 运行

```bash
python3 test/vector_boolean_logic/run_formal.py \
  --reference ef0dc75 --out build/vector_boolean_formal
```

`--only offset`、`--only round`、`--only writeback` 和 `--only address` 分别选择单类检查。

`run_writeback.py` 另外提供逐字节数值检查，覆盖字节和数据字请求、各个总线内起始偏移、不同请求长度、随机背压与错误响应：

```bash
python3 test/vector_boolean_logic/run_writeback.py \
  --verilator verilator --out build/vector_boolean_writeback
```
