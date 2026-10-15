# 并发漏洞检出基准（concurrency benchmark）

`feature/concurrency-contracts` 分支的检出能力基准：6 个已知并发 bug 案例，
每个案例跑 buggy 版（旧式 spec / 完整 spec）和 fixed 版三个场景，验证 spec
的第四个可选字段 `concurrency`（多线程并发约定）能把 6 类真实并发 bug 全部
报成 `kind=concurrency` 的 MISMATCH，且修复版全部 MATCH。

> **说明 / NOTE**
> 与 `concurrency-demo/run_demo_live.py` 同一套机制：`run_benchmark_live.py`
> 跑到每个需要模型判断的环节时写入 `live/request.json` 并等待
> `live/response.json`——判断由外部大模型实时给出，切块、逐块检查、违规汇总
> 走的是 `src/reasoner.py` 的真实管线代码，spec 文本经 `src/parser.py` 的
> `format_spec_for_reasoner` 真实构建，**无需 API key**。

## 演示目标

每个案例一个"多线程共享状态"的真实 bug 模式，buggy 文件里用 `# BUG:` 注释
标出位置，fixed 文件里用 `# 修复:` 注释。spec 统一四字段：
`signature` / `pre_condition` / `post_condition` / `concurrency`。

## 六个案例

| 案例 | bug 模式 | buggy 关键点 | 修复 |
| --- | --- | --- | --- |
| `abba_locks` | ABBA 死锁 | 正向路径先 lock_a 后 lock_b，反向路径相反 | 两条路径统一先 A 后 B |
| `check_then_act` | 去重集合竞态 | `if id not in pending` 与 `pending.add` 之间未持锁 | 检查+加入放进同一次 `with lock` |
| `lost_update` | 丢失更新 | `stats["count"] += 1` 未持锁，读-改-写交错 | 自增放进 `with lock` |
| `publication_order` | 发布顺序错误 | 先 `ready_flag.set()` 再写 config，读者看到标志时数据没写好 | 先写完 config 再置标志 |
| `condvar_wait` | 条件变量误用 | `if not queue: cond.wait()`，虚假唤醒后直接 pop 空队列 | `if` 改 `while` 循环复查 |
| `blocking_wait` | 回调内原地等待（ROS 2 单线程执行器死锁） | 回调里 `while not future.done(): sleep(...)`，完成回调也要这同一个线程 | 改 `future.add_done_callback(...)`，不占用当前线程 |

每个案例三个文件：`案例名.py`（buggy）、`案例名_fixed.py`、`案例名.spec.json`。

## 怎么跑

```bash
uv run python docs/examples/concurrency-benchmark/run_benchmark_live.py
# 只跑部分案例（调试用）：
uv run python docs/examples/concurrency-benchmark/run_benchmark_live.py abba_locks condvar_wait
# 然后由外部的模型侧进程逐个应答 live/ 下的 request.json
```

脚本把 `GRANULARITY` monkeypatch 成 10（这些案例 10~13 行，切成 1 块）。
每个案例依次跑三个场景：

- **场景 A**：buggy 版 + 脚本现场去掉 `concurrency` 键的旧式 spec
  （`all_bugs=False`）。并发约定传不到检查里 → 预期漏报，验证通过。
- **场景 B**：buggy 版 + 完整 spec（`all_bugs=True`）→ 预期 MISMATCH，
  违规 `kind=concurrency`，触发语句定位到 bug 行，原因带双线程交错反例。
- **场景 C**：fixed 版 + 同一份完整 spec（`all_bugs=True`）→ 预期 MATCH。

## 预期输出

实跑结果（`benchmark_output_live.txt`，共 48 次模型应答）与预期完全一致：

```
================ 汇总 ================
案例                无 concurrency    有 concurrency（buggy）   修复版
abba_locks          漏报（通过）      MISMATCH                  MATCH
check_then_act      漏报（通过）      MISMATCH                  MATCH
lost_update         漏报（通过）      MISMATCH                  MATCH
publication_order   漏报（通过）      MISMATCH                  MATCH
condvar_wait        漏报（通过）      MISMATCH                  MATCH
blocking_wait       漏报（通过）      MISMATCH                  MATCH

检出统计：6 个已知并发漏洞，无 concurrency 字段时检出 0 个，有 concurrency 字段时检出 6 个；6 个修复版通过 6 个。
基准运行完成。
```

两个容易误判的点，实跑中都处理对了：

- `abba_locks`、`publication_order` 的 post_condition 是功能描述，buggy 版的
  功能逻辑本身是对的，后条件对照判 MATCH，违规只来自 concurrency 检查；
- "不返回"类的 post（check_then_act / lost_update / condvar_wait）对
  `while True` 循环都判通过，违规同样只来自 concurrency 检查。

## 真实端到端验证指南（有 LLM key 的机器）

1. 配置 key（参考根 README 的 Configuration 一节）：

   ```bash
   cp .env.example .env   # 填入 LLM_API_KEY
   # 或用交互式向导：uv run python src/configure_llm.py
   ```

2. 用 entry pipeline 跑单个案例目录，例如 abba_locks：

   ```bash
   uv run python main.py docs/examples/concurrency-benchmark \
     --entry-func abba_locks-py::transfer --all-bugs
   ```

   spec 生成阶段的 prompt 已支持在 spec 里生成 `concurrency` 字段；
   生成出的 `.spec.json` 若包含该字段，reasoner 就会做逐块并发约定检查。

3. 查看产物（位于 `docs/examples/concurrency-benchmark/fm_agent/` 下）：
   - `logic_verification_results/`：每个函数的验证结果 JSON
     （all-bugs 模式下违规带 `kind` 字段，property 违规的证据完整保留）；
   - `report.html`：静态报告页，违规详情会显示类别
     （如 `Violation type: concurrency`）。
