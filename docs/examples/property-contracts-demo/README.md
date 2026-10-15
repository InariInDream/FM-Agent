# 资源 / 时序约定（resources / ordering）检查 before/after 演示包

面向组会投屏的演示：展示 `feature/property-contracts` 分支为 spec 新增的两个可选
字段 `resources` 与 `ordering`，以及 reasoner 在逐块不变式检查之外，对**资源使用**
（获取必须配对释放、容器不跨迭代无界累积）和**操作时序**（锁获取顺序等先后约束）
的逐块检查能力。

> **说明 / NOTE**
> `run_demo_live.py` 跑到每个需要模型判断的环节（生成块后条件、后条件对照 spec、
> 逐块约定检查）时，会把代码段和问题写入 `live/request.json` 并等待
> `live/response.json`——判断由外部大模型实时给出，切块、逐块检查、违规汇总
> 走的是 `src/reasoner.py` 的真实管线代码，**无需 API key**。

## 演示目标

`task_worker.py`：一个不终止的任务处理循环（`while True`），每轮从队列取任务、
从缓冲区池 `pool` 获取缓冲区，按优先级走两条路径。spec 声明两类约定：

- **resources**：每次迭代 `pool.acquire()` 的缓冲区在该迭代内释放或移交有界
  `cache`；`cache` 条目数任意时刻不超过 `MAX_CACHE = 64`，不跨迭代无界增长。
- **ordering**：任何执行路径上 `lock_a` 必须先于 `lock_b` 获取。

- **buggy 版**：slow 路径先 `lock_b` 后 `lock_a`（与其他线程形成 ABBA 死锁风险）；
  fast 路径把缓冲区移交 `cache`，但 `cache` 从不淘汰旧条目，跨迭代无界增长
  （缓冲区内存随运行时间持续累积）。
- **fixed 版**（`task_worker_fixed.py`）：两条路径统一先 A 后 B；`cache` 写满时
  淘汰最旧条目并释放其缓冲区。

这两个问题都不是"返回值对不对"能表达的：函数不返回，传统 pre/post 条件检查
完全覆盖不到。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `task_worker.py` | 演示目标（buggy 版） |
| `task_worker_fixed.py` | 对照修复版（统一锁顺序、cache 有界淘汰） |
| `worker.spec.json` | spec 字典示例，含新字段 `resources` 与 `ordering` |
| `run_demo_live.py` | 演示脚本（判断由外部大模型实时给出，经 `live/` 目录文件交换，跑真实 reasoner 管线） |
| `demo_output_live.txt` | 一次真实运行的完整输出（可直接截图进 PPT） |

`worker.spec.json` 的格式即管线生成的 sidecar 格式，新字段长这样：

```json
{
  "signature": "run_task_worker(queue, pool, lock_a, lock_b, cache)",
  "pre_condition": "queue、pool、lock_a、lock_b 已初始化可用；……",
  "post_condition": "正常运行期间不返回（while True 事件循环），无返回路径",
  "resources": "每次迭代从 pool.acquire() 获取的缓冲区，在该迭代内要么 ……不跨迭代无界增长",
  "ordering": "任何执行路径上 lock_a 必须先于 lock_b 获取；……"
}
```

## 怎么跑

```bash
uv run python docs/examples/property-contracts-demo/run_demo_live.py
# 然后由外部的模型侧进程逐个应答 live/ 下的 request.json
```

脚本会把 `GRANULARITY` monkeypatch 成 10，让演示函数被真实切成多块，
并打印每块的行号边界与逐块检查过程。

## 三个场景的预期输出

- **场景 A（before）**：buggy 代码 + 不含 `resources`/`ordering` 的旧式 spec。
  reasoner 只做后条件对照，函数又没有显式 `return` → 返回
  `The function passes the verification...`，**两个 bug 不可见**。
- **场景 B（after）**：buggy 代码 + 完整 spec（`all_bugs=True`）。每块都过一遍
  资源检查和时序检查 → 最终 `status: MISMATCH`，两处违规：
  `kind=resource`（`cache[task["id"]] = buf` 无界增长，反例：65 个不同 id 的
  fast 任务即超限）与 `kind=ordering`（slow 路径 `with lock_b:` 先于
  `with lock_a:`，ABBA 死锁风险）。
- **场景 C（after 对照）**：fixed 代码 + 同一份 spec → 全部通过，`status: MATCH`。

完整输出见 `demo_output_live.txt`。

## 真实端到端验证指南（有 LLM key 的机器）

要在真实模型下端到端验证，找一台配好环境的机器：

1. 配置 key（参考根 README 的 Configuration 一节）：

   ```bash
   cp .env.example .env   # 填入 LLM_API_KEY
   # 或用交互式向导：uv run python src/configure_llm.py
   ```

2. 用 entry pipeline 跑本目录：

   ```bash
   uv run python main.py docs/examples/property-contracts-demo \
     --entry-func task_worker-py::run_task_worker --all-bugs
   ```

   生成出的 `.spec.json` 若包含 `resources` / `ordering` 字段，reasoner 即会
   执行对应的逐块约定检查。

3. 查看产物（位于 `docs/examples/property-contracts-demo/fm_agent/` 下）：
   - `logic_verification_results/`：每个函数的验证结果 JSON
     （all-bugs 模式下含 `kind=resource` / `kind=ordering` 的结构化违规）；
   - `report.html`：静态报告页，浏览器打开截图即可进 PPT。
