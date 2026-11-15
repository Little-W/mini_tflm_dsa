# SoC RAM 窄读回归

本测试直接实例化生产文件 `rtl/soc/soc_axi_ram.sv`，并经其 AXI 写口初始化存储器。没有以软件模型代替 RAM RTL。

```bash
python test/conv_soc_ram/run.py
```

要求 PATH 中有支持 `--binary --timing --assert` 的 Verilator。编译产物写入临时目录并自动清理；完整编译与仿真日志在 `build/conv_soc_ram/`。输入通过 testbench 的 AXI 写口即时生成，不需要已有向量。

## 修改范围

原 RAM 的 AR 队列只保存地址和长度，活动读地址按每拍一个完整 word 递增。因此 byte/halfword 连续读会读错下一拍，窄读请求跨多个 beat 时不能用于硬件 im2col。

修复后，AR 队列还保存 size、burst 和命令检查结果；活动地址以字节为单位递推，并保留地址空间溢出的进位。支持总线位宽以内的 FIXED/INCR 读；32 位总线对应 ARSIZE=0/1/2。非对齐首拍只承诺 AXI 规定的有效 byte lane，后续 INCR 拍从 transfer size 对齐地址递增。其余 lane 可以包含同一物理字中的数据，主设备必须按有效 lane 使用。

不支持的 size、WRAP/保留 burst、过长 FIXED burst，以及跨 4 KiB 的请求，均返回规定长度的 SLVERR 响应。超出 RAM 实际 DP 的读也返回 SLVERR 和零数据。范围检查适用于非 2 的幂的 DP；地址溢出不会读到低地址别名。写通路没有因窄读功能而改变。

原有同步 RAM 读和连续响应流水仍保留。测试检查完整 word 的拍间连续性；outstanding=3/4、无等待时，连续 256 个响应占用 255 个拍间间隔，即每周期一拍。outstanding=1 保留原有跨命令气泡，命令内仍保持连续。

## 固定回归配置

默认检查 DP/outstanding 为 1031/4、1024/1、1031/3，每组分别使用固定和随机
等待。测试包含混合 size 排队、随机 AR/R 延迟和 RREADY、停顿时 payload 保持、
4 KiB 边界、非对齐首拍、FIXED、RAM 尾部、高地址、非法请求和错误后继续执行。
每轮结果写入 `build/conv_soc_ram/modified_status.json` 及对应日志。

可显式选择本地已有的原始 RAM 版本，验证它在窄读用例上的预期失败：

```sh
python3 test/conv_soc_ram/run.py --baseline-commit 148964d180f52cb852c5a7e3d5c89773fa0a8ea5
```

该可选命令需要本地存在指定 Git 对象；正常当前 RTL 回归不依赖历史源码包或
历史结果。这些测试属于 RAM 模块功能和周期验证，不证明完整 SoC 功能，也不
构成综合面积或物理时序结论。
