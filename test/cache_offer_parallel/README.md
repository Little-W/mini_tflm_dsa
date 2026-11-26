# 窗口缓存的预取比较与槽位选择

当前片段与下一片段分别检查在途填充、缓存驻留和预取队列中的完整标签。三位标签比较结果独立归并，当前片段是否重复只在末级决定下一片段的选择。预取队列保留并行独热选择结果，逻辑队列位置和物理存储地址分别编码。

请求容量、缓存容量、物理槽位映射、优先次序和全部寄存边沿保持一致。条件中包含 X 或 Z 时，条目覆盖与片段选择遵循过程条件的四态语义。

## 功能检查

完整窗口缓存采用四组容量与总线参数，分别在明确关闭和启用 `SYNTHESIS`、`XILINX_FPGA` 的两种方式下检查全部共有状态与公开输出。八项时序等价检查均通过，外部输入不附加限制。

独立重复判断模块覆盖 1、2、25、29 位标签以及 1、3、10、9 个比较条目。八项任意输入形式检查和 524,288 次四态结果比较均通过。

## 资源与组合路径

采用 16 组、2 路、128 字节缓存行、64 位总线与返回数据、2 个需求队列条目的完整窗口缓存配置。参照提交为 `548bda54`，两种实现使用相同的综合配置和 ABC9 映射检查。

| 指标 | 参照实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 2,895 | 2,792 |
| LUTRAM 名义位置 | 68 | 68 |
| 触发器 | 2,001 | 2,001 |
| DSP | 16 | 16 |
| RAMB36 等效块 | 1 | 1 |
| RAMB18 等效块 | 26 | 26 |
| 最长寄存器间组合级数 | 12 | 10 |
| 槽位映射到预取存储器地址 | 12 | 9 |

资源、源文件摘要和实际连接路径见 `measurement.json`，功能检查见 `validation.json`。150 MHz 的器件时序由布局布线后的报告确认。

## 重现

```bash
python3 test/cache_offer_parallel/check_parent.py --out build/cache_offer_parallel/parent
python3 test/cache_offer_parallel/check_offer.py --out build/cache_offer_parallel/offer
python3 test/cache_offer_parallel/measure.py --out build/cache_offer_parallel/measurement
```
