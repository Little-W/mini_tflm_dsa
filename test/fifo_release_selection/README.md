# FIFO 写入目标银行选择

## 行为

`vec_s8_to_fifo_full` 在采用计数存储的银行配置下，先确定下一周期的写银行及相邻银行，再分别计算这两个银行的释放条件。每个目标银行先读取当前有效状态，随后按释放优先、写入完成其次的顺序更新阻塞结果。

写银行推进与独热位置使用同一个完成条件。其他银行仍独立更新 `bank_ready_next`，数据存储端口、输出顺序、寄存器数量和接口周期保持原有行为。其余银行配置继续使用并行银行状态归并。

## 自动检查

| 检查 | 结果 |
| --- | --- |
| FPGA 存储配置 | 10 个参数组合，一步归纳通过 |
| 通用存储配置 | 10 个参数组合，一步归纳通过 |
| 非预计算水位 | 生产参数，一步归纳通过 |
| 保存状态关系 | 6 项关系直接与常数一比较，并与完整状态共同从复位证明 |
| 四态周期检查 | 2 种模式，各 11 个参数组合、1024 周期，共 1,849,100 次比较 |
| 32 位数值检查 | 81 项，12,392 字节，7,196 周期，周期差异为 0 |
| 64 位数值检查 | 81 项，12,392 字节，4,522 周期，周期差异为 0 |

形式检查只要求第一个采样周期复位，后续功能输入、复位与数据 RAM 返回输入均保持自由。待证明关系包含两个阻塞寄存器、行计数保存值、独热写入位置及写银行范围。

四态检查保留实际控制、存储命令和状态更新表达式；两份事件模型均把 `always_comb` 转换为 `always @*`，比较各周期的状态、公开输出和存储命令。

## 局部映射与完整连接路径

采用 16 路向量、32 个银行、64 位总线和循环存储参数。统计来自映射网表，端口路径使用实际 LUT 真值表、进位方向和 DSP 寄存边界。

| 项目 | 参照实现 | 当前实现 |
| --- | ---: | ---: |
| 名义 LUT 数量 | 1233 | 1249 |
| FF | 173 | 173 |
| DSP | 1 | 1 |
| RAMB18 | 8 | 8 |
| 模块内部寄存器间最长路径 | 10 | 10 |
| 合并尺寸输入到两个阻塞寄存器 | 11 | 7 |
| 合并尺寸输入到任一内部时钟存储终点 | 11 | 9 |

`measurement.json` 保存各路径的实际单元、连接与终点。参照 RTL 来自 `8aa34632`，源文件及脚本散列保存在 `validation.json`。

## 复现

```bash
python test/fifo_release_selection/run_formal.py --reference 8aa34632 --out build/fifo_release_selection/formal_fpga
python test/fifo_release_selection/run_formal.py --reference 8aa34632 --generic --out build/fifo_release_selection/formal_generic
python test/fifo_release_selection/run_formal.py --reference 8aa34632 --profile v16_n32_b64_c1 --precomputed-watermark 0 --out build/fifo_release_selection/formal_watermark
python test/fifo_read_qualification/run_cycle.py --reference 8aa34632 --bus-width 32 --out build/fifo_release_selection/numeric32
python test/fifo_read_qualification/run_cycle.py --reference 8aa34632 --bus-width 64 --out build/fifo_release_selection/numeric64
python test/fifo_write_blocked/run_four_state.py --reference 8aa34632 --cycles 1024 --out build/fifo_release_selection/four_state
python scripts/fpga/open_fpga_synth.py --case-config test/fifo_release_selection/cases.json --cases current --rtl-dsp-attributes --wide-alu-dsp-budget 740 --out build/fifo_release_selection/mapped
python test/fifo_release_selection/measure_paths.py --reference build/reference_fifo/current --current build/fifo_release_selection/mapped/current --out build/fifo_release_selection/measurement.json
```
