# 向量引擎共享存储返回历史检查

本检查对实际 `vector_engine` 及其全部依赖模块进行时序归纳证明，使用生产参数 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64`、`WINDOW_LANES=8`、`SHARED_STORAGE_ENABLE=1`。外部功能输入保持自由，不限制任务配置、返回数据或握手序列。

检查以观察到复位之后的状态为起点，每次 `CHECK` 清除边沿重新开始记录本任务的返回历史。证明包含以下性质：

- 首次 PS 返回之前，不启动量化，不发布共享量化请求，也不执行本地 `q_accumulator` 的有效捕获。
- 首次权重返回之前，不发生 `dw_issue_fire`。
- PS 返回保持标志、量化输入活动标志、权重保存有效标志均要求本任务已经收到对应存储返回。

证明允许返回有效信号与使用条件出现在同一周期。PS 返回有效信号下降之后，本地量化仍可使用保持的返回数据；该使用条件同样包含在检查范围内。

运行命令：

```sh
python test/vector_shared_epoch/run_formal.py --out build/vector_shared_epoch_validation
```

`--source-root` 可指定其他源码目录。脚本分别检查普通 RTL 与 `SYNTHESIS`、`XILINX_FPGA` 定义，以及本地量化和共享量化，共四种配置。输出记录完整依赖文件的 SHA-256、证明脚本和日志。

`validation.json` 保存已完成检查的结果。该检查只观察控制和使用条件，不改变生产 RTL 的接口、状态或存储行为。
