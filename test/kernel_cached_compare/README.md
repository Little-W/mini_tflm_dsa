# 已保存权重描述符的比较资格

处于 `PF_LOADING` 或 `PF_CACHED` 时，缓存命中使用已保存描述符的比较结果。`comparison_stored_ready` 由比较有效状态和比较来源决定，缓存命中与丢弃条件直接使用这一资格。新候选的稳定性检查继续服务于候选接收和后台空闲判断。

已保存描述符的资格与新候选字段相互独立。此表达式保持公开接口、缓存状态迁移和请求周期一致，并保留未知状态输入的四态行为。

元数据、行列尺寸、行列坐标和基地址分别形成完整比较结果，然后在同一寄存级汇合。结构边界保留在实际比较节点，尾部尺寸选择与其他比较树分别计算。

## 验证结果

- 全部二值控制输入通过组合等价证明。
- 12,288 次严格四态检查通过，覆盖缓存状态、比较来源、候选稳定性、匹配结果及传输完成的未知值和高阻值。
- 小配置、生产 32 位总线、生产 64 位总线的完整加载器逐周期等价证明通过。
- 32 位与 64 位总线分别通过 285 个加载任务和 72,960 项数值检查，分别使用 45,050 与 29,443 个周期；全部 C++ 编译单元启用 UBSan。
- 在生产参数下，逻辑 LUT 为 4,317，触发器为 2,337，DSP 为 13，RAMB18E1 为 16，最长寄存器间组合路径为 10 级，连接图完整。

```bash
python test/kernel_cached_compare/run_formal.py --reference 415a70a \
  --out build/kernel_cached_compare/formal
python test/kernel_prefetch/run.py --fpga --bus-width 32 \
  --out build/kernel_cached_compare/numeric32
python test/kernel_prefetch/run.py --fpga --bus-width 64 \
  --out build/kernel_cached_compare/numeric64
```

`validation.json` 保存源文件散列值、等价证明、数值检查和资源测量结果。
