# Kernel 权重块存储

`kernel_loader_buffer` 保存阵列输入前的计算分块。生产参数为 `SIZE=16`、`DATA_WIDTH=16`，一个分块包含 16×16 个有符号 16 位元素，占 512 B。模块共有三个物理槽位，合计 1.5 KiB。

## 槽位与预取

| 用途 | 数量 | 控制方式 |
| --- | ---: | --- |
| 等待发送或正在装载的分块 | 2 | `slot_reserved`、`slot_loaded` 和一位逻辑槽位编号 |
| 正在向阵列发送的分块 | 1 | `active_storage` 保存物理槽位编号 |

`send_pending` 将队首分块的物理槽位与活动槽位交换，逻辑槽位随后可接收下一块数据。交换只更新槽位编号，矩阵数据保留在原存储位置。接收发送请求后的第二个周期输出首组元素，后续每周期输出一组，共输出 16 组。

每列存储器保存三个分块在该列的全部元素，因此列深度为 `3×SIZE=48`，列宽为 16 位。16 个列存储器各有独立读取地址，用于生成阵列需要的对角排列。全部列同步接收同一输入行。

## 资源选择

| 目标 | 生产配置的实现 | 矩阵数据容量 |
| --- | --- | ---: |
| ASIC | 公共 `regfile` 选择寄存器数组，SRAM 宏数量为 0 | 12,288 bit |
| FPGA | 16 个深度 48、宽度 16 的推断同步 RAM，保留 `block` 综合提示 | 12,288 bit |

公共 `regfile` 是描述读写行为的 RTL 模块，实际存储形式由目标配置和容量条件选择。ASIC 小数组使用准确的逻辑深度，避免为每列分配 128 个地址。同步读端在未使能时保持输出，同周期同地址读写返回写入前的数据。

128×16 SRAM 宏的深度可容纳八个 16 行分块。若采用该容量并增加有效预取，需要同时扩展逻辑槽位数量、槽位编号、DMA 上下文和预取描述符队列。当前调度器保存两项逻辑槽位和一个命令预取描述符，三个物理槽位满足这一调度容量。

## 验证

`check_structure.py` 检查生产参数的完整 1.5 KiB 容量、逐列端口数、同步读写属性和同地址读取行为。ASIC 配置进一步将数组展开为寄存器，检查 SRAM 宏数量为零、没有存储单元或锁存器残留，并统计寄存器位数。FPGA 配置检查推断存储器的宽度、深度和端口属性。

`test/kernel_prefetch/run.py` 使用独立 DMA 数据模型检查完整加载器，覆盖 S8、S16、im2col、尾部分块、预取命中、在途预取、丢弃、刷新，以及装载和阵列输出同时进行的情况。`validation.json` 保存本次源文件摘要与运行结果。

| 验证项目 | 参数与覆盖范围 | 结果 |
| --- | --- | --- |
| 完整加载器 | BUS_WIDTH 为 32、64、128；共 855 个分块、218,880 个输出值 | 通过 |
| 四态行为 | DATA_WIDTH 为 8、16；共 12,168 周期、292,032 次检查 | 通过 |
| ASIC 存储结构 | 0 个 SRAM 宏、12,288 个数据位；模块展开后共 12,876 个寄存器位 | 通过 |
| FPGA 存储结构 | 16 个 48×16 同步 RAM | 通过 |

局部 XC7 综合使用 `synth_xilinx`，参数 `SIZE=16`：

| DATA_WIDTH | LUT | FF | RAMB18 | DSP | 最长寄存器间组合级数 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | 546 | 204 | 16 | 0 | 7 |
| 16 | 994 | 332 | 16 | 0 | 7 |

两个局部综合网表的寄存器路径图均完整。`DATA_WIDTH` 控制模块内部元素宽度，当前生产设计使用 16 位；输入 S8 模式也由该 16 位存储处理。

生产宽度 16 位的存储形式比较如下。表中合计包含组合逻辑 LUT 与分布式存储占用的名义 LUT 数量。

| `p_ram_style` | 逻辑 LUT | LUTRAM | 合计 LUT | FF | RAMB18 | 最长寄存器间组合级数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `block` | 994 | 0 | 994 | 332 | 16 | 7 |
| `auto` | 999 | 384 | 1,383 | 588 | 0 | 7 |
| `distributed` | 999 | 384 | 1,383 | 588 | 0 | 7 |

`auto` 与 `distributed` 均映射为 96 个 `RAM64M`，可以释放 16 个 `RAMB18`，同时增加 389 个名义 LUT 和 256 个 FF。三种配置的寄存器路径图均完整。生产设置保留 `block`，控制整体 LUT 使用量；候选综合使用独立源码副本。

```bash
python3 test/kernel_asic_storage/check_structure.py \
  --source-root . --out build/kernel_asic_storage/structure

python3 test/kernel_prefetch/run.py \
  --source-root . --asic --bus-width 64 \
  --extra-source asic/rtl/smic40_sram_1r1w.sv \
  --extra-source test/asic_regfile/sram_model.sv \
  --out build/kernel_asic_storage/loader_bus64

python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/kernel_asic_storage/synthesis_cases.json \
  --cases kernel_buffer_s8 kernel_buffer_s16 \
  --source-root . --out build/kernel_asic_storage/fpga
```

结构检查给出存储容量、宏数量及寄存器位数；工艺面积和频率由对应目标的综合及静态时序报告确定。
