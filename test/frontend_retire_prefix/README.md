# 退休行条件递增

`conv_im2col_frontend` 的请求和两级预取各自计算退休行。输入行加上上方填充并右移后，`short_pixel_q` 决定是否递增，最后按 `retire_last_row_q` 限幅。

FPGA 实现采用并行区间全一检查。低五位的进位同时包含递增使能，其余区间并行检查。每一路十七位结果使用四个前缀查找表、七个双输出查找表和三个单输出查找表，从输入到任一结果最多经过两级查找表。通用 RTL 保留显式十八位加法，包含最高位进位。

端口、寄存器、配置接收时刻和输出周期保持原有定义。新增连接使用显式位宽、命名的生成块和输入信号，综合 RTL 未添加函数。

## 综合测量

参考提交为 `9c112bfe49143be627eb44798446850075107812`。测量实际 `axi_dual_block_dma`、窗口队列、完整前端与完整读取缓存，其余五个相邻模块作为接口边界。所有相邻综合源码的 SHA-256 相同，仅前端的条件递增发生改变。

| 项目 | 参考版本 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT 单元 | 11,321 | 11,382 |
| 分布式 RAM LUT 位置 | 484 | 484 |
| SRL LUT 位置 | 0 | 0 |
| 名义 LUT 位置总计 | 11,805 | 11,866 |
| 触发器 | 5,187 | 5,187 |
| DSP48E1 | 33 | 33 |
| RAMB18E1 | 20 | 20 |
| CARRY4 | 974 | 962 |
| 最长寄存器间组合单元数 | 17 | 15 |

路径计算包含 LUT、MUXF、CARRY、存储读口及 DSP 内部寄存器边界之间的组合运算。联合网表的连接图完整，没有组合环。详细路径与源码摘要保存在 `measurement.json`。上述资源属于技术映射结果；物理 LUT 占用和 150 MHz 时序需要目标器件的实现报告。

## 功能检查

- 通用 RTL 和官方 FPGA 原语模型分别通过完整十八位加法结果的全部输入形式证明。
- 同两种模型分别通过三路九十六位退休结果的全部输入形式证明，覆盖请求选择、右移、限幅和禁用状态。
- 实际 FPGA 窗口测试通过：接受 422 个请求，完成 418 个请求，复位取消 4 个请求，检查 4,457 个有效数值和 19 个预期错误。
- 常驻窗口的 1,545 行逐周期记录与参考版本一致。
- 非幂次几何测试覆盖 30 组配置、960 个请求和 7,916 个数值，249,411 行逐周期记录与参考版本一致。

## 运行方法

环境需提供 Yosys/Slang、ABC9、Pyosys、Verilator 和官方 Xilinx 原语模型。

```bash
python3 test/frontend_retire_prefix/run.py \
  --reference 9c112bfe --out build/retire_prefix/formal

python3 test/window_descriptor_stage/synthesis.py \
  --reference 9c112bfe --include-cache \
  --out build/retire_prefix/synthesis --cases reference current

python3 test/frontend_retire_prefix/paths.py \
  --reference build/retire_prefix/synthesis/reference \
  --current build/retire_prefix/synthesis/current \
  --proof build/retire_prefix/formal/summary.json \
  --out build/retire_prefix/paths.json

python3 test/window_dma/run.py --fpga --reference-ref 9c112bfe \
  --verilator verilator-modern --jobs 2 --out build/retire_prefix/window

python3 test/frontend_retire_prefix/numeric.py \
  --model build/retire_prefix/window \
  --reference-model build/retire_prefix/window/reference \
  --proof build/retire_prefix/formal/summary.json \
  --verilator-include /path/to/verilator/include \
  --out build/retire_prefix/nonpower
```
