# IA 数据有效条件的并行计算

IA 控制器分别计算分组就绪和控制状态许可。普通组、尾组、预取组的完整加载计数先并行比较，再选择一位完成结果。`ia_data_ready_select` 按清除、启动、完成的原有优先级计算输出活动许可，分组就绪结果在数据有效寄存器前合并，保持原有状态转换及请求周期。

## 验证

完整等价检查覆盖三种控制器阵列尺寸，以及生产、紧凑和通用加载器六个配置；全部公开输出和共同状态均相同，输入不附加数值限制。两个生产控制器配置各比较 20,004 个四态周期，每个时钟边沿前后检查 43 个公开输出，覆盖全部五种控制状态。

```bash
python test/ia_completion_depth/run_formal.py \
  --reference 9e3e5d6a6f47befe6c86aceacad7999923206458 --out /tmp/ia_ready_formal
python test/ia_state_outputs/run_control_four_state.py \
  --reference 9e3e5d6a6f47befe6c86aceacad7999923206458 --out /tmp/ia_ready_four_state
python test/ia_data_ready_select/measure.py --out /tmp/ia_ready_measure
```

## 完整模块综合

测量保留生产 `ia_loader_ctrl` 的全部公开输出，配置为 16 个阵列元素、64 位总线、32 个缓存块及 29 位计数器，启用生产配置的预计算选项。

| 项目 | 远端参考 | 当前设计 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,484 | 1,500 |
| 分布式存储 LUT | 12 | 12 |
| 最长寄存器组合路径 | 10 级 | 10 级 |
| `send_ia_trigger` 输入至 `ia_data_valid` 寄存器 | 6 级 | 4 级 |

输入至寄存器的测量在实际映射网络的输入端定义分析起点，综合输入及资源统计保持完整模块。生产源码摘要、形式证明、四态比较和映射结果分别保存在 `formal.json`、`four_state.json` 与 `measurement.json`。150 MHz 时序由整机布局布线报告确认。
