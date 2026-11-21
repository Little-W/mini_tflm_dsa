# 权重加载器组合深度验证

`kernel_loader_ctrl.sv` 使用分组前缀条件维护完整计数宽度的进位，按模宽关系计算下一次计数是否达到上限。列分组、描述符位置和配置取整使用公共算术模块。25 倍列步长先计算逐位和与进位，再完成一次完整加法。

`kernel_loader.sv` 在接收有效预取描述符时保存有效行列数量。元数据、行列尺寸、行列坐标和基地址分别形成完整比较结果，实际比较节点保留组合边界，最后统一汇合。DMA 接口、缓存命中规则、描述符接收条件和命令周期保持一致。

## 综合测量

参数为 `SIZE=16`、`REG_WIDTH=32`、`COUNT_WIDTH=29`、`DATA_WIDTH=16`、`BUS_WIDTH=64`。参考加载器来自提交 `415a70a`。两个版本使用相同公共 RTL、相同 `xc7` 综合选项和 `use_dsp` 属性选择规则，资源上限为 740 个 DSP。

| 指标 | 参考版本 | 当前版本 |
| --- | ---: | ---: |
| 逻辑 LUT | 4,703 | 4,317 |
| 触发器 | 2,557 | 2,337 |
| DSP48E1 | 1 | 13 |
| CARRY4 | 274 | 162 |
| RAMB18E1 | 16 | 16 |
| 最长寄存器间组合路径 | 13 | 10 |

连接图完整。路径统计包含实际连接经过的 LUT、进位单元、存储器异步读取及 DSP 组合段；时钟寄存边界按器件参数识别。150 MHz 的最终时序结果由完整 SoC 的布局布线报告确认。

```bash
python test/kernel_control_depth/measure.py --reference 415a70a \
  --out build/kernel_control_depth/measurement
```

## 功能与周期验证

- 完整控制器的 6 组参数在 FPGA 综合分支下通过逐周期等价证明，共 15,462 个等价位。
- 当前加载器顶层的 3 组参数通过全部共同状态和公开输出的等价证明，共 42,673 个等价位，包含生产配置的 32 位与 64 位总线。该证明为两个顶层使用同一当前控制器；控制器的独立证明覆盖其全部输入序列。
- 缓存资格表达式通过全部二值输入关系证明和 12,288 次严格四态检查。
- 18 组描述符相等比较和 14 组突发长度编码通过组合证明。
- 遍历算术的 11 种宽度及 4 组完整控制器配置通过证明。
- 3 组配置证明比较结果有效期间的 678 位输入保持一致，并检查等待比较时的预取状态。
- 24 组四态检查覆盖 1 至 65 位计数器的随机值、相邻边界、最大值回绕，以及逐位未知值和高阻值，共 108,096 次检查。
- 32 位与 64 位总线各执行 285 次逻辑加载、72,960 项数值检查，分别使用 45,050 与 29,443 个周期。用例覆盖预取命中、在途命中、候选变化、取消、刷新、尾部形状以及 S8/S16 数据；全部 C++ 编译单元启用 UBSan。

```bash
python test/kernel_prefetch/run_control_formal.py --reference 415a70a --fpga --seq 2 \
  --profiles 1:1 4:8 8:16 16:29 16:32 16:33 \
  --out build/kernel_control_depth/controller_formal
python test/kernel_cached_compare/run_formal.py --reference 415a70a \
  --out build/kernel_control_depth/loader_formal
python test/kernel_compare_stage/run_formal.py \
  --out build/kernel_control_depth/comparison_formal
python test/kernel_control_depth/run_four_state.py \
  --out build/kernel_control_depth/four_state
python test/kernel_prefetch/run.py --fpga --bus-width 32 \
  --out build/kernel_control_depth/numeric32
python test/kernel_prefetch/run.py --fpga --bus-width 64 \
  --out build/kernel_control_depth/numeric64
```

`validation.json` 保存源文件散列值、具体参数、工具检查结果和成对测量结果。验证脚本检查执行期间源文件保持一致。
