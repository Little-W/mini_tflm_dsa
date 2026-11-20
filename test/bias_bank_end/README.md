# 偏置银行末端地址保存

`bias_loader_buffer` 在接收装载命令时，使用公共 `parallel_prefix_add` 计算扩展一位的块起点与装载长度之和。末端寄存器的更新条件、初始化、复位和银行选择保持，结果保留全部扩展位。

参考电路由当前完整缓冲区生成，仅把该加法替换为原有扩展位宽的普通 `+` 表达式。测试不依赖额外历史提交。

## 验证

- 10 组完整缓冲区状态和存储端口等价检查，计数宽度包含 1、8、12、29、32，分组容量包含非二次幂 3，并分别启用和关闭请求索引共享。外部输入没有范围假设。
- 40,960 组实际加法边界四态样本。参考表达式的已知结果位保持，部分未知位可解析为已知值；不声明普遍四态等价。
- 392 项完整加载器 DMA、WS/IS 数值与驻留复用检查。
- 生产参数下的完整 `bias_loader` 普通 RTL 映射。资源与源文件摘要保存于 [measurement.json](measurement.json)。

| 项目 | 普通加法对照 | 分组进位计算 |
|---|---:|---:|
| 逻辑 LUT | 1,190 | 1,208 |
| FF | 1,227 | 1,227 |
| RAMB36E1 | 1 | 1 |
| 完整加载器最长组合路径 | 10 | 9 |

偏置银行保留 32,768 bit，WS 缓存保留 512 bit。该结果来自开源映射和寄存器连接分析，实际 Vivado 面积、布线及 150 MHz 时序仍需整机报告确认。

## 复现

```bash
export PYTHONDONTWRITEBYTECODE=1
BIAS_BANK_OUT=/tmp/bias_bank_end
python3 test/bias_bank_end/prove.py --out "$BIAS_BANK_OUT/formal"
python3 test/bias_bank_end/check_four_state.py --out "$BIAS_BANK_OUT/four_state"
python3 test/bias_loader_reuse/run.py --out "$BIAS_BANK_OUT/reuse" --jobs 1
python3 test/bias_bank_end/prepare_measurement.py --out "$BIAS_BANK_OUT/inputs"
python3 scripts/fpga/open_fpga_synth.py \
  --case-config "$BIAS_BANK_OUT/inputs/cases.json" --cases reference current \
  --through pre_lut --out "$BIAS_BANK_OUT/pre"
for version in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "$BIAS_BANK_OUT/pre/$version" --out "$BIAS_BANK_OUT/mapped/$version" \
    --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
    --wire-delay-ps 500 --delay-target-ps 6667
done
python3 test/bias_bank_end/collect_report.py \
  --formal "$BIAS_BANK_OUT/formal" --four-state "$BIAS_BANK_OUT/four_state" \
  --reuse "$BIAS_BANK_OUT/reuse" --inputs "$BIAS_BANK_OUT/inputs" \
  --mapped "$BIAS_BANK_OUT/mapped" --out "$BIAS_BANK_OUT/measurement.json"
```
