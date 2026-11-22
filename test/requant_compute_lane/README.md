# 统一量化通道验证

`requant_compute_lane` 接收一个有符号 INT32 累加值、预处理乘数和七位右移量，在七个使能边沿后同时提供 INT8 与 INT16 结果。`i_s16` 选择偏移处理方式。配置在一次任务及其流水排空期间保持稳定。

## 算术阶段

| 使能边沿 | 操作 |
|---|---|
| 1 | 保存 INT32 输入；常规接口同时保存乘数 |
| 2 | 保存四个有符号乘法部分积 |
| 3 | 合并为完整 64 位乘积 |
| 4 | 完成 32、16、8 位粗移位并保存必要的保护位 |
| 5 | 完成 4、2、1 位细移位，生成商与最近偶数舍入增量 |
| 6 | 合并商、舍入增量和输出偏移 |
| 7 | 应用激活上下界和输出精度限制，保存结果 |

`p_delayed_parameters=1` 接收下一个边沿才到达的同步参数存储结果。数据首先进入输入寄存器，乘数在部分积计算时使用。该参数保持七个边沿的输出延迟，并与量化控制模块中的参数存储读取相配合。默认值为零，数据、乘数和移位量在同一输入边沿接收。

`i_en` 同时暂停数据和有效位。异步复位及 `i_clear` 清空有效位与输出；`i_clear` 的优先级高于 `i_en`。无效通道输出为零。

## 数值与控制检查

```bash
python test/requant_compute_lane/run.py \
  --out build/requant_compute_lane --verilator verilator --jobs 1 --variants generic
```

测试使用独立的 128 位整数除法与余数计算，覆盖全部 128 种移位量、乘法输入极值、两种精度、激活上下界、输出偏移、暂停、清空、复位和尾列屏蔽。C++ 测试启用未定义行为检查。当前检查完成 1,057,912 个周期、850,859 个有效输出、73,578 个暂停周期、3,129 次清空及 468 次复位。

通道裁剪、有效位与清空的形式和四态检查可运行 `python test/requant_compute_lane/run_formal.py --out build/requant_lane_control`。检查覆盖全部 100 个数值输入位，另完成 131,072 次四态比较，其中包含 12,480 次已知有效输出比较。

两级移位的完整输入形式检查位于 `test/requant_pipeline`。参数准备与模式选择分别由 `test/requant_parameter_prepare`、`test/requant_parameter_read` 检查。`test/requant_time_share` 与 `test/vector_shared_quant` 检查实际控制模块、存储、参数装载和任务共享行为。

## 映射检查

`synthesis_cases.json` 指向完整通道与普通算术依赖。映射后可将导出的 Verilog 文件传给 `run.py --variants mapped --mapped <文件>`，运行相同的独立数值测试。模块资源数量和组合级数应以对应源文件散列的实际映射结果为准。
