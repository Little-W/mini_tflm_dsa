# SoC RAM 命令范围判定

生产实现 `rtl/soc/soc_axi_ram.sv` 与仿真模型 `test/models/soc_axi_ram.sv` 使用相同的 `axi_command_bad` 函数。该函数检查传输尺寸、burst 编码、FIXED 长度与 4 KiB 边界，保持全部 AXI 读写队列、响应周期、数据存储和初始化行为。

当总线每拍最多包含 16 字节时，跨页检查直接计算页内末拍序号。设传输尺寸为 `2^size` 字节，首拍所在页内序号为 `page_address >> size`，末拍序号等于首拍序号加 `len`。`len` 只有 8 位，因此跨页条件可由页内序号高位是否全为一，以及低 8 位加法的进位确定。FIXED 传输的地址保持不变，其长度限制独立检查。更宽的总线保留通用范围计算。

## 验证范围

[measurement.json](measurement.json) 保存实际源码摘要、完整验证结果及局部映射数据。固定参考提交为 `1ff5aaeea92e5e33698bf35990bbe3a3d519d593`。

| 检查 | 配置及范围 | 结果 |
| --- | --- | --- |
| 源码范围 | 生产实现与模型只修改 `axi_command_bad`；两份函数完全一致 | 通过 |
| 完整二态输入 SAT | 地址宽度 8、16、32、40；`ADDR_LSB` 为 0 至 5，共 24 组；地址、长度、尺寸及 burst 均不作输入限制 | 全部通过 |
| 生产 RAM 协议 | 14 组参数，每组固定和随机接收等待两种模式 | 28 项通过 |
| 仿真模型协议 | 相同 14 组参数；随机模式同时启用模型内部的命令、响应和写入延迟 | 28 项通过 |
| 四态传播检查 | 相同 24 组函数参数，每组 65,536 次，总计 1,572,864 次 | 完成分类比较 |
| LUT 映射验证 | 两份网表分别执行 ABC9 `&verify` | 通过 |

协议测试覆盖 32 位和 64 位总线，RAM 深度为 1024 或 1031，未完成请求上限为 1、3 或 4。首读响应延迟覆盖 1、2、3、8、17 个周期。测试检查有效字节、非整数次幂容量边界、窄传输、FIXED 与 INCR、非法请求、4 KiB 边界、响应暂停保持及连续响应吞吐率。每个配置的两种模式完成后立即删除临时编译目录，源码副本、日志和结果保存在指定输出目录。

### 四态结果

完整输入等价证明的范围是二态输入。Icarus Verilog 的四态采样中，两个实现存在以下未知值传播差异：

- 地址或长度含 X/Z，而已知条件足以排除跨页时，参考表达式的加法可能返回 X，当前判定返回 0；本次采样共 92,036 次。
- burst 编码含 X/Z 时，当前对 `burst == 2'b01` 的检查可能返回 X，参考范围计算可能已经返回 1；本次采样共 3,123 次。

本次采样未出现确定的 0 与确定的 1 相互变化，也未出现 0 变为 X 或 X 变为 1。`ADDR_LSB=5` 使用相同通用分支，全部四态样本一致。四态统计不作为四态等价结论；已定义输入的功能及错误响应由完整二态 SAT 和实际 AXI 协议测试检查。

## 生产配置局部测量

测量采用 `DP=32768`、`DW=64`、`AW=32`、`MEM_WORD_WIDTH=64`，读写各保留 4 个未完成请求，首读延迟为 2 个周期。逻辑数据容量保持 256 KiB。

| 指标 | 参考 | 当前 |
| --- | ---: | ---: |
| 逻辑 LUT | 567 | 485 |
| 触发器 | 198 | 198 |
| CARRY4 | 58 | 41 |
| RAMB36E1 | 64 | 64 |
| 分布式 RAM LUT | 68 | 68 |
| DSP48E1 | 0 | 0 |
| 寄存器间最大组合级数 | 15 | 15 |

使用 `physical-cost`、`small-lut-area-cost=1`、最大 6 输入 LUT、500 ps 连线成本与 6667 ps 映射目标。两项映射的进程树峰值内存均小于 200 MiB。物理 LUT 数量由完整 SoC 布局统计；150 MHz 需要布线后的器件时序分析。

## 复现命令

在仓库根目录运行，环境需提供 Yosys Python 接口、Slang、Verilator 和 Icarus Verilog：

```bash
python3 test/soc_ram_command/prove.py \
  --out /tmp/npu_soc_ram_command/formal
python3 test/soc_ram_command/check_four_state.py \
  --out /tmp/npu_soc_ram_command/four_state
python3 test/conv_soc_ram/run.py \
  --rtl-source rtl/soc/soc_axi_ram.sv --verilator verilator-modern --jobs 1 \
  --out /tmp/npu_soc_ram_command/protocol/production
python3 test/conv_soc_ram/run.py \
  --rtl-source test/models/soc_axi_ram.sv --verilator verilator-modern --jobs 1 \
  --out /tmp/npu_soc_ram_command/protocol/model
python3 test/soc_ram_command/prepare_measurement.py \
  --out /tmp/npu_soc_ram_command/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config /tmp/npu_soc_ram_command/inputs/cases.json \
  --cases reference current --through pre_lut --out /tmp/npu_soc_ram_command/pre
python3 scripts/fpga/remap_fpga_luts.py \
  --source /tmp/npu_soc_ram_command/pre/reference \
  --out /tmp/npu_soc_ram_command/mapped/reference \
  --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
  --wire-delay-ps 500 --delay-target-ps 6667
python3 scripts/fpga/remap_fpga_luts.py \
  --source /tmp/npu_soc_ram_command/pre/current \
  --out /tmp/npu_soc_ram_command/mapped/current \
  --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
  --wire-delay-ps 500 --delay-target-ps 6667
python3 test/soc_ram_command/collect_report.py \
  --formal /tmp/npu_soc_ram_command/formal \
  --four-state /tmp/npu_soc_ram_command/four_state \
  --protocol-production /tmp/npu_soc_ram_command/protocol/production \
  --protocol-model /tmp/npu_soc_ram_command/protocol/model \
  --mapped-reference /tmp/npu_soc_ram_command/mapped/reference \
  --mapped-current /tmp/npu_soc_ram_command/mapped/current \
  --out /tmp/npu_soc_ram_command/measurement.json
```
