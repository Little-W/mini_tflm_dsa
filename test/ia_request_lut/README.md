# IA 有序请求坐标比较

`ia_loader` 的有序请求描述符使用两个 `add_equal` 实例检查行、列坐标。FPGA 配置启用各实例的 `p_use_lut` 参数，使用显式 `LUT6` 计算逐位进位关系，并按六位分组归约。坐标宽度、低位输入进位、截断加法和描述符匹配条件保持原有定义。ASIC 与通用仿真配置使用组合 RTL。

本修改没有新增寄存器或握手阶段。缓存容量、请求优先级、DMA 描述符和所有公开输出的逐周期行为保持一致。

## 模块测量

参考源码为 `75f9862e`，当前 RTL 为 `b1a2cb98`。完整加载器参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`。

| 映射方法 | 版本 | 逻辑 LUT | FF | 最长寄存器路径 | `ps_frame_final` 到 `load_ia_req` |
| --- | --- | ---: | ---: | ---: | ---: |
| 普通 Xilinx 映射 | 参考 | 5,728 | 3,080 | 12 | 9 |
| 普通 Xilinx 映射 | 当前 | 5,743 | 3,080 | 12 | 12 |
| 物理面积成本映射 | 参考 | 5,005 | 3,080 | 13 | 13 |
| 物理面积成本映射 | 当前 | 4,986 | 3,080 | 13 | 12 |

每个版本均使用 176 个 RAM LUT，DSP 和 BRAM 数量均为零。物理面积成本映射减少 19 个逻辑 LUT，目标公开输出路径缩短一级。组合优化会根据完整模块的其他使用者安排末级归约，因此两种映射的请求输出级数分别记录。完整 SoC 的请求仲裁路径由同一源码的整机连接检查确定。

路径分析读取实际映射连接，并使用保存的寄存器来源识别起点。公开输出的观察端点只用于路径统计，不加入综合网表。逻辑 LUT 数量为映射原语计数，物理位置数量由布局结果提供。

## 功能验证

比较器使用工具链提供的 Xilinx `LUT6` 功能模型，对位宽 `1/2/27/28/30/32/64` 证明任意输入、输入进位与模加法结果的等价性。

完整加载器的五组状态比较覆盖生产参数、三十二位计数、六十四个缓存块、非二的幂小尺寸本地 RAM 和 ASIC 配置。检查包含全部匹配寄存器、存储状态与公开输出，不限制外部请求或握手序列。

实际 FPGA 原语的逐周期接口比较同时运行参考和当前实现，检查全部 39 个公开输出，并启用未定义行为检查。两组回归共检查 180,122 个周期和 903,952 个数值：

| 场景 | 周期 | 数值检查 |
| --- | ---: | ---: |
| 有序任务预取，251 条 DMA 命令 | 57,835 | 179,920 |
| 32 个缓存块，81 个分组任务 | 122,287 | 724,032 |

`measurement.json` 保存验证配置、源码 SHA-256、模型来源和各报告的 SHA-256。

## 复现

```sh
python3 test/ia_request_lut/run_formal.py --out build/ia_request_lut/formal

python3 test/ia_request_lut/run_interface.py \
  --verilator /path/to/verilator --out build/ia_request_lut/interface

python3 test/ia_frame_rows/prepare_measurement.py \
  --reference-rev 75f9862e --out build/ia_request_lut/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ia_request_lut/inputs/cases.json \
  --cases loader_reference loader_current --out build/ia_request_lut/native \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/ia_request_lut/native/loader_current \
  --out build/ia_request_lut/physical/loader_current \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 test/ia_request_lut/measure_paths.py \
  --mapped build/ia_request_lut/physical/loader_current/mapped.json \
  --pre-lut build/ia_request_lut/native/loader_current/pre_lut.il \
  --out build/ia_request_lut/physical/loader_current/paths.json

python3 test/ia_request_lut/collect_measurement.py \
  --build build/ia_request_lut --out test/ia_request_lut/measurement.json
```

参考与当前版本分别执行物理面积成本映射，两种映射的两个版本均执行路径统计后生成汇总记录。
