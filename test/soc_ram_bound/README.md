# SoC RAM 地址越界预测

生产 `soc_axi_ram` 与测试存储器使用相同的组合地址计算。二次幂容量在地址容量边界处分别归并低位进位和高位地址，直接形成下一次读取的越界结果。低八位进位分别准备两组步长候选，步长最高位在末级选择一位结果，独立组合模块保留进位结果与容量判断之间的逻辑边界。中间地址按三位分组归并。

固定突发、扩展地址最高位和定宽回绕保持原表达式的结果，其余容量继续使用完整无符号比较。所有请求队列、响应寄存器、存储器读写边沿及 AXI 周期行为保持原有定义。未知步长采用完整移位表达式，保留标准四态行为。

## 验证结果

60 组地址宽度、数据宽度和存储容量配置通过组合形式证明，覆盖全部地址、步长、突发类型和请求选择输入，输入没有增加限制。低字节进位和完整越界输出通过 606,208 次四态比较，包含全部低八位四态地址与已知步长的组合、全部四态步长与已知低字节地址的组合，以及未知地址和控制的混合输入。

实际 RTL 的 20 组 AXI 协议测试全部通过，覆盖 32 位和 64 位数据、1,024 和 1,031 个字容量、1/3/4 个在途请求、1/2/4/8 周期首拍延迟，以及确定性和随机反压。检查包括窄传输、请求队列、越界响应、写入字节使能和连续传输。

256 KiB、64 位物理存储、32 位地址、读写各四个在途请求的完整模块测量如下。

| 指标 | 参考结构 | 当前结构 |
| --- | ---: | ---: |
| 逻辑 LUT | 510 | 505 |
| 分布式存储名义 LUT | 68 | 68 |
| 名义 LUT 总数 | 578 | 573 |
| 触发器 | 198 | 198 |
| RAMB36 | 64 | 64 |
| 最长寄存器组合路径 | 9 级 | 9 级 |

映射等价检查和连接图完整性检查均通过。完整 SoC 的连接路径和目标器件布局布线时序分别测量。`validation.json` 保存源码散列和验证结果，`measurement.json` 保存完整模块资源与连接路径。

## 复现

```bash
python test/soc_ram_bound/run.py --out build/soc_ram_bound/formal
python test/soc_ram_bound/check_four_state.py --out build/soc_ram_bound/four_state
python test/conv_soc_ram/run.py --rtl-source rtl/soc/soc_axi_ram.sv \
  --synthesis --jobs 1 --first-read-latencies 1 2 4 --out build/soc_ram_bound/protocol
python scripts/fpga/open_fpga_synth.py \
  --case-config test/soc_ram_bound/cases.json --cases soc_ram \
  --out build/soc_ram_bound/pre --through pre_lut
python scripts/fpga/remap_fpga_luts.py \
  --source build/soc_ram_bound/pre/soc_ram --out build/soc_ram_bound/mapped \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
  --max-lut-inputs 8 --small-lut-area-cost 1 --discard-abc9-temporaries
```
