# RTL 目录结构

RTL 按功能域组织。

```text
rtl/
  common/          # 可被多个设计复用的 RAM/基础单元
  axi_top/         # AXI-Lite 控制接口
  soc/             # CPU 桥接、互连和外设
  soc_top.sv       # SoC 顶层
  npu/
    top/           # NPU 顶层
    control/       # 控制器和任务调度
    dma/           # block DMA、窗口队列、读取缓存与 DMA client 仲裁
      cache/       # im2col 输入缓存、缓存 RAM 和替换预测器
    conv/          # im2col、卷积地址生成与向量运算
    loaders/       # IA / W / bias loader 及片上缓存
    compute/       # 脉动阵列、数据整理、累加与 de-diagonalizer
    buffers/       # partial-sum buffer / FIFO
    ps_compact/    # 部分和压缩、解压与压缩帧存储
    writeback/     # requant、s8 打包和 OA writer
```

Vivado 工程源文件由 `fpga/vivado/tflm_ai_dsa_soc/scripts/sources.tcl` 统一枚举；VCS 的 NPU 和模块测试从该目录读取源码。
