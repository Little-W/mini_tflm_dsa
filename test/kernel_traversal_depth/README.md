# 权重加载遍历计数时序验证

`kernel_loader_ctrl` 为四个遍历维度分别计算递增值。列计数使用五位分组的 `kernel_count_increment`，各组并行形成结果位的翻转条件。列边界同时检查当前值是否达到上限、下一值是否等于上限，并单独处理最大值递增后的回绕。计数保留完整的 `COUNT_WIDTH` 模运算。

本实现保留配置接收、清除、请求接收、遍历顺序、地址输出以及各公开信号的周期关系。寄存器数量保持不变。

## 功能验证

`run.py` 从实际源文件提取四个计数器的更新表达式和边界比较表达式，使用无约束组合 SAT 检查计数宽度 1、2、5、6、8、9、16、29、32、33、65。检查覆盖全零、全一、分组进位、比较边界以及所有其他二值输入组合。

同一入口分别展开参考实现和当前实现，进行完整控制器的逐周期等价检查。参数组合为：

| `SIZE` | `REG_WIDTH` | `COUNT_WIDTH` |
|---:|---:|---:|
| 16 | 32 | 29 |
| 1 | 8 | 1 |
| 4 | 16 | 16 |
| 16 | 32 | 33 |

验证包含所有公开输出和匹配的内部状态，不增加输入假设。`reference_controller.sv` 保存此次比较使用的控制器参考源码，验证输入和公共依赖均记录 SHA256。

## 同设置测量

独立综合参数为 `SIZE=16`、`REG_WIDTH=32`、`COUNT_WIDTH=29`，使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`。路径统计包含寄存器的数据端口与使能端口。

| 指标 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1279 | 1380 |
| 寄存器 | 663 | 663 |
| 最大寄存器间组合级数 | 14 | 14 |
| `load_col_in_group` 到 `load_repeat` | 14 | 9 |
| BRAM / DSP | 0 / 0 | 0 / 0 |

此表记录完整控制器独立映射结果。整机中相同计数路径的深度还受周围逻辑共同优化影响。测量入口保存映射网表、逐级路径和输入摘要，完整记录位于 `measurement.json`。

## 复现

在仓库根目录执行：

```bash
python test/kernel_traversal_depth/run.py \
  --out build/kernel_traversal_depth/formal

python test/kernel_traversal_depth/measure.py \
  --out build/kernel_traversal_depth/measurement
```

两个入口均支持 `--candidate` 和 `--reference-source`。综合入口还支持 `--lock-file`，可与其他大型综合任务共用文件锁。运行环境需要安装带 `read_slang` 的 `pyosys`。
