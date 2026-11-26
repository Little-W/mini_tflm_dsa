# 窗口接收计数

`vector_window_count_add` 将本拍元素数量加入完整接收计数。低位和值使用短加法，最高进位使用并行产生条件。高位每四位形成一个独立传播条件，各组预先归并较低完整组的传播结果。`vector_window_count_group` 结合该单比特前缀和低位进位，同时形成本组全部结果位。低位进位只参与末级修正，完整计数位宽和定宽回绕均保留。

```sh
python3 test/vector_window_count/run.py --out build/vector_window_count
python3 test/vector_window_count/run_formal.py --out build/vector_window_mask_formal
```

检查包含 6 种计数及增量位宽的无输入约束组合形式证明，以及普通、综合两种条件编译方式下共 360000 组四态比较。完整 `vector_engine_address` 与提交 `8b3728c008e6093095c8ade34aa4516145bc6005` 的逐周期等价证明覆盖完整公开端口，输入不受约束。

`run_formal.py` 另外直接提取生产地址模块中的有效掩码计数树和累计表达式，覆盖 `WINDOW_LANES=1、3、4、8、16、31、32` 七种配置。每种配置均比较全部掩码及完整 32 位累计值。

32 位计数、4 位增量配置在输入和输出处添加测量寄存器，按照整机相同的 LUT 资源权重进行映射，计算逻辑使用 45 个 LUT，最长寄存器间结构路径为 3 个组合单元。测量电路的 68 个触发器仅用于输入和输出寄存。
