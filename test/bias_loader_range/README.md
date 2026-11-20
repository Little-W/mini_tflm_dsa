# 偏置驻留范围检查

`bias_loader_buffer` 在接受装载命令的周期中，将起始块号与块数相加，并把结果保存到 `bank_end_q`。末端位置比块号多一位，能够保存最高位进位。驻留检查同时比较起始位置与末端位置，WS 向量读取、IS 标量读取和预取命令使用原有周期。

生产参数 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=28`、`GROUP_BLOCKS_MAX=32` 下，独立 Xilinx 综合结果如下。

| 项目 | 参考实现 | 保存末端位置 |
|---|---:|---:|
| 逻辑 LUT | 1,154 | 1,133 |
| `CARRY4` | 67 | 51 |
| 触发器 | 767 | 769 |
| `RAMB36E1` | 1 | 1 |
| 最长寄存器间组合单元数 | 15 | 11 |

四种参数配置完成全部状态与输出的形式比较，共 42,814 位；输入没有附加假设。参考实现中的观测信号由已保存的块号与块数直接计算，参与等价证明。功能测试完成了 392 个偏置装载与复用场景。源码散列、结果和资源记录保存在 `docs/data/bias_range_validation.json`。

```sh
python3 test/bias_loader_range/run_formal.py --out build/bias_range_formal
python3 test/bias_loader_reuse/run.py --out build/bias_range_regression --jobs 1
python3 test/bias_loader_range/synthesis.py --out build/bias_range_synth/current
python3 test/bias_loader_range/synthesis.py --out build/bias_range_synth/reference --reference-ref 975ce61
```
