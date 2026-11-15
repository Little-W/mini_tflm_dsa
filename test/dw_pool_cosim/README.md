# DW、池化与向量运算的 C/RTL 协同仿真

本测试编译生产 NMSIS 入口与 `dsa_dw_pool_execute()`，通过真实 AXI-Lite
寄存器接口执行 `npu_axil_top`，数据存储使用生产模块 `soc_axi_ram`。

## 运行

需要 GCC、G++、Python 3、GNU Make 和支持 SystemVerilog 的 Verilator。

```bash
python3 test/dw_pool_cosim/run.py --size 16 --pe-count 4 --out build/dw_pool_cosim/pe4
python3 test/dw_pool_cosim/run.py --size 16 --pe-count 8 --out build/dw_pool_cosim/pe8
python3 test/dw_pool_cosim/run.py --size 16 --pe-count 8 --disabled --out build/dw_pool_cosim/disabled
python3 test/dw_pool_cosim/run.py --size 16 --pe-count 8 --pcr --out build/dw_pool_cosim/pcr
```

可用 `--verilator /path/to/verilator` 指定工具路径，使用 `--jobs` 控制编译并行度。
`--skip-build` 只接受与源文件摘要、参数和编译模式一致的现有构建。

## 检查内容

- DW：1×1、3×3、5×5、7×7，矩形卷积核，步长为 2，膨胀系数为 2，
  通道尾部，空 bias，正量化 shift，两批输入，以及同一地址更新输入后再次执行。
- 池化：平均值、最大值、最小值，边缘窗口，有效元素计数，正负半整数舍入，
  通道尾部和多批输入。
- 向量：s8/s16 求和、最大值、最小值、点积、Hadamard 积；长度为 1、3、17、65，
  有符号极值、32 位累计回绕、跨 4 KiB 地址和输出保护字节。
- 软件选择：depth multiplier 为 2、超过 32 位地址空间的输入指针，以及硬件能力关闭。
- 模式切换：普通 Conv WS → DW → 池化 → Conv IS → DW，以及向量 → Conv WS → DW。
- 无效配置：零向量长度、未知操作、未满足 s16 地址要求和地址范围溢出均在 START 前返回。
- 不支持的硬件配置：检查能力寄存器、驱动拒绝，以及直接写 START 后的错误完成、IRQ
  与无外部访存行为。PCR 配置编译实际 `GEMPACT_PANEL_ENGINE` 和 `GEMPACT_PCR_PS` 分支。

DW、平均池化和最大池化的预期结果由本仓库 NMSIS 标量实现计算。
参考对象通过 `DSA_NN_DW_POOL_ENABLE=0` 关闭加速分发，并使用独立的函数名称链接。
最小池化与向量使用独立整数计算。

硬件命令执行期间，对 CPU 地址空间中的输入、权重、bias、量化参数和输出设置
`PROT_NONE`。CPU 驱动只能操作配置寄存器；RTL 使用 AXI RAM 内的对应数据。
仿真分别运行固定等待与随机等待两种存储响应。

## 结果

输出目录包含 `summary.json`、编译记录、源文件 SHA-256，以及 `fixed.log` 和
`random.log`。通过标志为 `DW_POOL_C_RTL_COSIM_PASS`。

结果中的 `cycles` 是 Verilator 时钟周期，包含 C 驱动引发的 MMIO 访问和硬件运算。
主机直接执行 C 指令所花的时间未转换成 RISC-V 周期；软件分支检查用于验证数值和选择行为。
