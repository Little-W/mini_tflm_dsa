# RTL 目录结构

当前 RTL 按功能域归档，避免历史上的 `basic/`、`top/`、`sub_modules/` 平铺式结构继续膨胀。

```text
rtl/
  common/          # 可被多个设计复用的 RAM/基础单元
  axi_top/         # AXI-Lite 控制接口
  soc/             # CPU 桥接、互连和外设
  soc_top.sv       # SoC 顶层
  npu/
    top/           # NPU 顶层
    control/       # 控制器和任务调度
    dma/           # block DMA 与 DMA client 仲裁
    loaders/       # IA / W / bias loader 及片上缓存
    compute/       # 脉动阵列、数据整理、累加与 de-diagonalizer
    buffers/       # partial-sum buffer / FIFO
    writeback/     # requant、s8 打包和 OA writer
```

Vivado 工程源文件由 `fpga/vivado/tflm_ai_dsa_soc/scripts/sources.tcl` 统一枚举；VCS 的 NPU 和模块测试从该目录读取源码。
