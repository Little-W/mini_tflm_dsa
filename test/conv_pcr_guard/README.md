# PCR 编译配置下的 Conv 安全回退

```sh
python3 test/conv_pcr_guard/run.py
```

需要 x86-64 Linux 和 GCC。所有临时对象、日志和 JSON 报告默认写入
`build/conv_pcr_guard/`；`--out` 可指定其他生成目录。本目录不保存结果或向量。

脚本分别编译 standalone PCR、NMSIS PCR、普通编译但无 Conv capability 三种
配置，链接真实生产 C driver 和 NMSIS 入口，通过 `DSA_MMIO_CUSTOM` 观察访问。
这是 host C 测试，没有执行 RTL、RISC-V 固件或性能测量。

PCR 配置使用 SIZE=16、IA slots=4、PS frames=8、panel max R/W=8/16、
PS pool=81920 B、PS_FORCE_RAW=0。每种低层构建都检查 WS/IS 两种 dataflow。
同一对齐形状在 PCR per-tensor 规划下合法；Conv 所需 per-channel 标志被
共享 planner 拒绝。因此 PCR 编译的 validate/execute 返回
`DSA_ERR_INVALID_DIM`（3），在此之前不会读取 MMIO，更不会发 START。
普通编译的 validate 成功，但硬件 capability 缺失时 execute 返回
`DSA_ERR_UNSUPPORTED`（0x80000002），仅进行能力寄存器读取。

真实 NMSIS probe 对合法但不支持的请求返回 0（未接管），让原软件内核继续。
测试先将 input/filter/output/bias/multiplier/shift 六个数组地址设为不可访问，
验证 probe 不读取它们。随后即时生成一个 3×3×1 输入、2×2 核、2 个输出通道
的用例，提供正常软件 scratch，运行真实 wrapper fallback，并将全部 8 个输出
与直接卷积加原始 NMSIS requantize 比较。两种 NMSIS 构建共核对 16 个输出。
所有路径要求零 MMIO 写、零 START。

构建命令和 GCC 实际头文件依赖 SHA 在生成报告中保存。`-Wno-unused-function`
仅用于容纳 PCR 选择后未使用的既有 static helper；生产源码未作删改。
