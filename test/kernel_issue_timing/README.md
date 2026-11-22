# 权重请求与调度器算术

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

## 设计

`kernel_loader.sv` 在请求接收前并行准备缓存命中、普通加载和预取加载的资格，并保存组合选择边界。`init_cfg`、`cache_flush` 与 DMA 授予信号参与最终接收条件。预取和普通加载使用同一传输类型选择结果，保持请求顺序、缓存命中、清除排空及所有公开输出的逐周期行为。

`kernel_loader_ctrl.sv` 分别准备行、分组与重复次数的更新资格。各维度仍在原来的请求接收边沿更新；地址、列号和遍历计数使用完整模宽行为级加法。`ps_window_scheduler.sv` 共享活动帧的下一个 K 起点，并独立计算 reduction 和 stationary_rows 的减一结果。`use_dsp` 属性标注这些行为级算术，供 FPGA 工具推断资源。

四态仿真保留选择表达式在未知值与高阻值下的结果；相应传播分支限定在仿真部分。设计保留已有接口、存储容量与周期。

## 独立综合

参考源码取自 `9eef82af`，公共 RTL 相同。使用 `synth_xilinx`、740 个 DSP 的总预算和 RTL 属性选择，路径统计包含寄存器数据、时钟使能及同步控制端口。

| 完整模块 | 参数 | 参考逻辑 LUT | 当前逻辑 LUT | 参考 DSP | 当前 DSP | 参考 FF | 当前 FF | 实际寄存器间最长组合级数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `kernel_loader` | SIZE=16，COUNT_WIDTH=29，BUS_WIDTH=64，DATA_WIDTH=16 | 4,317 | 4,254 | 13 | 21 | 2,337 | 2,337 | 10 → 9 |
| `ps_window_scheduler` | SIZE=16，FRAME_COUNT=16，MAX_REUSE_TILES=32 | 1,289 | 1,258 | 7 | 10 | 966 | 966 | 9 → 9 |

两个模块共减少 94 个逻辑 LUT，增加 11 个 DSP。加载器继续使用 16 个 RAMB18，调度器存储结构保持相同。四份连接图均完整。

模块接口的独立诊断显示，`init_cfg` 到内部存储端口的最大深度为 6，`load_weight_granted` 为 3。诊断使用人工输入起点，统计范围仅限加载器内部。完整 SoC 的寄存器间组合级数需要结合外围控制进行测量；150 MHz 需要目标器件实现后的时序报告。

## 功能验证

- `run_formal.py` 比较所有可匹配状态与公开输出，输入不附加协议限制，证明使用组合等价检查与无界归纳。
- 加载控制器覆盖 COUNT_WIDTH 为 1、8、29、32、33 的配置，包括计数回绕。
- 完整加载器覆盖 FPGA 与通用算术配置，以及 32、64、128 位总线。
- 帧调度器覆盖 1、3、16、17 个帧和受限、非受限复用容量，共 5 组参数 × 2 种算术配置。
- `run_four_state.py` 提取实际 RTL 的请求表达式、遍历更新语句与共享算术，在 3 组宽度下完成 239,616 次严格四态比较。
- `test/kernel_prefetch/run.py` 使用实际 RTL RAM 与独立 DMA 数据模型。32 位和 64 位总线各完成 285 个逻辑加载任务、72,960 个数值检查，合计 74,493 个周期。覆盖预取命中、在途命中、候选变化、清除排空、不同数据位宽、尾块、读写重叠和随机等待；所有 C++ 编译单元启用 UBSan。

参数、通过数量、原始报告路径与 SHA256 保存在 `validation.json`。较大的中间日志和网表以 gzip 形式保存，解压后的内容散列保持相同。

## 复现

在仓库根目录准备参考源码：

```bash
mkdir -p build/kernel_issue_reference
git archive 9eef82af rtl | tar -x -C build/kernel_issue_reference
```

完整生产加载器证明与数值仿真：

```bash
python3 test/kernel_issue_timing/run_formal.py \
  --reference-root build/kernel_issue_reference --module kernel_loader \
  --profiles 4:8:32 16:29:64 --fpga --out build/kernel_issue_formal
python3 test/kernel_issue_timing/run_four_state.py \
  --reference-root build/kernel_issue_reference \
  --scheduler-source rtl/npu/control/ps_window_scheduler.sv \
  --out build/kernel_issue_four_state
python3 test/kernel_prefetch/run.py --fpga --bus-width 64 \
  --count-width 29 --out build/kernel_issue_numeric64
python3 test/kernel_prefetch/run.py --fpga --bus-width 32 \
  --count-width 29 --out build/kernel_issue_numeric32
```

加载控制器与帧调度器证明：

```bash
python3 test/kernel_issue_timing/run_formal.py \
  --reference-root build/kernel_issue_reference --module kernel_loader_ctrl \
  --profiles 1:1:32 4:8:32 16:29:64 16:32:64 16:33:64 \
  --fpga --out build/kernel_issue_controller
python3 test/kernel_issue_timing/run_formal.py \
  --reference-root build/kernel_issue_reference --module ps_window_scheduler \
  --profiles 1:1:1 4:3:4 16:16:32 16:16:0 16:17:64 \
  --fpga --out build/kernel_issue_scheduler_fpga
python3 test/kernel_issue_timing/run_formal.py \
  --reference-root build/kernel_issue_reference --module ps_window_scheduler \
  --profiles 1:1:1 4:3:4 16:16:32 16:16:0 16:17:64 \
  --out build/kernel_issue_scheduler_generic
```

独立资源与路径测量：

```bash
python3 test/kernel_control_depth/measure.py --reference 9eef82af \
  --out build/kernel_issue_measure
python3 test/scheduler_control/prepare_measurement.py --reference-rev 9eef82af \
  --out build/kernel_issue_scheduler_measure
python3 scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config build/kernel_issue_scheduler_measure/cases.json \
  --cases scheduler_reference scheduler_current \
  --out build/kernel_issue_scheduler_measure/synthesis \
    --max-register-path-cells 10
```
