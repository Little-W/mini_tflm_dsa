# 预测器坐标并行借位

预测器的两个 34 位坐标减法分别计算低 16 位差值和高 18 位结果。
高位分别计算借位为零和为一时的差值，再由低位借位选择结果。
计算保留完整的符号位，坐标范围、步长和后续秩值计算使用原有寄存边沿。

参考版本为 `2bd1d2b332874303b5ad39ea489fce44b336ac98`。
参考预测器 SHA-256 为 `897e3ef847a18b7c005b214b97a59db051674a0c3bd7030ea7ce72d124d7f395`，
当前源码为 `8a0526a7cd5f3f700112316c57e90426983a7b9013fbbfd136db9fcdd19dc745`。

## 验证

`run.py` 从实际源码提取减法表达式，并核对其余 RTL 的语法内容与参考版本相同。
形式证明允许两个 33 位填充坐标和两个 32 位乘积任意变化，覆盖全部 130 位输入及 68 位结果。

独立数值测试在每次运行时重新生成几何模型，覆盖 33 组配置和 13,226 个下一次访问秩值。
其中 14 组启用预测，19 组检查配置限制，最大卷积核为 25 个元素。
边界包括大填充、大膨胀和 32,768 的步长。
全部公开输出在 206,076 个周期内与固定参考版本一致。

实际 FPGA 窗口测试使用官方原语模型，覆盖配置、背压、撤销、中止、复位和错误恢复：
422 个请求接收，418 个完成，4 个复位取消，4,457 个数值检查，19 个预期错误。
连续驻留窗口的 512 个响应耗时 1,534 周期，最大响应间隔为 3 周期；
1,545 行请求、响应、AXI 和忙状态记录与参考版本逐周期相同。

## 独立映射

测量采用完整 `conv_next_use_predictor`，使用 Xilinx 7 系列原语。
路径统计包含 DSP 内部寄存器到输出端口之间的组合运算。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 1,732 | 1,780 |
| 触发器 | 1,128 | 1,128 |
| DSP48E1 | 13 | 13 |
| CARRY4 | 139 | 149 |
| DSP 内部寄存器到 `coordinate_good_s1` | 15 级 | 14 级 |
| 模块最长寄存器路径 | 16 级 | 16 级 |

模块最长路径经过配置点数的向上取整计算，到达 `cfg_blocks_q`。
该配置计算保持原有实现。
当前综合最大驻留内存为 229,784 KiB。
源码摘要、资源和完整连接路径保存在 `docs/data/fpga_predictor_borrow.json`。

## 运行

```bash
python3 test/predictor_borrow/run.py --reference 2bd1d2b3 --out build/predictor_borrow/formal
python3 test/conv_replacement/predictor_test.py --reference-ref 2bd1d2b3 --verilator verilator-modern --build build/predictor_borrow/numeric --out build/predictor_borrow/numeric/summary.json
python3 test/window_dma/run.py --out build/predictor_borrow/fpga --verilator verilator-modern --jobs 1 --fpga --reference-ref 2bd1d2b3
python3 test/conv_replacement/predictor_synthesis.py --reference-ref 2bd1d2b3 --out build/predictor_borrow/synthesis/reference
python3 test/conv_replacement/predictor_synthesis.py --out build/predictor_borrow/synthesis/current
```
