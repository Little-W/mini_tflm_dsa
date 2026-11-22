# FPGA 生产配置的完整 NPU 仿真

```sh
python3 test/fpga_integration/run.py --verilator /path/to/verilator --jobs 1 --out build/fpga_integration
```

脚本读取 `config/npu_fpga.mk` 与 SoC 生产参数，使用 `SIZE=16`、64 位数据总线、7 个 8 KiB 共享存储块、4 KiB 卷积缓存、16 个部分和帧，以及 RAW 部分和存储配置。向量处理单元数量、地址位宽、INT16 输出 FIFO 容量均与 `soc_top` 综合入口一致。

仿真对实际 RTL 启用 `SYNTHESIS` 和 `XILINX_FPGA`。乘加、移位和比较使用统一的普通 RTL，存储行为来自设计中的可综合数组。观察模块检查状态、数据顺序、反压与帧地址，单独加入的帧观察模块同时检查十二周期配置准备间隔。

一次编译依次运行 38 项功能任务、21 项容量任务、15 项输出任务和 12 项打包布局任务。每项任务使用独立的软件数值结果检查存储内容，报告保存各类别的任务结果与帧统计。观察模块使用启用断言的仿真副本，实际 RTL 文件保持原样。

`--source-root` 可指定固定的 RTL 目录。结果包含生产配置、参与编译的源文件摘要、观察模块摘要、仿真命令、检查数量及通过状态。当前测试需要支持接口数组默认值的 Verilator。综合网表资源与布局布线时序使用独立的综合流程测量，见 [开源 FPGA 综合](../../docs/open_fpga_synthesis.md)。
