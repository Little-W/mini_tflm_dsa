# 偏置控制器准备阶段验证

## 当前设计

偏置控制器在已有标记、分组和请求阶段准备后续计算结果：

1. 标记阶段保存剩余块数。分组阶段使用该结果确定装载长度、尾块偏移和窗口末端标志。
2. 装载长度仍先进行完整位宽比较，再按固定银行容量保存有效结果位。配置输入和公开计数端口的宽度保持。
3. `S_CMD` 保存当前 DMA 地址，`S_REQ` 根据该地址准备尾块地址，`S_LOAD` 在尾块请求发生时使用准备结果。
4. 宽地址加法和索引加法使用公共 `parallel_prefix_add`。二次幂分块的数量计算先取商，再处理低位非零标志；原计数宽度的回绕结果保留，其他分块参数使用通用表达式。

公开输出、原有 24 个状态寄存信号、状态推进顺序、DMA 请求周期和初始化优先级均进行逐周期比较。偏置银行和 WS 缓存的容量保持。

## 验证方法

`prove.py` 对两个实际控制器建立完整状态比较，并把准备值在消费阶段应满足的关系加入归纳检查。所有性质共同进行初始检查和归纳证明；只指定首次采样时复位有效，没有配置范围或握手时序假设。参数覆盖 `COUNT_WIDTH=1/8/12/29/32/35`、`REG_WIDTH=16/32/40`、32/64/128 位总线，以及非二次幂 `SIZE=12` 和分组容量 3、5。

四态周期检查实例化两个实际控制器，比较全部公开输出和原有状态信号。配置采样使用完整宽度的二态数据，在未采样的配置输入和握手控制上注入 X/Z，检查 32,768 个周期。该检查说明所覆盖场景的四态行为，不声明任意未知配置下的普遍四态等价。

既有 `test/bias_loader_reuse` 覆盖 392 项实际 DMA、WS/IS 数值、驻留复用、尾块与等待场景。局部测量使用完整 `bias_loader` 的生产参数与普通 RTL 算术，保存源文件和工具的 SHA-256。结果见 [measurement.json](measurement.json)。实际 Vivado 面积、布线及 150 MHz 时序由整机报告确认。

## 生产参数局部测量

完整加载器采用 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`GROUP_BLOCKS_MAX=32`。对照仅将控制器替换为 `2297cb12` 的版本，其他模块使用相同源码。两侧使用相同普通 RTL 综合和成本参数。

| 项目 | 参考版本 | 当前设计 |
|---|---:|---:|
| 逻辑 LUT | 1,180 | 1,190 |
| FF | 1,181 | 1,227 |
| CARRY4 | 101 | 91 |
| RAMB36E1 | 1 | 1 |
| 控制器寄存路径最大组合级数 | 14 | 9 |
| 完整加载器最大组合级数 | 14 | 10 |

完整加载器的 10 级路径位于缓冲区的银行末端地址保存逻辑。新增准备寄存器保持原有公开周期，并分开窗口判断和地址计算。

## 复现

从仓库根目录运行，环境应提供 Python Yosys/Slang、ABC、Verilator 和 Icarus。

```bash
export PYTHONDONTWRITEBYTECODE=1
BIAS_CTRL_OUT=/tmp/bias_control_depth
python3 test/bias_control_depth/prove.py --out "$BIAS_CTRL_OUT/formal"
python3 test/bias_control_depth/check_four_state.py --out "$BIAS_CTRL_OUT/four_state"
python3 test/bias_loader_reuse/run.py --out "$BIAS_CTRL_OUT/reuse" --jobs 1
python3 test/bias_control_depth/prepare_measurement.py --out "$BIAS_CTRL_OUT/inputs"
python3 scripts/fpga/open_fpga_synth.py \
  --case-config "$BIAS_CTRL_OUT/inputs/cases.json" --cases reference current \
  --through pre_lut --out "$BIAS_CTRL_OUT/pre"
for version in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "$BIAS_CTRL_OUT/pre/$version" --out "$BIAS_CTRL_OUT/mapped/$version" \
    --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
    --wire-delay-ps 500 --delay-target-ps 6667
done
python3 test/bias_control_depth/collect_report.py \
  --formal "$BIAS_CTRL_OUT/formal" --four-state "$BIAS_CTRL_OUT/four_state" \
  --reuse "$BIAS_CTRL_OUT/reuse" --mapped-reference "$BIAS_CTRL_OUT/mapped/reference" \
  --mapped-current "$BIAS_CTRL_OUT/mapped/current" --out "$BIAS_CTRL_OUT/measurement.json"
```
