# 向量双操作数加法

Softmax 的估计值更新和 INT32 归约求和使用三十二位双操作数加法，输入进位固定为零。两处实例配置十六位低段算术和并行高段进位修正，并启用原分组四态传播。最高进位继续完整计算，调用方只使用低三十二位结果。

```sh
python3 test/parallel_prefix_grouped_unknowns/run.py --out build/parallel_prefix_grouped_unknowns
python3 test/vector_selected_adders/run_formal.py --out build/vector_selected_adders
```

完整父模块验证包含三种 Softmax 深度与寄存配置，以及完整 INT32 归约操作。普通编译和 `SYNTHESIS` 编译的八项证明覆盖全部公开输出，输入不附加限制。通用算术验证进一步覆盖最高进位、未知值和高阻态传播。

## 完整向量引擎测量

测量配置为 16 个向量通道、8 个计算单元、64 位总线、8 个窗口通道，并启用共享存储和共享量化。映射采用 Xilinx 7 系列、6667 ps 延迟目标、300 ps 连线代价与最多 8 输入逻辑分解。

| 项目 | 使用分组加法 | 使用所选分段加法 |
|---|---:|---:|
| 逻辑 LUT | 10011 | 9915 |
| FF | 6683 | 6683 |
| LUTRAM 的 LUT 数量 | 120 | 120 |

两处算术合计增加两个 DSP，减少 96 个逻辑 LUT。寄存器、接口周期、计算通道数量及存储容量保持原有配置。完整 SoC 的资源和时序结果由相同固定源码的整机综合测量确定。
