# 图像命令列数保存

`axi_block_dma_arbiter` 在接受命令之前计算图像读取使用的有效列数，并与原始命令字段在同一时钟边沿保存。向量客户端的零列数或越界列数采用完整分块宽度，其余客户端采用对应的固定块宽。复位时保存完整图像块宽。

`axi_dual_block_dma` 的 `p_prepared_image_columns` 参数控制是否读取 `rd_image_columns`。仲裁器启用该参数，直接向描述符入口提供保存结果；独立使用时，参数缺省关闭，模块根据原始 `rd_valid_cols` 计算列数。两种配置保留全部命令接收、保持、复位和响应周期。

## 已完成的验证

- 12 组无界归纳覆盖 1～64 位原始字段、二次幂与其他分块尺寸，以及完整客户端编号。
- 196,620 次四态比较覆盖每个输入位的 0、1、X、Z，包含连续接收、暂停保存和复位。
- 两种配置各 7 组完整双 DMA 比较，共检查 32,470 个状态、公开输出和子模块接口位。子模块返回信号及公共输入保持任意取值。
- 新配置的完整比较使用已由字段保存证明建立的关系：保存列数等于当前原始命令字段的范围处理结果。

```bash
python test/dma_image_admission/check_prepared_columns.py --out build/dma_image_columns/field_capture
python test/dma_image_admission/run_formal.py --reference-rev e62697bb --out build/dma_image_columns/default_control
python test/dma_image_admission/run_formal.py --reference-rev e62697bb --prepared-image-columns --out build/dma_image_columns/prepared_control
```

结果及源码摘要保存在 `prepared_columns_validation.json`。
