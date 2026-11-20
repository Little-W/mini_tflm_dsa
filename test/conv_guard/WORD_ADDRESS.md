# 读取保护器的字节地址生成

`conv_axi_read_guard` 将字节地址分为总线字内偏移和上部地址。上部地址预先计算加一结果，低位偏移产生的进位只负责选择上部地址。该结构保持完整地址宽度的模加行为，包括地址回绕、单字节读取、整字读取和 GEMM 直接转发。

## 综合与组合路径

比较使用 `ADDR_W=32`、`DATA_W=64`、`SPLIT_GEMM_4K=1`、`READ_OUTSTANDING=4`，参考提交为 `cd0455b`。资源统计和路径分析使用同一份完整模块综合网表。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 871 | 870 |
| 触发器 | 392 | 392 |
| CARRY4 | 72 | 73 |
| 寄存器间最长组合路径 | 10 | 10 |
| 含公开端口的最长组合路径 | 14 | 11 |
| 至 `m_araddr` 的最长组合路径 | 14 | 10 |
| 至 `s_arready` 的最长组合路径 | 10 | 7 |

路径分析按实际连接逐位计算；公开端口使用仅存在于分析副本的零深度边界。输出地址计算缩短后，整个模块重新映射的请求就绪路径也随之缩短。组合单元数用于比较结构，150 MHz 时序使用完整器件布局布线结果确认。

## 验证

七组完整状态和输出等价证明共覆盖 5,061 位，外部输入不增加约束。参数覆盖 16、32、33、40 位地址，16、32、64、128、256 位数据总线，以及两种 `SPLIT_GEMM_4K` 设置。

32/64 位总线与两种页拆分设置分别比较 50,000 个周期的全部公开输出，共 200,000 个周期，包含配置更新、复位、页尾地址和长突发。所有公开输出周期保持相同。

实际分配区间测试通过 10 条请求、46 拍返回数据、119 次字节读取和两次读错误检查。跨页测试通过 192 次读取、192 次写入、读写各 10 次错误和四笔并发事务，共 22,868 个周期。

源码、网表、仿真程序的 SHA-256 和详细路径保存在 [word_address_measurement.json](word_address_measurement.json)。

```bash
python3 test/conv_guard/run_control_formal.py \
  --out build/guard_word_address/formal --reference-ref cd0455b
python3 test/conv_guard/compare.py \
  --out build/guard_word_address/compare --reference-ref cd0455b \
  --verilator verilator-modern
python3 test/conv_guard/synthesis.py \
  --out build/guard_word_address/reference --reference-ref cd0455b --data-width 64
python3 test/conv_guard/synthesis.py \
  --out build/guard_word_address/current --data-width 64
python3 test/conv_guard/measure_paths.py \
  --reference build/guard_word_address/reference \
  --current build/guard_word_address/current --out build/guard_word_address/paths.json
python3 test/dma_page_guard/run.py --guard-only \
  --out build/guard_word_address/page --verilator verilator-modern
python3 test/conv_guard/run.py
```
