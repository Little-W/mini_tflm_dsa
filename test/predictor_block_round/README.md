# 预测器配置取整

配置分块数使用 33 位的 `cfg_points_q + block_rows_q - 1` 进行向上取整。
当前实现先将三项运算压缩为两个操作数，再计算低 16 位结果，以及高 17 位的两种进位结果。
低位进位只选择已经算出的高位结果。完整的 33 位结果继续使用原有移位及配置接收边沿。

参考版本为 `626902ef86c6f55471510ca9fd5d122a390e0b8e`。
参考预测器 SHA-256 为 `8a0526a7cd5f3f700112316c57e90426983a7b9013fbbfd136db9fcdd19dc745`，
当前源码为 `015474bfdc1c6e41f6953ee1237c2e38d1fd82e8dac90b14e52c3b9c8b0ea9e6`。

## 验证

`run.py` 从实际源码提取运算，核对其余 RTL 的语法内容保持相同。
全部 64 位输入和完整 33 位结果通过形式比较，输入允许为任意值。
独立几何模型测试覆盖 33 组配置和 13,226 个下一次访问秩值。
全部公开输出在 206,076 个周期内与参考版本相同。

官方 FPGA 原语模型下的窗口测试通过 422 个请求接收、418 个完成、4 个复位取消、
4,457 个数值检查及 19 个预期错误。
连续驻留窗口的 512 个响应耗时 1,534 周期，最大响应间隔为 3 周期。
请求、响应、AXI 和忙状态的 1,545 行记录与参考版本逐周期相同。

## 独立映射

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 1,780 | 1,844 |
| 触发器 | 1,128 | 1,128 |
| DSP48E1 | 13 | 13 |
| CARRY4 | 149 | 154 |
| 寄存器到 `cfg_blocks_q` | 16 级 | 12 级 |
| 完整预测器最长寄存器路径 | 16 级 | 14 级 |

测量使用完整预测器和 Xilinx 7 系列原语，保留 DSP 内部组合运算的级数。
当前综合最大驻留内存为 229,632 KiB。
完整资源、逐位连接路径和源码摘要保存在 `docs/data/fpga_predictor_block_round.json`。

## 运行

```bash
python3 test/predictor_block_round/run.py --reference 626902ef --out build/block_round/formal
python3 test/conv_replacement/predictor_test.py --reference-ref 626902ef --verilator verilator-modern --build build/block_round/numeric --out build/block_round/numeric/summary.json
python3 test/window_dma/run.py --out build/block_round/fpga --verilator verilator-modern --jobs 1 --fpga --reference-ref 626902ef
python3 test/conv_replacement/predictor_synthesis.py --reference-ref 626902ef --out build/block_round/synthesis/reference
python3 test/conv_replacement/predictor_synthesis.py --out build/block_round/synthesis/current
python3 test/predictor_block_round/paths.py --reference build/block_round/synthesis/reference --current build/block_round/synthesis/current --proof build/block_round/formal/summary.json --out build/block_round/paths.json
```
