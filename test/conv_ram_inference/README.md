# Conv 数据缓存 RAM 推断

```sh
python3 test/conv_ram_inference/run.py --yosys yosys
```

也可选择已安装的 `yowasp-yosys`。脚本从当前生产
`rtl/npu/conv/conv_sdp_ram.sv` 生成网表，默认将 `ram.json`、`status.json`
和 `yosys.log` 写入 `build/conv_ram_inference/`；`--out` 可覆盖目录。
不读取已有网表或历史综合报告。

检查通用 `$mem_v2` 必须为 1024×32 bit、一个同步读端口、一个同步写端口和
四个独立字节写使能。数据阵列没有复位；同地址同时读写由缓存状态机禁止。

这是逻辑 1R1W RAM 推断检查。没有目标器件 RAM 映射、完整 NPU 综合、tag
阵列面积评估、布局布线或静态时序，不能据此报告 BRAM 宏数量、面积、Fmax
或功耗。工具版本、实际命令、源码 SHA 和检查结果由每次执行产生。
