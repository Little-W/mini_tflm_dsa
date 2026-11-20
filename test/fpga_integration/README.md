# FPGA 实现分支的完整 NPU 仿真

```sh
python3 test/fpga_integration/run.py --verilator /path/to/verilator --jobs 2 --out build/fpga_integration
```

脚本读取 `config/npu_fpga.mk`，使用 `SIZE=16`、64 位数据总线、7 个 8 KiB 共享存储块、4 KiB 卷积缓存、16 个部分和帧和直接 INT32 部分和存储配置，执行完整 NPU 的 38 项数值与事务检查。

仿真对实际 RTL 启用 `SYNTHESIS` 和 `XILINX_FPGA`，使用 Yosys 附带的官方 `LUT1`、`LUT6`、`LUT6_2`、`MUXF7`、`MUXF8` 和 `DSP48E1` 功能模型。这样可以同时执行阵列权重加载、共享存储读选择、量化移位、偏置选择及 Softmax 的 FPGA 实现分支。

性能和内部状态统计保存在测试文件中。脚本为这些观察模块生成独立的仿真副本，启用其中的模块绑定与检查；实际 RTL 文件保持原样。输出报告记录生产配置、RTL 摘要、原语模型摘要、观察模块摘要、仿真命令和数值检查结果。

当前完整 NPU 测试依赖支持接口数组默认值的 Verilator。工具环境及综合方法见 [开源 FPGA 综合](../../docs/open_fpga_synthesis.md)。
