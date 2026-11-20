# 缓存窗口行号计算

前端使用同一套行号规则生成 `req_window_retire` 和两级预取的窗口元数据。请求端先选择当前行或已保存的请求行，再进行一次计算。两个预取阶段各自保留独立组合计算，全部接口继续使用原有周期。

设 `z` 为输入行与前置填充相加后按步长右移的结果，`n` 为最后输出行，`s` 为短像素标志。有效计算返回 `z < n ? z + s : n`，关闭该功能时返回 `32'hffff_ffff`。行递增与上限比较并行执行，最后选择限幅结果。求和、移位和限幅均保留显式位宽。

## 验证

参考提交为 `781deda2`。`retirement_equivalence.py` 从当前和参考 RTL 提取实际表达式，对全部输入位模式证明三个 32 位结果相同，并逐字检查其余前端代码保持一致。形式证明覆盖 96 位输出，全部通过。

完整前端与真实缓存、预测器共同运行逐周期比较，覆盖 `SIZE=4/8/16`、`LANES=2`、32/64 位总线和窗口预取开关。148 项数值任务完成 1,747,244 个周期；控制专项完成 23 项检查和 134 个周期。全部 19 项公开输出、数值结果和完成周期与参考提交相同。

## 独立综合

完整前端的独立综合把缓存和预测器作为接口边界，采用 `SIZE=16`、`LANES=2`、`BUS_WIDTH=64` 和普通 Xilinx 算术映射。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 6,531 | 6,398 |
| 触发器 | 3,238 | 3,238 |
| DSP48E1 | 30 | 30 |
| CARRY4 | 724 | 718 |
| 最长寄存器间组合单元数 | 21 | 21 |

当前独立前端的最长路径由 `kx_q` 经过坐标处理到状态寄存器。单独综合上述窗口行号计算时，逻辑 LUT 从 363 减少至 283，最长输入到输出组合结构从 19 个单元减少至 15 个。完整 SoC 的 DSP 分配、物理面积和时序由整机流程测量。

整机实例采用 `LANES=4`。相同综合设置下，参考提交 `781deda2` 使用 6,642 个逻辑 LUT，窗口行号计算版本 `151b87d5` 使用 6,586 个逻辑 LUT；两者均使用 3,236 个触发器和 30 个 DSP48E1，最长组合路径均为 21 个单元。CARRY4 数量从 736 减少至 730。两种通道配置的测量分别记录，综合脚本通过 `--lanes` 显式选择配置。

源码摘要、形式结果、逐周期结果及资源记录见 [frontend_retirement_rows_validation.json](../../docs/data/frontend_retirement_rows_validation.json)。

## 重复运行

```bash
python3 test/conv_frontend/tools/retirement_equivalence.py \
  --out build/frontend_retirement/formal --synthesize
python3 test/conv_frontend/tools/compare_frontend.py \
  --reference-ref 781deda2 --lanes 2 --out build/frontend_retirement/interface
python3 test/conv_frontend/tools/synthesis.py \
  --reference-ref 781deda2 --lanes 2 --out build/frontend_retirement/reference
python3 test/conv_frontend/tools/synthesis.py \
  --lanes 2 --out build/frontend_retirement/current
python3 test/conv_frontend/tools/measure_descriptor_paths.py \
  --mapped build/frontend_retirement/current/mapped.json \
  --pre-lut build/frontend_retirement/current/pre_lut.il \
  --out build/frontend_retirement/current/paths.json
```
