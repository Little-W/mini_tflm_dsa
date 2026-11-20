# SoC AXI RAM 地址运算验证

完整检查结果与源码摘要见 [measurement.json](measurement.json)。

## 当前设计

生产 RAM 和仿真 RAM 使用相同的地址推进、容量比较与写字节选择逻辑。

`axi_next_addr` 保留完整的 `AW+1` 位地址。`FIXED` 传输返回当前地址；其他 `burst` 编码按照原接口的递增规则，清除低于 `size` 的地址位并增加 `2^size`。低八位通过传输边界掩码和前缀全一条件计算，高位按字节并行准备递增结果，前缀进位选择保持值或递增值；字节内使用逐位逻辑保留 X/Z 传播。地址计算保持组合逻辑，所有地址寄存器、队列和握手过程保持原有周期。

写字节选择使用两个条件：字节位置不低于首字节，并且该位置与首字节属于同一个传输块。传输块编号由右移 `size` 得到，覆盖未对齐首拍和全部 `size` 编码。

对于可由扩展字地址表示的2 的整数次幂容量，越界条件为容量边界以上地址位的归约或。非2 的整数次幂容量保留完整无符号比较；地址宽度不足以表示容量常数时，也保留原来的定宽比较行为。

## 验证范围

- **地址推进的全输入 SAT：** `AW=1/3/7/8/9/16/24/32/40/65`，共 10 组。比较全部 `AW+1` 个输出位，覆盖所有地址、`size` 和 `burst` 编码，无输入限制。
- **容量与写字节选择的全输入 SAT：** 128 组，覆盖不同地址和字节通道宽度，容量包含 `1/2/3/7/8/15/16/31/32/63/64/65/1024/1031/32768/32769`。这些检查直接提取两份实际源码的表达式，覆盖扩展地址位、容量截断边界、2 的整数次幂与非2 的整数次幂容量。
- **四态输入检查：** 地址推进比较 655,360 组输入，容量与字节选择比较 32,768 组输入。检查已知输入结果，并逐位统计 X/Z 的传播。当前实现与参考实现的四态结果逐位一致。
- **实际 RAM 协议回归：** 生产实现与仿真实现各运行 14 个配置，每个配置包含固定等待和随机等待两种模式，共 56 项。覆盖 32/64 位数据、1024/1031 个存储字、1/3/4 个未完成请求，以及 1/2/3/8/17 个周期的首读延迟。检查精确字节数据、连续读写、窄传输、错误响应、完成标志和背压。

源码快照检查要求，除上述三个组合逻辑区域外，两份 RAM 源码与参考提交 `2297cb12deac56b476f9a2a656da4038a9d8a75c` 逐字节相同。测试同时核对生产实现与仿真实现的三个区域一致。各项报告保存源码、测试和映射结果的 SHA-256。

## 局部原生综合结果

生产配置为 `DP=32768`、`DW=64`、`AW=32`、`MEM_WORD_WIDTH=64`，读写各保留 4 个未完成请求，首读延迟为 2 个周期。数据容量为 2,097,152 bit，即 256 KiB。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 474 | 473 |
| 分布式 RAM LUT 位置 | 68 | 68 |
| 触发器 | 198 | 198 |
| CARRY4 | 15 | 15 |
| RAMB36E1 | 64 | 64 |
| RAMB18E1 | 0 | 0 |
| DSP48E1 | 0 | 0 |
| 最长寄存器间组合路径 | 9 级 | 9 级 |

测量采用普通 RTL 算术、`physical-cost`、`small-lut-area-cost=1`、最大 6 输入 LUT、500 ps 连线成本和 6667 ps 映射目标。未启用额外 DSP 算术替换。两项映射的组合图完整，ABC9 功能核对通过，映射进程树峰值内存均小于 200 MiB。

完整 SoC 的物理 LUT 数量需要整机布局统计。当前环境没有 Vivado，150 MHz 与器件实际组合路径级数仍需 Vivado 综合及布线时序报告确认。

## 复现命令

运行环境需要 Python 的 `pyosys`、Slang 插件、Icarus Verilog 和支持当前 SystemVerilog 源码的 Verilator。工具路径应加入 `PATH`，Python 依赖应加入 `PYTHONPATH`。以下命令从仓库根目录运行。

```bash
python3 test/soc_ram_next_addr/prove.py \
  --out /tmp/npu_soc_ram_address/formal
python3 test/soc_ram_next_addr/check_four_state.py \
  --out /tmp/npu_soc_ram_address/four_state
python3 test/soc_ram_next_addr/check_helpers_four_state.py \
  --out /tmp/npu_soc_ram_address/helpers_four_state
python3 test/conv_soc_ram/run.py \
  --rtl-source rtl/soc/soc_axi_ram.sv --verilator verilator-modern --jobs 1 \
  --out /tmp/npu_soc_ram_address/protocol/production
python3 test/conv_soc_ram/run.py \
  --rtl-source test/models/soc_axi_ram.sv --verilator verilator-modern --jobs 1 \
  --out /tmp/npu_soc_ram_address/protocol/model
python3 test/soc_ram_next_addr/prepare_measurement.py \
  --out /tmp/npu_soc_ram_address/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config /tmp/npu_soc_ram_address/inputs/cases.json \
  --cases reference current --through pre_lut --out /tmp/npu_soc_ram_address/pre
python3 scripts/fpga/remap_fpga_luts.py \
  --source /tmp/npu_soc_ram_address/pre/reference \
  --out /tmp/npu_soc_ram_address/mapped/reference \
  --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
  --wire-delay-ps 500 --delay-target-ps 6667
python3 scripts/fpga/remap_fpga_luts.py \
  --source /tmp/npu_soc_ram_address/pre/current \
  --out /tmp/npu_soc_ram_address/mapped/current \
  --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
  --wire-delay-ps 500 --delay-target-ps 6667
python3 test/soc_ram_next_addr/collect_report.py \
  --formal /tmp/npu_soc_ram_address/formal \
  --four-state /tmp/npu_soc_ram_address/four_state \
  --helpers-four-state /tmp/npu_soc_ram_address/helpers_four_state \
  --protocol-production /tmp/npu_soc_ram_address/protocol/production \
  --protocol-model /tmp/npu_soc_ram_address/protocol/model \
  --mapped-reference /tmp/npu_soc_ram_address/mapped/reference \
  --mapped-current /tmp/npu_soc_ram_address/mapped/current \
  --out /tmp/npu_soc_ram_address/measurement.json
```

协议脚本在每个配置的两种等待模式完成后释放编译目录，其余输出保留源码快照、日志和结果摘要。
