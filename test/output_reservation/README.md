# 输出存储预留与容量阈值

顶层在配置提交边沿同时保存输出存储区预留数量和占用阈值。预留为零时按一个存储区处理，超过容量时饱和至容量，其他值从容量中减去预留数量。运行期间 FIFO 直接比较完整就绪数量和阈值，并单独处理部分写入和定宽计数回绕。配置生效周期、FIFO 请求周期和数据吞吐保持原有行为。

`p_precomputed_watermark=1` 使用 `i_ready_bank_threshold`，完整 SoC 启用该参数。默认值为零时使用 `reserve_banks` 计算容量状态。

## 验证

`run.py` 提取实际顶层配置寄存逻辑。启用 `--precomputed-threshold` 时，同时提取阈值寄存器及其复位和更新表达式，比较 FIFO 容量状态。13 组配置通过复位检查与无界归纳证明，寄存器位宽覆盖 4 至 64 位，存储区数量覆盖 1 至 512；包括零预留、容量饱和、运行中复位以及全部计数编码。

`run_interfaces.py` 对 S8 完整实现、S8 线性实现和 S16 实现进行逐周期比较。5 组配置共 35,734 个等价位通过证明，包括公开输出和共同寄存状态。S8 完整实现比较实际 RAM 读写端口，并向两个实现提供相同的任意 RAM 返回数据；线性实现和 S16 实现展开内部存储器进行比较。默认容量计算另有 15 组参数通过全部输入的组合形式证明。

16 通道、32 个存储区、64 位总线、循环布局的 S8 FIFO 独立综合结果为 1,149 个逻辑 LUT、60 个分布式 RAM LUT、165 个触发器和 8 个 RAMB18，寄存器之间最长组合路径为 10 级。整机中的跨模块路径由整机综合另行测量。

`threshold_validation.json` 保存源码 SHA-256、参数和验证结果。

## 重复运行

```sh
python test/output_reservation/run.py --reference 415a70a \
  --precomputed-threshold --out build/output_threshold
python test/output_reservation/run_interfaces.py --out build/output_threshold_interfaces
python test/writeback_bus/run_watermark_formal.py --out build/watermark_default
```
