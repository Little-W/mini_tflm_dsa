# IA 装载完成事件的资格选择

IA 控制器提前计算装载完成与分组退休四种事件组合下的数据有效及分组就绪条件。两个当周期事件通过独立组合选择模块确定结果，原有状态寄存器继续在相同时钟边沿接收。完成事件、分组退休、预取、计数边界与输出忙碌条件保持原有定义。

事件或复位信号含未知值时，使用条件语句保持原有四态传播和异步边沿采样顺序。新增模块 `ia_completion_select` 仅包含普通组合选择，不增加寄存器或周期。

## 功能验证

参考提交为 `324eba48`。完整控制器覆盖 `SIZE=3/16/32`，完整加载器覆盖生产、紧凑及通用配置。六组无约束形式比较全部通过，共 44,547 个等价位；全部公开输出、有效状态和展开的存储内容逐周期比较。边沿内的阻塞赋值临时值在其实际接收的状态寄存器处检查。

生产及紧凑配置的完整控制器完成 40,008 个四态周期，逐周期在时钟边沿前后严格比较所有公开输出。两种配置均覆盖全部五个控制状态和 1576 个数据有效周期，包含未知控制、未知复位转换、反压和完成事件。结果见 `validation.json`。

## 独立映射

完整生产控制器使用相同公共依赖进行比较。此测量使用工作树中原有公共比较器，未计入 `54a96b45` 的公共比较器修改。采用 physical-cost 映射，目标周期 6667 ps，估算连线延迟 300 ps，最大切分输入数 8。

| 指标 | 参考结构 | 当前结构 |
| --- | ---: | ---: |
| 逻辑 LUT | 1510 | 1524 |
| 触发器 | 789 | 789 |
| 最长内部组合级数 | 10 | 10 |
| 装载完成输入至 `ia_data_valid` | 6 | 3 |
| 装载完成输入至 `send_group_ready_r` | 5 | 3 |

详细结果与文件散列值见 `measurement.json`。跨前端与 IA 控制器的完整组合路径由整机映射报告统计。

## 复现

```bash
python test/ia_completion_depth/run_formal.py --out build/ia_completion_verified
python test/ia_state_outputs/run_control_four_state.py --reference 324eba48 --out build/ia_completion_four_state
python test/ia_completion_depth/prepare.py --out build/ia_completion_inputs
python scripts/fpga/open_fpga_synth.py --case-config build/ia_completion_inputs/cases.json --cases reference current --out build/ia_completion_pre --through pre_lut
python scripts/fpga/remap_fpga_luts.py --source build/ia_completion_pre/reference --out build/ia_completion_reference --delay-target-ps 6667
python scripts/fpga/remap_fpga_luts.py --source build/ia_completion_pre/current --out build/ia_completion_current --delay-target-ps 6667
python test/ia_completion_depth/measure_paths.py --mapped build/ia_completion_current/mapped.json --pre-lut build/ia_completion_pre/current/pre_lut.il --out build/ia_completion_current/paths.json
```
