# 参数数组行末判断

`vector_parameter_row_end` 根据 DMA 返回字节索引、每拍字节数和当前参数数量，组合判断本拍是否覆盖参数数组末尾。每个参数占四字节，计算保留原有三十二位无符号扩展与回绕语义。

该模块独立完成比较，`vector_engine_address` 再结合读取状态、返回有效位和参数类型生成 `parameter_row_last_fire`。模块没有寄存器，公开返回次序、行数更新时机和控制周期保持一致。

模块映射边界保留至 LUT 映射。最终路径统计展开全部模块，并沿寄存器之间的完整连接计算逻辑级数。

## 检查范围

`run.py` 覆盖八组列索引宽度、元素数量宽度和总线拍字节数，包含较小总线与三十一位输入。普通配置和 FPGA 综合配置均执行无输入限制的形式等价及四态比较，总计 1,048,576 次四态比较。

完整 `vector_engine_address` 使用四种宏配置和两种读取阶段配置进行等价检查，同时比较全部公开输出与内部保存状态。

```sh
python3 test/vector_parameter_row_end/run.py --out build/vector_parameter_row_end
python3 test/vector_request_timing/check_address.py --reference 9e3e5d6a6f47befe6c86aceacad7999923206458 --out build/vector_parameter_address
```
