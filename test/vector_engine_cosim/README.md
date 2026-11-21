# 生产驱动与 RTL 联合仿真

测试通过实际 AXI-Lite、NPU、DMA 和 AXI RAM 调用生产 NMSIS 函数及 VCE 驱动。
硬件执行期间，测试将输入、参数和输出对应的主机地址设为不可访问，保证结果来自
RTL 执行。每个算子完成后逐元素核对输出，并检查输出区前后的保护字节。

## 覆盖内容

测试覆盖 DW、Conv 与 GEMM 的任务切换、小窗口和全局池化、INT8 Add、有符号向量
运算、通道尾部、非整字地址的 INT8 数据、4 KiB 边界，以及固定和随机外存延迟。
Add 使用 ResNet-8 的三组量化参数，并检查舍入、输出饱和、相同输入和原位软件执行。

启用共享 RAM 时，测试交替提交矩阵和向量任务，并从 CSR 读回矩阵任务实际选择的
IA bank 数量。八个或九个 bank 配置覆盖 1、2、4 个 IA bank，较小配置覆盖其支持
的分配。任务复用外存地址并改变内容，随后逐元素检查，确认新任务使用本次装载的数据。

错误测试包括权重读取、输入读取和结果写入的实际 AXI 越界响应，以及存储适配器和
物理共享 RAM 的错误注入。测试核对错误码，在不复位整个设备的情况下继续提交
DW 和 GEMM/Conv，并检查后续数值结果。故障注入仅位于测试模块中。

## 运行

默认的独立存储配置：

```bash
python3 test/vector_engine_cosim/run.py \
  --out build/vector_engine_cosim \
  --verilator /path/to/verilator --jobs 2 --size 16 --pe-count 8
```

共享 RAM、AXI64、16 个 VCE PE 和完整共享量化：

```bash
python3 test/vector_engine_cosim/run.py \
  --pcr --size 16 --pe-count 16 --bus-width 64 \
  --bank-bytes 4096 --bank-count 8 --cache-bytes 8192 \
  --target generic --out build/vector_engine_cosim_shared \
  --verilator /path/to/verilator --jobs 2
```

`--target generic` 使用固定 PS 通道；`--target asic` 选择生产 RTL 的轮转 bank 映射。
`--pcr` 使用已有 IA/PS 共享 RAM 和 RAW32 部分和格式。存储块大小支持 2、4、8 KiB，
总数支持 6 至 9 个。`--disabled` 验证 VCE 不可用时的软件执行选择。

每次运行均测试固定和随机 DDR 延迟。`summary.json` 保存源码摘要、构建命令、
执行文件摘要、实际能力和分配检查，以及每个场景的结果。
`--skip-build` 仅在构建输入、参数和执行文件摘要一致时复用已有仿真器。

计时包含 C 驱动的 AXI-Lite 访问；主机 CPU 指令执行不计入周期。
完整 RISC-V 推理测量由 `test/model_benchmark` 提供。
