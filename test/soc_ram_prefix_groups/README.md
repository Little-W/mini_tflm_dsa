# SoC RAM 地址前缀分组

`axi_next_addr` 按六位片段并行计算高位字节的进位前缀。高位字节预先准备递增值，再根据低八位和高位前缀的完整进位条件选择保持值或递增值。地址寄存器、读写队列和 AXI 接收周期保持相同。生产 RAM 与仿真 RAM 使用相同的地址函数。

## 功能检查

完整地址函数在 `AW=1/3/7/8/9/16/24/32/40/65` 下通过全部输入 SAT 证明，涵盖扩展地址位及所有 `size`、`burst` 编码。地址容量和写字节选择另外完成 128 项参数证明，其他时序与队列代码逐字节比较。

四态仿真完成 655,360 组输入比较，所有输出位保持相同的已知值和 X/Z 传播。生产 RAM 的 12 项实际协议测试覆盖 32/64 位总线、1/3/4 项未完成请求、1024/1031 个数据字、2/8 个周期首读延迟，以及固定等待和随机等待。测试检查准确的字节数据、窄传输、错误响应、完成状态及接收暂停。

## 完整 RAM 映射

保留 256 KiB 数据容量，参数为 `DP=32768`、`DW=64`、`AW=32`、`MEM_WORD_WIDTH=64`，读写各 4 项未完成请求，首读延迟为 2 个周期。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 名义 LUT 数量 | 569 | 578 |
| 完整模块最长寄存器间路径 | 9 | 9 |
| 写地址寄存器到写地址寄存器 | 8 | 7 |

两次映射采用相同的 `physical-cost` 配置，最大 LUT 输入数 8，目标周期 6,667 ps，布线延迟参数 300 ps。完整 SoC 的实际连接路径由整机测量报告记录。

## 运行

```sh
python test/soc_ram_next_addr/prove.py --reference 07a199ac \
  --out build/soc_ram_prefix_groups/formal
python test/soc_ram_next_addr/check_four_state.py --reference 07a199ac \
  --out build/soc_ram_prefix_groups/four_state
python test/conv_soc_ram/run.py --rtl-source rtl/soc/soc_axi_ram.sv \
  --synthesis --first-read-latencies 2 --out build/soc_ram_prefix_groups/protocol
python test/soc_ram_next_addr/prepare_measurement.py --reference 07a199ac \
  --out build/soc_ram_prefix_groups
python scripts/fpga/open_fpga_synth.py \
  --case-config build/soc_ram_prefix_groups/cases.json --cases reference current \
  --out build/soc_ram_prefix_groups/mapping --through pre_lut
python scripts/fpga/remap_fpga_luts.py \
  --source build/soc_ram_prefix_groups/mapping/current \
  --out build/soc_ram_prefix_groups/cost/current --mode physical-cost \
  --delay-target-ps 6667 --wire-delay-ps 300 --max-lut-inputs 8 --discard-abc9-temporaries
```

对参考模块执行相同映射命令，将两个目录中的 `current` 同时替换为 `reference`。`validation.json` 与 `measurement.json` 保存参数、源码摘要和检查结果。
