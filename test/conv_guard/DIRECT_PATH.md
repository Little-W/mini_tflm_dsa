# 读取保护器的直接传输条件

直接传输使用请求格式与 4 KiB 页范围条件。卷积的四个分配区间独立检查，并由卷积处理状态使用。页范围计算把 ARLEN 与页内地址的反码按两个四位字段并行比较，保留全部长度和地址编码的行为。

## 固定配置结果

参考提交为 `2f06471c`，配置为 32 位地址、64 位数据、四笔读取事务及启用 GEMM 页拆分。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 870 | 851 |
| 触发器 | 392 | 392 |
| CARRY4 | 73 | 73 |
| 寄存器间最长组合单元数 | 10 | 10 |
| `s_arready` 最长组合单元数 | 7 | 6 |
| 含全部公开端口的最长组合单元数 | 11 | 12 |

模块保持全部公开输出周期。整机面积与组合深度由完整 `soc_top` 测量给出。

## 验证

七组完整状态等价检查覆盖 16、32、33、40 位地址和 16 至 256 位数据总线。十一组范围表达式证明遍历全部输入编码。32/64 位数据总线及两种页拆分配置各比较 50,000 个周期。跨页功能测试完成 192 次读取、192 次写入，覆盖四笔并发事务和读写错误。

```sh
python3 test/conv_guard/run_control_formal.py --out build/guard_direct/formal --reference-ref 2f06471c
python3 test/conv_guard/range_equivalence.py --out build/guard_direct/range --reference-ref 2f06471c
python3 test/conv_guard/compare.py --out build/guard_direct/compare --reference-ref 2f06471c --verilator verilator-modern
python3 test/dma_page_guard/run.py --guard-only --out build/guard_direct/page --verilator verilator-modern
```

[固定参数与检查结果](direct_path_measurement.json) 保存参数、源码摘要、形式结果和逐位连接路径。
