# 不变式（Invariants）推理 before/after 演示包

面向组会投屏的演示：展示 `feature/spec-invariants` 分支为 spec 新增的可选
`invariants` 字段，以及 reasoner 对**连续 / 不终止行为**（`while True` 事件循环这类
"永不 return" 的函数）的逐块不变式检查能力。

> **重要说明 / NOTE**
> 本目录有两个演示脚本，区别只在"判断从哪来"，管线都是 `src/reasoner.py` 的真实代码：
>
> - `run_demo_llm.py`（推荐用于汇报）：三处需要模型判断的环节（生成块后条件、
>   后条件对照 spec、逐块不变式检查），判断内容由大模型真实阅读演示代码后给出、
>   离线录入回放，**无需 API key**。
> - `run_demo.py`：判断由确定性规则替代，用于无模型环境下核对管线行为。

## 演示目标

`stream_processor.py`：一个不终止的流处理循环（`while True`，永不显式 return），
不变式为 **`buffer` 中未处理元素数任意时刻不超过 `CAPACITY = 8`**。

- **buggy 版**：收到 batch 后未检查剩余容量就 `buffer.extend(batch)`，突发流量下
  buffer 会瞬时超限，违反不变式。
- **fixed 版**（`stream_processor_fixed.py`）：extend 前先检查
  `len(batch) > CAPACITY - len(buffer)`，不足时先 `flush` 排空，不变式恒成立。

这类"运行途中任意时刻都要成立"的性质用传统 pre/post 条件表达不了——函数根本不返回，
旧流程只剩"末尾隐式 return"一次无效的后条件检查，bug 完全不可见。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `stream_processor.py` | 演示目标（buggy 版，37 行） |
| `stream_processor_fixed.py` | 对照修复版（结构相同，extend 前有容量守卫） |
| `buggy.spec.json` / `fixed.spec.json` | spec 字典示例，含新字段 `invariants` |
| `run_demo_llm.py` | 演示脚本（大模型判断离线录入回放，跑真实 reasoner 管线） |
| `run_demo.py` | 演示脚本（确定性规则替代判断，跑真实 reasoner 管线） |
| `demo_output_llm.txt` / `demo_output.txt` | 两个脚本各自的一次真实运行输出（可直接截图进 PPT） |

`*.spec.json` 的格式即管线生成的 sidecar 格式，新字段长这样：

```json
{
  "signature": "run_stream_processor(source, sink, metrics)",
  "pre_condition": "source 与 sink 已连接可用；……",
  "post_condition": "正常运行期间不返回；仅在收到 shutdown 时退出循环，退出前 buffer 已排空……",
  "invariants": "任意时刻 len(buffer) <= CAPACITY（CAPACITY = 8），……"
}
```

## 怎么跑

脚本本身无第三方依赖，但需要项目环境来 `import src.reasoner`（系统 python3 版本太旧，
请用 uv 或项目 venv）：

```bash
uv run python docs/examples/invariants-demo/run_demo_llm.py   # 大模型判断版（推荐）
uv run python docs/examples/invariants-demo/run_demo.py       # 确定性规则版
```

脚本会把 `GRANULARITY` monkeypatch 成 10，让 30+ 行的演示函数被真实切成 3 块，
并打印每块的行号边界与逐块检查过程。

## 三个场景的预期输出

- **场景 A（before）**：buggy 代码 + 不含 `invariants` 的旧式 spec。
  reasoner 解析不到 Invariants 段，函数又没有显式 `return`，只剩最后一块
  "末尾隐式返回"的后条件检查（桩恒通过）→ 返回
  `The function passes the verification...`，**bug 不可见**。
- **场景 B（after）**：buggy 代码 + 含 `invariants` 的同一份 spec（`all_bugs=True`）。
  每块都过一遍不变式检查，块 2（`Line 11 ~ Line 20`）里 `buffer.extend(batch)`
  前无容量守卫 → 判定违反。最终 `status: MISMATCH`，违规条目带
  `kind=invariant`、触发语句 `Line 20: buffer.extend(batch)` 与原因。
- **场景 C（after 对照）**：fixed 代码 + 同一份 spec。块 2 里检测到容量守卫
  （`CAPACITY` / `flush`）→ 全部通过，最终 `status: MATCH`。

完整输出见 `demo_output_llm.txt`（大模型判断版）与 `demo_output.txt`（确定性规则版）。

## 真实端到端验证指南（有 LLM key 的机器）

上面的两个演示脚本都不接 API：判断要么由大模型离线给出后回放，要么由确定性规则代替。
要在真实模型下端到端验证，找一台配好环境的机器：

1. 配置 key（参考根 README 的 Configuration 一节）：

   ```bash
   cp .env.example .env   # 填入 LLM_API_KEY
   # 或用交互式向导：uv run python src/configure_llm.py
   ```

2. 用 entry pipeline 跑本目录（`--entry-func` 从入口函数出发做推理，
   `--all-bugs` 汇总全部候选违规）：

   ```bash
   uv run python main.py docs/examples/invariants-demo \
     --entry-func stream_processor-py::run_stream_processor --all-bugs
   ```

   spec 生成阶段的 prompt（`md/system_prompt.md`、`md/workflow_spec_step4_batch.md`）
   在本分支已支持为连续/不终止行为生成 `invariants` 字段；生成出的
   `.spec.json` 若包含该字段，reasoner 即会执行逐块不变式检查。

3. 查看产物（位于 `docs/examples/invariants-demo/fm_agent/` 下）：
   - `logic_verification_results/`：每个函数的验证结果 JSON
     （all-bugs 模式下含 `kind=invariant` 的结构化违规）；
   - `report.html`：静态报告页，浏览器打开截图即可进 PPT。
   - 也可用 `uv run python dashboard.py docs/examples/invariants-demo` 实时观察运行。
