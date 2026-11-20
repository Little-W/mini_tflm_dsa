# 前端配置接收与请求元数据

前端采用五位二进制主状态。FPGA 配置就绪逻辑由三个六输入查找表并行检查主状态、配置阶段、地址阶段、预取阶段及挂起标志，再与缓存就绪和提示状态合并。本地寄存器位到配置就绪最多经过两级查找表，缓存就绪只参与最后一级。`busy` 由同一空闲结果取反生成。

当前项和新描述符分别完成请求索引移位及纪元计算，`incoming_context` 选择已计算的结果。接口、配置接收条件、请求接收时刻和输出周期保持原有定义。新增综合 RTL 使用显式位宽、命名生成块及中文注释，未添加函数。

## 功能检查

参考提交为 `eaba763528e6459e01b6f4a150776c223e42a62b`。

- 配置就绪和忙状态在完整二十位输入空间通过形式证明，覆盖所有主状态与阶段编码。通用 RTL 和官方 FPGA 原语模型分别检查。
- 请求元数据在 `LINE_BYTES=4/8/16/32/64/128` 六种参数下通过全部输入证明，每个参数覆盖 287 位输入和 196 位观察结果。
- 实际 FPGA 窗口测试接受 422 个请求，完成 418 个请求，复位取消 4 个请求，检查 4,457 个有效数值和 19 个预期错误。
- 常驻窗口的 1,545 行逐周期记录与参考版本一致。
- 非幂次几何测试覆盖 30 组配置、960 个请求和 7,916 个数值，249,411 行逐周期记录与参考版本一致。

## 联合综合

测量包含实际 `axi_dual_block_dma`、窗口队列、完整前端和完整读取缓存。线性 DMA、读取保护、写入保护、读取复用器及预测器作为接口边界。参考与当前的其他综合源码摘要完全相同。

| 项目 | 参考版本 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT 单元 | 11,321 | 11,291 |
| 分布式 RAM LUT 位置 | 484 | 484 |
| SRL LUT 位置 | 0 | 0 |
| 名义 LUT 位置总计 | 11,805 | 11,775 |
| 触发器 | 5,187 | 5,187 |
| DSP48E1 | 33 | 33 |
| RAMB18E1 | 20 | 20 |
| CARRY4 | 974 | 974 |
| 联合网表最长组合单元数 | 17 | 17 |

当前最长路径为输入行到缓存退休字段的计算。其余保存的路径组最长为十五级。联合图完整，没有组合环。`measurement.json` 保存具体起止点、组合单元、源码摘要及检查结果。`fg_state[1]` 查询由实际触发器的 Q 端点定位；查询结果为零时表示该联合范围内没有到指定寄存器 D 端的连接路径。

这些统计属于技术映射结果。完整 SoC 的寄存器路径、物理 LUT 占用和 150 MHz 时序需在相应综合与实现范围内检查。

## 运行方法

```bash
python3 test/frontend_control_depth/run.py \
  --reference eaba7635 --out build/frontend_control/formal

python3 test/window_descriptor_stage/synthesis.py \
  --reference eaba7635 --include-cache \
  --out build/frontend_control/synthesis --cases reference current

python3 test/frontend_control_depth/paths.py \
  --reference build/frontend_control/synthesis/reference \
  --current build/frontend_control/synthesis/current \
  --proof build/frontend_control/formal/summary.json \
  --out build/frontend_control/paths.json

python3 test/window_dma/run.py --fpga --reference-ref eaba7635 \
  --verilator verilator-modern --jobs 2 --out build/frontend_control/window

python3 test/frontend_control_depth/numeric.py \
  --model build/frontend_control/window \
  --reference-model build/frontend_control/window/reference \
  --proof build/frontend_control/formal/summary.json \
  --verilator-include /path/to/verilator/include \
  --out build/frontend_control/nonpower
```
