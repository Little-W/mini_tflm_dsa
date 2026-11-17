# SoC RAM 验证

测试直接实例化 `rtl/soc/soc_axi_ram.sv`，覆盖 AXI32/AXI64 的读写行为、固件镜像初始化和 FPGA RAM 综合。

## AXI 读写

```sh
python3 test/conv_soc_ram/run.py --out build/conv_soc_ram
```

需要支持 `--binary --timing --assert` 的 Verilator。测试经 AXI 写口生成数据，检查窄读、完整总线宽度读取、混合传输尺寸排队、随机等待、响应暂停时的数据保持，以及 4 KiB 边界、RAM 尾部和非法请求后的继续执行。

RAM 支持总线宽度以内的 FIXED/INCR 传输。非对齐首拍按 AXI 规定选用有效 byte lane，后续 INCR 拍从传输尺寸边界递增地址。超出 RAM 范围、不支持的传输尺寸、WRAP/保留 burst、过长 FIXED burst 和跨 4 KiB 的请求返回 SLVERR。

默认配置包含 DP/outstanding 为 1031/4、1024/1、1031/3，AXI32/AXI64 均运行固定和随机等待测试。1031/4 配置还检查 1、2、3、8、17 个周期的首响应延迟。完整总线宽度的连续响应在命令内保持每周期一拍。

## 固件镜像与重新加载

```sh
python3 test/conv_soc_ram/run_images.py \
  --out build/conv_soc_ram_images --verilator verilator
```

普通 SoC 仿真接受 32 位 CPU 镜像。测试覆盖十六进制字、`@` 字地址、注释、下划线、稀疏覆盖和重新加载，并通过 RAM 内容和 AXI 读响应分别比较数值。

FPGA Tcl 的 `cpu_memory.tcl` 将输入补零到 `CPU_MEM_DP` 个 CPU 字，生成 `cpu32.mem` 和与物理总线宽度相同的 `cpu.mem`。AXI64 的第 `i` 个物理字为 `(cpu_word[2*i+1] << 32) | cpu_word[2*i]`。综合配置将 `MEM_WORD_WIDTH` 设为 `DW`，直接对物理 RAM 调用 `$readmemh`。AXI32 和 AXI64 均使用这些实际生成的镜像运行初始化仿真。

## RAM 综合与初始化位比较

```sh
python3 test/conv_soc_ram/check_synthesis.py \
  --out build/conv_soc_ram_synthesis --yosys yosys
```

需要包含 `read_slang` 的 Yosys，以及 Tcl 8.6。脚本执行以下检查：

- 通过生产 Tcl 转换完整和带地址指令的 CPU32 镜像。
- 检查 1024×32、512×64 的同步数据 RAM、关闭初始化和未指定初始化文件的配置。
- 逐字比较推导后的 RAM 初始化值，检查启用初始化时文件字宽与 RAM 数据宽度一致。
- 将 512×64 数据 RAM 映射为 Xilinx 7 系列 RAM，核对一个 `RAMB36E1` 的 512 个初始化字。
- 确认初始化过程不生成额外 RAM，记录命令、源文件摘要、存储器清单和检查结果。

结果保存在指定目录的 `summary.json`、Yosys 日志和生成的镜像中。
