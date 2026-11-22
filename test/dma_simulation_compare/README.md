# 线性 DMA 末拍比较

跨字读取的末拍序号随描述符保存。响应阶段将当前拍数与保存的序号分组比较，结果参与末拍和传输完成判断。

非 `SYNTHESIS` 配置保留 `u_rsp_last_equal`，用于输入包含未知值时的逐位进位一致性比较。该实例及其专用操作数只在仿真配置中声明，综合配置直接使用保存序号的比较结果。公开接口、描述符容量和传输周期保持。

完整模块比较所用源文件 SHA256：`39cc592d23c832d57d4b698a306ed1130c2fa067bcbda6e7a4479089216b3b1d`。

## 验证结果

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| 完整非综合语句比较 | 通用、FPGA、ASIC 三种配置，各 8,462 个代码标记 | 逐个相同 |
| ASIC 完整模块状态等价 | 7 组参数、21,211 个状态和输出位 | 通过 |
| FPGA 完整模块状态等价 | 7 组参数、21,211 个状态和输出位 | 通过 |
| 综合预处理结构 | 专用仿真实例及其操作数 | 仅保留在非综合配置 |

完整模块证明涵盖 BUS_WIDTH 32、64、128，DATA_WIDTH 8、16、32，描述符容量 1、2、3、4，以及生产 SoC 使用的 SIZE64、CACHE_BLOCKS64 配置。外部输入未添加限制，比较包含所有公共输出和共同内部状态。

预处理比较保留每个运算符、标识符、常量和控制语句，仅忽略注释与空白字符。三种非综合配置的完整语句相同，因此四态输入下的整个模块行为保持。

## 运行

```bash
python test/dma_simulation_compare/run.py \
  --reference-root build/dma_simulation_compare/reference \
  --source-root . \
  --out build/dma_simulation_compare/verification
```

参考目录需要包含完整的 `rtl/npu/dma/axi_linear_block_dma.sv`。`validation.json` 保存源文件摘要、各配置检查结果和完整状态证明报告摘要。

当前公共算术接口与对应源码摘要见 [公共模块验证](../resource_neutral_arithmetic/README.md)。
