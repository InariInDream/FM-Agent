# callee 约定跨函数传递 before/after 演示包

面向组会投屏的演示：展示 `feature/cross-function-contracts` 分支的两部分改动——

1. `invariants` / `resources` / `ordering` 三类约定字段可以随 `.info.json` 的
   callee 条目传给调用方：reasoner 检查 caller 时能看到被调函数声明的约定
   （比如"返回的缓冲区由调用方释放"）。
2. property 违规的证据链补全：违规结果带类别（invariant/resource/ordering）、
   被违反的约定文本和触发语句，一路保留到结果 JSON 和 report。

> **说明 / NOTE**
> `run_demo_live.py` 跑到每个需要模型判断的环节（生成块后条件、后条件对照 spec、
> 逐块约定检查）时，会把代码段和问题写入 `live/request.json` 并等待
> `live/response.json`——判断由外部大模型实时给出，切块、逐块检查、违规汇总
> 走的是 `src/reasoner.py` 的真实管线代码，callee 信息经
> `src/parser.py` 的 `format_info_for_reasoner` 真实构建，**无需 API key**。

## 演示目标

两个函数：

- **callee** `lease_buffer(pool)`：从缓冲区池取一个缓冲区返回。它的 spec
  声明了 resources 约定：**返回的缓冲区由调用方在同一轮迭代内
  `pool.release()` 释放**。这个约定管的是调用方的行为，只看 lease_buffer
  自己检查不出来。
- **caller** `run_worker(queue, pool)`：不终止的任务处理循环（`while True`），
  每轮迭代调 `lease_buffer` 拿缓冲区用。它自己的 spec 也声明了 resources
  约定：每次迭代从 pool 获取的缓冲区在该迭代内归还。

- **buggy 版**（`worker_caller.py`）：每轮 `buf = lease_buffer(pool)` 用完
  直接进下一轮，从不 `pool.release(buf)`，缓冲区随运行时间持续漏掉，
  pool 最终耗尽。
- **fixed 版**（`worker_caller_fixed.py`）：每轮末尾 `pool.release(buf)` 归还。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `worker_caller.py` | 演示目标 caller（buggy 版） |
| `worker_caller_fixed.py` | 对照修复版（每轮 release） |
| `lease_buffer.py` | callee（从 pool 取缓冲区返回） |
| `worker_caller.spec.json` | caller 的 spec，含 `resources` 字段 |
| `lease_buffer.spec.json` | callee 的 spec，含 `resources` 字段（要求调用方释放） |
| `run_demo_live.py` | 演示脚本（判断由外部大模型实时给出，经 `live/` 目录文件交换，跑真实 reasoner 管线） |
| `demo_output_live.txt` | 一次真实运行的完整输出（可直接截图进 PPT） |

callee 条目现在允许携带三类约定字段（旧格式只有四个基础字段）：

```json
{
  "callees": [
    {
      "name": "lease_buffer",
      "signature": "lease_buffer(pool)",
      "pre_condition": "pool 已初始化且有空闲缓冲区",
      "post_condition": "返回一个可用的缓冲区对象",
      "resources": "返回的缓冲区由调用方负责在同一轮迭代内 pool.release() 释放"
    }
  ]
}
```

## 怎么跑

```bash
uv run python docs/examples/callee-contracts-demo/run_demo_live.py
# 然后由外部的模型侧进程逐个应答 live/ 下的 request.json
```

脚本会把 `GRANULARITY` monkeypatch 成 10，并打印每块的行号边界与逐块检查过程。
场景 A 的"旧格式 info"由脚本用 callee spec 现场构造（只保留四个基础字段），
模拟改动前约定字段传不过来的行为。

## 三个场景的预期输出

- **场景 A（before）**：buggy caller + 不含 `resources` 的旧格式 callee info。
  knowledge 里只有 lease_buffer 的 pre/post，推不出 `buf` 需要归还 pool
  → 逐块资源检查通过，**bug 不可见**。
- **场景 B（after）**：buggy caller + 含 `resources` 的 callee info
  （`all_bugs=True`）。模型从 callee 约定推出 `buf` 必须同迭代释放，而循环体里
  没有 `release` → 最终 `status: MISMATCH`，违规 `kind=resource`，触发语句
  `Line 15: buf = lease_buffer(pool)`（及 `while True:` 行），反例：pool 共 N 个
  缓冲区，连续 N+1 个任务后耗尽。
- **场景 C（after 对照）**：fixed caller + 同一份 callee info → 全部通过，
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
   uv run python main.py docs/examples/callee-contracts-demo \
     --entry-func worker_caller-py::run_worker --all-bugs
   ```

   spec 生成阶段的 prompt（`md/system_prompt.md`、`md/workflow_spec_step4_batch.md`）
   已支持在 info.json 的 callee 条目里生成三类约定字段；生成出的 `.info.json`
   若包含这些字段，reasoner 检查 caller 时就能看到。

3. 查看产物（位于 `docs/examples/callee-contracts-demo/fm_agent/` 下）：
   - `logic_verification_results/`：每个函数的验证结果 JSON
     （all-bugs 模式下违规带 `kind` 字段，property 违规的证据完整保留）；
   - `report.html`：静态报告页，违规详情会显示类别
     （如 `Violation type: resource`），浏览器打开截图即可进 PPT。
