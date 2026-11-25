# Kernel 权重块存储

`kernel_loader_buffer` 生产参数为 `SIZE=16`、`DATA_WIDTH=16`。每个分块包含 16×16 个有符号 16 位元素，占 512 B；三个物理槽位共占 1.5 KiB。每列存储器的逻辑深度为 48，宽度为 16 位。

两个逻辑槽位接收和预取分块，第三个物理槽位保存正在发送的权重。`send_pending` 交换物理槽位编号。接收发送请求后的第二个周期输出首组元素，后续每周期输出一组，共输出 16 组。

## 存储实现

| 目标 | 实现 | 逻辑数据容量 |
| --- | --- | ---: |
| ASIC | 16 个 `RAMTP128X16` SRAM 宏 | 12,288 bit |
| FPGA | 16 个 48×16 同步 RAM，使用 `block` 综合提示 | 12,288 bit |

ASIC 存储通过 `regfile` 的 `p_asic_force_sram` 参数选择；该参数默认为关闭，由生产参数的 Kernel 列存储器启用。写入在下一时钟边沿提交，读取通过转发获取此前已接收的写入。同步读端在未使能时保持输出，同周期同地址读写返回写入前的数据。宏的物理容量合计为 32,768 bit。

## 验证

`check_structure.py` 检查 ASIC 宏数量及 FPGA 同步 RAM 的宽度、深度、端口和同地址读取属性。`tb_collision.sv` 使用 SRAM 模型检查生产参数下的同址读写以及随后的读取。`test/kernel_prefetch/run.py` 使用独立 DMA 数据模型检查完整加载器，覆盖 S8、S16、im2col、尾部分块、预取、丢弃、刷新以及装载和阵列输出同时进行的情况。

```bash
python3 test/kernel_asic_storage/check_structure.py \
  --source-root . --out build/kernel_asic_storage/structure

python3 test/kernel_prefetch/run.py \
  --source-root . --asic --bus-width 64 \
  --extra-source asic/rtl/smic40_sram_1r1w.sv \
  --extra-source test/asic_regfile/sram_model.sv \
  --out build/kernel_asic_storage/loader_bus64

verilator --binary --timing --assert -Wno-fatal --top-module tb_collision \
  -DASIC_SRAM -DASIC_SYNTHESIS --Mdir build/kernel_asic_storage/collision_obj \
  rtl/npu/loaders/kernel_loader_buffer.sv rtl/common/regfile.v \
  asic/rtl/smic40_sram_1r1w.sv test/asic_regfile/sram_model.sv \
  test/kernel_asic_storage/tb_collision.sv
build/kernel_asic_storage/collision_obj/Vtb_collision
```

`synth_dc.tcl` 使用 SMIC40 RVT TT 工艺库和 10 ns 时钟，对生产参数的独立模块进行 Design Compiler 综合并输出宏数量、面积和时序报告。执行前应确认脚本中的工艺库路径适用于当前环境。
