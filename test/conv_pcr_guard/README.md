# Conv 能力选择与软件执行

```sh
python3 test/conv_pcr_guard/run.py
```

需要 x86-64 Linux 和 GCC。编译产物、运行日志和 JSON 报告默认写入
`build/conv_pcr_guard/`，可用 `--out` 指定生成目录。

测试编译 standalone、NMSIS 两个公开驱动接口，并覆盖 `PCR_ENGINE=0` 和
`PCR_ENGINE=1`。两个配置均使用统一计算路径，部分和数据池为 12 KiB。

每种构建在 WS、IS 两种方向下检查两种硬件能力：

- 提供 Conv 能力时，验证配置并提交一次硬件计算请求。
- 未提供 Conv 能力时，返回 `DSA_ERR_UNSUPPORTED`，保持零 MMIO 写入和零计算请求。

NMSIS 检查首先将输入、权重、输出、bias、multiplier 和 shift 数组设为不可访问，
验证能力检查可在不读取数组的情况下返回。随后生成 3×3×1 输入、2×2 卷积核与
两个输出通道，执行软件内核，并将八个输出逐项与直接卷积及 NMSIS 量化结果比较。
两种 NMSIS 构建合计检查十六个数值输出。

这是使用实际 C 驱动和 NMSIS 入口的主机测试。RTL 正确性与硬件周期由对应的
仿真测试测量。报告记录编译命令、源码摘要、可执行文件摘要及各配置的运行结果。
