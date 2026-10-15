# 多线程并发约定（concurrency）before/after 演示包

面向组会投屏的演示：展示 `feature/concurrency-contracts` 分支的改动——spec
新增第四个可选字段 `concurrency`（多线程并发约定），reasoner 逐块检查函数在
多线程交错下是否违反该约定，违规结果带类别 `kind=concurrency`、触发语句和
双线程交错反例，一路保留到结果 JSON 和 report。

> **说明 / NOTE**
> `run_demo_live.py` 跑到每个需要模型判断的环节（生成块后条件、后条件对照 spec、
> 逐块约定检查）时，会把代码段和问题写入 `live/request.json` 并等待
> `live/response.json`——判断由外部大模型实时给出，切块、逐块检查、违规汇总
> 走的是 `src/reasoner.py` 的真实管线代码，spec 文本经
> `src/parser.py` 的 `format_spec_for_reasoner` 真实构建，**无需 API key**。

## 演示目标

`run_dispatcher(queue, pending, stats, lock)`：不终止的任务分发循环
（`while True`），会被多个线程用同一组 pending/stats/lock 并发调用。
它的 spec 声明了 concurrency 约定：

- 对 `pending` 的"检查是否存在再加入"序列必须在同一次持锁
  （`with lock`）内完成，中途不得释放；
- `stats` 的所有读写必须持有 `lock`。

- **buggy 版**（`task_dispatcher.py`）：
  1. check-then-act：`if task["id"] not in pending` 与 `pending.add(...)`
     之间没有持锁，两个线程同时通过检查，同一任务被处理两次；
  2. `stats["done"] += 1` 自增未持锁，并发下丢失更新（读-改-写交错）。
- **fixed 版**（`task_dispatcher_fixed.py`）：检查+加入整段放进同一次
  `with lock:`；`stats["done"] += 1` 也持锁。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `task_dispatcher.py` | 演示目标（buggy 版） |
| `task_dispatcher_fixed.py` | 对照修复版（持锁保护两处共享状态操作） |
| `dispatcher.spec.json` | run_dispatcher 的 spec，含 `concurrency` 字段 |
| `run_demo_live.py` | 演示脚本（判断由外部大模型实时给出，经 `live/` 目录文件交换，跑真实 reasoner 管线） |
| `demo_output_live.txt` | 一次真实运行的完整输出（可直接截图进 PPT） |

spec 在 signature/pre/post 之外允许携带 `concurrency` 字段（旧式 spec 没有）：

```json
{
  "signature": "run_dispatcher(queue, pending, stats, lock)",
  "pre_condition": "queue、pending、stats、lock 已初始化可用；pending 为空 set；stats[\"done\"] 为 0",
  "post_condition": "正常运行期间不返回（while True 事件循环），无返回路径",
  "concurrency": "本函数会被多个线程以同一组 pending、stats、lock 并发调用。对 pending 的\"检查是否存在再加入\"序列必须在同一次持锁（with lock）内完成，中途不得释放；stats 的所有读写必须持有 lock"
}
```

## 怎么跑

```bash
uv run python docs/examples/concurrency-demo/run_demo_live.py
# 然后由外部的模型侧进程逐个应答 live/ 下的 request.json
```

脚本会把 `GRANULARITY` monkeypatch 成 10，并打印每块的行号边界与逐块检查过程。
场景 A 的"旧式 spec"由脚本加载 `dispatcher.spec.json` 后去掉 `concurrency`
键现场构造，模拟改动前约定字段传不过来的行为。

## 三个场景的预期输出

- **场景 A（before）**：buggy 版 + 不含 `concurrency` 的旧式 spec。
  没有并发约定文本，逐块检查只对照"不返回"的后条件 → 两处并发 bug 不可见，
  验证**通过**。
- **场景 B（after）**：buggy 版 + 完整 spec（`all_bugs=True`）。模型从
  concurrency 约定发现违规 → 最终 `status: MISMATCH`，违规
  `kind=concurrency`。循环体在同一块里，一次并发检查把两处违规点一起报出
  （一条违规记录，触发语句含三行）：
  1. check 行与 `pending.add` 行：线程 1 检查 id 不在 pending、还没 add 时，
     线程 2 也检查同一 id 也不在，两个线程都 process 同一任务，重复处理；
  2. `stats["done"] += 1` 行：两线程同时读到 5、各自写回 6，实际处理了两个
     任务但计数只涨了 1。
- **场景 C（after 对照）**：fixed 版 + 同一份完整 spec → 全部通过，
  `status: MATCH`。

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
   uv run python main.py docs/examples/concurrency-demo \
     --entry-func task_dispatcher-py::run_dispatcher --all-bugs
   ```

   spec 生成阶段的 prompt 已支持在 spec 里生成 `concurrency` 字段；
   生成出的 `.spec.json` 若包含该字段，reasoner 就会做逐块并发约定检查。

3. 查看产物（位于 `docs/examples/concurrency-demo/fm_agent/` 下）：
   - `logic_verification_results/`：每个函数的验证结果 JSON
     （all-bugs 模式下违规带 `kind` 字段，property 违规的证据完整保留）；
   - `report.html`：静态报告页，违规详情会显示类别
     （如 `Violation type: concurrency`），浏览器打开截图即可进 PPT。
