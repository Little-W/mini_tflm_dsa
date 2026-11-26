# 部分和预取的请求资格

`ps_frame_store` 先并行准备首行读取资格和后续行读取资格。`frame_request`、`frame_accept` 以及已经接受命令的状态在末级选择读取资格，使上游中止控制不经过局部状态的完整判断过程。首行冲突检测、容量状态、取消准备、队列信用和同步读返回周期保持一致。

已知控制值使用分解后的表达式；包含 `X/Z` 的控制组合使用原有四态表达式。全部改变发生在组合逻辑中，接口与状态寄存器不增加周期。

## 检查结果

四种完整模块配置通过公开输出与共同状态的等价证明：内部存储、轮转外部存储，以及固定通道的每帧 256 行和 512 行配置。功能输入不施加约束，合计检查 64,382 个等价位。

`run_control.py` 从两版实际源码提取准备和预取表达式，完成全部二态输入的组合证明，并检查 32,768 组四态输入。四个关键控制信号的全部 256 种四态组合均被覆盖。详细结果保存在 `validation.json`。

## 完整模块映射

两版使用相同的 16 帧、每帧最多 512 行、48 KiB 外部存储参数。映射使用 `physical-cost`、6667 ps 目标、300 ps 连线代价和最多 8 个输入的切割设置。

| 项目 | 修改前 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,576 | 1,572 |
| 完整模块最长寄存器间组合单元数 | 11 | 11 |
| `frame_request` 到存储读使能的组合单元数 | 5 | 2 |
| `frame_accept` 到存储读使能的组合单元数 | 4 | 2 |

输入路径使用网表边界分析节点标记起点和终点，节点不计入组合单元数，也不写入 RTL。`measurement.json` 保存原始文件摘要、资源统计和路径结果。

## 重复执行

在工程根目录运行：

```sh
python test/ps_prefetch_qualification/run_full.py --out build/ps_prefetch_full
python test/ps_prefetch_qualification/run_control.py --out build/ps_prefetch_control
python test/ps_prefetch_qualification/prepare.py --out build/ps_prefetch_inputs
python scripts/fpga/open_fpga_synth.py --case-config build/ps_prefetch_inputs/cases.json --cases reference current --out build/ps_prefetch_pre --through pre_lut
python scripts/fpga/remap_fpga_luts.py --source build/ps_prefetch_pre/reference --out build/ps_prefetch_reference --delay-target-ps 6667
python scripts/fpga/remap_fpga_luts.py --source build/ps_prefetch_pre/current --out build/ps_prefetch_current --delay-target-ps 6667
python test/ps_prefetch_qualification/measure_paths.py --mapped build/ps_prefetch_current/mapped.json --pre-lut build/ps_prefetch_pre/current/pre_lut.il --inputs frame_request frame_accept --outputs ram_read_en --out build/ps_prefetch_current/input_paths.json
```
