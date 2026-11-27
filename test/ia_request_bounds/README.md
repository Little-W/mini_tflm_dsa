# IA 请求上界与数据有效选择

完整输入装载器分别计算普通组、尾组和预取组的剩余请求条件。三位比较组通过平衡结构归并，当前组只选择已经完成的一位比较结果。坐标加法等值检查保留六位比较组，限制完整地址匹配的组合深度。

初始化周期将分组就绪标志清零，因此数据有效资格只需考虑加载状态和发送状态。控制器在现有边沿保存数据有效标志，保持所有公开输出、状态更新和存储内容的逐周期行为。未知控制输入继续采用原有条件语句及状态表达式。

## 验证

参考提交为 `f02e539e210161e285e595ec2271b0f1067450a6`。完整控制器覆盖 `SIZE=3/16/32`，完整装载器覆盖生产、紧凑存储及通用配置。六组无约束形式比较全部通过，共检查 45,007 个等价位。生产与紧凑配置完成 40,008 个四态周期，逐周期比较全部 43 个公开输出，包含未知复位、反压、加载完成及发送事件。

| 完整装载器指标 | 参考结构 | 当前结构 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,819 | 3,808 |
| 分布式存储名义 LUT | 12 | 12 |
| 名义 LUT 总数 | 3,831 | 3,820 |
| 最长寄存器组合路径 | 12 级 | 10 级 |
| 映射等价检查 | 通过 | 通过 |

两组测量均保留完整装载器的全部端口。参数为 `SIZE=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=32`、`COUNT_WIDTH=29`、共享存储地址宽度 12，启用有序任务、共享写入寄存及 DMA 请求寄存。

## 复现

```bash
python test/ia_completion_depth/run_formal.py --reference f02e539e --out build/ia_request_bounds/formal
python test/ia_state_outputs/run_control_four_state.py --reference f02e539e --out build/ia_request_bounds/four_state
python test/ia_request_bounds/measure.py --out build/ia_request_bounds/mapping
```

形式比较、四态结果及完整映射分别见 `formal.json`、`four_state.json` 和 `measurement.json`。整机寄存器路径由完整 SoC 测量确认。
