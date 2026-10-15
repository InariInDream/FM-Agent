#!/usr/bin/env python3
"""并发漏洞检出基准：6 个已知并发 bug 案例，判断由大模型实时完成（无需 API key）。

==============================================================================
说明 / NOTE
  与 concurrency-demo/run_demo_live.py 同一套 live/ 文件交换机制：脚本跑到
  每个需要模型判断的环节时写入 live/request.json 并等待 live/response.json，
  响应由外部大模型实时给出；切块、逐块检查、违规汇总走的是
  src/reasoner.py 的真实管线代码。
==============================================================================

六个案例（每个都是"多线程共享状态"的真实 bug 模式）：
  1. abba_locks         两条路径锁顺序相反（ABBA 死锁）
  2. check_then_act     去重集合"检查再加入"未持锁（竞态重复处理）
  3. lost_update        共享计数器自增未持锁（丢失更新）
  4. publication_order  先置就绪标志再写数据（发布顺序错误）
  5. condvar_wait       条件变量用 if 不用 while（虚假唤醒后 pop 空队列）
  6. blocking_wait      回调内原地等待 future（单线程执行器死锁）

每个案例跑三个场景：
  A: buggy 版 + 去掉 concurrency 的旧式 spec（all_bugs=False）→ 预期漏报
  B: buggy 版 + 完整 spec（all_bugs=True）→ 预期 MISMATCH，kind=concurrency
  C: fixed 版 + 完整 spec（all_bugs=True）→ 预期 MATCH

运行方式：
  uv run python docs/examples/concurrency-benchmark/run_benchmark_live.py
  # 只跑部分案例：
  uv run python docs/examples/concurrency-benchmark/run_benchmark_live.py abba_locks condvar_wait
  然后由外部的模型侧进程逐个应答 live/ 目录下的 request.json。
"""

import json
import os
import sys
import time
import unicodedata

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

from src import reasoner as reasoner_mod  # noqa: E402
from src.parser import format_spec_for_reasoner  # noqa: E402

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_DIR = os.path.join(DEMO_DIR, "live")
REQUEST_PATH = os.path.join(LIVE_DIR, "request.json")
RESPONSE_PATH = os.path.join(LIVE_DIR, "response.json")

reasoner_mod.GRANULARITY = 10

_call_id = 0


def ask_model(kind, payload):
    """把一次模型调用写到 live/request.json，等待 live/response.json。

    kind: "post_condition" | "post_implies_spec" | "property_check"
    响应格式：
      post_condition:     {"post_condition": "..."}
      post_implies_spec:  {"passed": true/false,
                           "statements": "..."|null, "reason": "..."|null}
      property_check:     {"passed": true/false,
                           "statements": "..."|null, "reason": "..."|null}
    """
    global _call_id
    _call_id += 1
    call_id = _call_id
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(REQUEST_PATH, "w", encoding="utf-8") as f:
        json.dump({"call_id": call_id, "kind": kind, **payload}, f,
                  ensure_ascii=False, indent=2)
    print(f"    >>> 等待模型应答（call {call_id}, {kind}）...", flush=True)
    while True:
        if os.path.exists(RESPONSE_PATH):
            try:
                with open(RESPONSE_PATH, "r", encoding="utf-8") as f:
                    resp = json.load(f)
            except json.JSONDecodeError:
                time.sleep(0.3)
                continue
            if resp.get("call_id") == call_id:
                os.remove(REQUEST_PATH)
                os.remove(RESPONSE_PATH)
                return resp
        time.sleep(0.3)


def _knowledge_text(info):
    return str(info) if info else ""


def live_generate_block_post_condition(block, pre, info, language,
                                       trace_dir=None, trace_meta=None):
    idx = trace_meta["block_index"] if trace_meta else 0
    print(f"    [块 {idx + 1}] 请求模型生成块后条件", flush=True)
    resp = ask_model("post_condition", {
        "language": language,
        "pre_condition": pre,
        "block": block,
        "task": "给定该代码段及其执行前的条件，生成该段执行完之后的条件"
                "（覆盖所有执行路径）。",
    })
    post = resp["post_condition"]
    print(f"    [块 {idx + 1}] 模型给出的后条件: {post}")
    return post


def live_check_post_implies_spec(block, post_condition, spec_post_condition,
                                 info, language, trace_dir=None, trace_meta=None):
    idx = trace_meta["block_index"] if trace_meta else 0
    print(f"    [块 {idx + 1}] 请求模型做后条件对照", flush=True)
    resp = ask_model("post_implies_spec", {
        "language": language,
        "block": block,
        "actual_post_condition": post_condition,
        "spec_post_condition": spec_post_condition,
        "task": "判断代码的实际行为是否满足 spec 要求的后条件；若不满足，"
                "给出触发语句（保留 Line N: 前缀）和原因。",
    })
    passed = bool(resp["passed"])
    print(f"    [块 {idx + 1}] 模型判定: {'MATCH' if passed else 'MISMATCH'}")
    stmts = resp.get("statements")
    if isinstance(stmts, list):
        stmts = "\n".join(str(item) for item in stmts)
    reason = resp.get("reason")
    if isinstance(reason, list):
        reason = "\n".join(str(item) for item in reason)
    return passed, stmts, post_condition, reason


_PROPERTY_TASKS = {
    "invariants": "假设进入该段时不变式成立，判断该段自身的执行是否会在某个"
                  "中间时刻破坏不变式（不只退出点）；若可能，给出触发语句"
                  "（保留 Line N: 前缀）和具体反例。",
    "resources": "判断该段自身的执行是否可能违反资源约定（获取未配对释放、"
                 "或容器跨迭代无界累积）；若可能，给出触发语句"
                 "（保留 Line N: 前缀）和具体反例。",
    "ordering": "判断该段自身的执行是否可能违反操作顺序约定；若可能，"
                "给出触发语句（保留 Line N: 前缀）和具体反例。",
    "concurrency": "假设有其他线程正用同一组共享状态并发执行本函数，判断该段"
                   "代码自身的执行是否存在某个线程交错，使得并发约定被违反"
                   "（check-then-act 中途未持锁、共享变量读写未持约定的锁等）；"
                   "若存在，给出触发语句（保留 Line N: 前缀）和一个具体的双线程"
                   "交错反例（线程 1 执行到哪、线程 2 执行到哪、结果是什么）。",
}


def live_check_block_property(block, pre_condition, property_kind, contract_text,
                              info, language, trace_dir=None, trace_meta=None):
    idx = trace_meta["block_index"] if trace_meta else 0
    print(f"    [块 {idx + 1}] 请求模型做{property_kind}检查", flush=True)
    resp = ask_model("property_check", {
        "language": language,
        "property_kind": property_kind,
        "pre_condition": pre_condition,
        "block": block,
        "contract": contract_text,
        "task": _PROPERTY_TASKS[property_kind],
    })
    passed = bool(resp["passed"])
    stmts = resp.get("statements")
    if isinstance(stmts, list):
        stmts = "\n".join(str(item) for item in stmts)
    reason = resp.get("reason")
    if isinstance(reason, list):
        reason = "\n".join(str(item) for item in reason)
    print(f"    [块 {idx + 1}] 模型判定: {'通过 MATCH' if passed else '违反 MISMATCH'}")
    return passed, stmts, reason


reasoner_mod._generate_block_post_condition = live_generate_block_post_condition
reasoner_mod._check_post_implies_spec = live_check_post_implies_spec
reasoner_mod._check_block_property = live_check_block_property


CASES = [
    {
        "name": "abba_locks",
        "buggy": "abba_locks.py",
        "fixed": "abba_locks_fixed.py",
        "spec": "abba_locks.spec.json",
        "bug_note": "正向路径先 A 后 B、反向路径先 B 后 A，两条路径锁顺序相反，"
                    "并发下形成 ABBA 死锁",
    },
    {
        "name": "check_then_act",
        "buggy": "check_then_act.py",
        "fixed": "check_then_act_fixed.py",
        "spec": "check_then_act.spec.json",
        "bug_note": "pending 的\"检查是否存在再加入\"之间没有持锁，两个线程同时"
                    "通过检查，同一任务被重复登记处理",
    },
    {
        "name": "lost_update",
        "buggy": "lost_update.py",
        "fixed": "lost_update_fixed.py",
        "spec": "lost_update.spec.json",
        "bug_note": "stats[\"count\"] += 1 自增未持锁，读-改-写交错导致丢失更新",
    },
    {
        "name": "publication_order",
        "buggy": "publication_order.py",
        "fixed": "publication_order_fixed.py",
        "spec": "publication_order.spec.json",
        "bug_note": "先 ready_flag.set() 再写 config，读者线程看到标志时数据"
                    "还没写好",
    },
    {
        "name": "condvar_wait",
        "buggy": "condvar_wait.py",
        "fixed": "condvar_wait_fixed.py",
        "spec": "condvar_wait.spec.json",
        "bug_note": "cond.wait() 用 if 不用 while，虚假唤醒后直接 pop 空队列",
    },
    {
        "name": "blocking_wait",
        "buggy": "blocking_wait.py",
        "fixed": "blocking_wait_fixed.py",
        "spec": "blocking_wait.spec.json",
        "bug_note": "在唯一的执行器线程上原地等 future，而 future 的完成回调"
                    "也需要这个线程调度，死锁",
    },
]


def load_numbered_function(filename):
    with open(os.path.join(DEMO_DIR, filename), "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().split("\n") if ln.strip()]
    return "\n".join(f"Line {i + 1}: {ln}" for i, ln in enumerate(lines))


def load_json(filename):
    with open(os.path.join(DEMO_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def print_block_layout(func):
    blocks = reasoner_mod._split_into_blocks_braced(func, "python")
    print(f"  切块结果（GRANULARITY={reasoner_mod.GRANULARITY}）：共 {len(blocks)} 块")
    for i, block in enumerate(blocks):
        block_lines = block.split("\n")
        first = block_lines[0].split(":", 1)[0]
        last = block_lines[-1].split(":", 1)[0]
        print(f"    块 {i + 1}: {first} ~ {last}（{len(block_lines)} 行）")


def _as_text(value, fallback):
    """模型应答里的 statements/reason 可能是字符串或数组，统一成文本。"""
    if value is None:
        return fallback
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def print_result(result, all_bugs):
    if all_bugs:
        print(f"  最终状态: {result['status']}")
        if result["violations"]:
            print(f"  违规汇总（all_bugs 模式，共 {len(result['violations'])} 处）:")
            for v in result["violations"]:
                print(f"    - kind = {v['kind']}")
                stmts = _as_text(v.get("statements"), "(模型未给出具体语句)")
                reason = _as_text(v.get("reason"), "(模型未给出原因)")
                print(f"      触发语句:\n        " + stmts.replace("\n", "\n        "))
                print(f"      原因: {reason}")
    else:
        print(f"  返回值（非 all_bugs 模式的字符串结果）:\n    {result}")


def run_scenario(tag, title, case, func_file, with_concurrency, all_bugs, note):
    print("=" * 76)
    print(f"场景 {tag}: {title}")
    print("=" * 76)
    print(f"  说明: {note}")
    func = load_numbered_function(func_file)
    spec = load_json(case["spec"])
    if not with_concurrency:
        spec = dict(spec)
        spec.pop("concurrency", None)
    spec_text = format_spec_for_reasoner(spec)
    knowledge = None
    print(f"  目标函数: {func_file}（{len(func.splitlines())} 行）")
    has_conc = "Concurrency-contracts:" in spec_text
    print(f"  spec 含 Concurrency-contracts 段: {'是' if has_conc else '否'}")
    print_block_layout(func)
    print("  --- 逐段检查过程（真实管线，模型实时应答） ---", flush=True)
    result = reasoner_mod.reasoner(func, spec_text, knowledge, "python",
                                   all_bugs=all_bugs)
    print("  --- 结果 ---")
    print_result(result, all_bugs)
    print()
    return result


def _disp_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in text)


def _pad(text, width):
    return text + " " * max(1, width - _disp_width(text))


def print_summary(rows):
    print("=" * 16 + " 汇总 " + "=" * 16)
    header = (_pad("案例", 20) + _pad("无 concurrency", 18)
              + _pad("有 concurrency（buggy）", 26) + "修复版")
    print(header)
    for row in rows:
        print(_pad(row["name"], 20) + _pad(row["without"], 18)
              + _pad(row["with_buggy"], 26) + row["fixed"])
    print()
    total = len(rows)
    det_without = sum(1 for r in rows if r["without"] != "漏报（通过）")
    det_with = sum(1 for r in rows if r["with_buggy"] == "MISMATCH")
    fixed_ok = sum(1 for r in rows if r["fixed"] == "MATCH")
    print(f"检出统计：{total} 个已知并发漏洞，无 concurrency 字段时检出 "
          f"{det_without} 个，有 concurrency 字段时检出 {det_with} 个；"
          f"{total} 个修复版通过 {fixed_ok} 个。")


def main():
    selected = sys.argv[1:]
    cases = [c for c in CASES if not selected or c["name"] in selected]
    if not cases:
        print(f"没有匹配的案例。可用案例: {[c['name'] for c in CASES]}")
        sys.exit(1)

    print("*" * 76)
    print("  并发漏洞检出基准：6 个已知并发 bug 案例 × 三个场景")
    print("  —— spec 第四个可选字段 concurrency 的检出能力对照")
    print("  模型判断由外部大模型实时给出（经 live/ 文件交换，无需 API key）。")
    print("*" * 76)
    print(flush=True)

    rows = []
    for case in cases:
        name = case["name"]
        print("#" * 76)
        print(f"# 案例: {name} —— {case['bug_note']}")
        print("#" * 76)
        print()

        result_a = run_scenario(
            f"A（{name}）", "buggy 版 + 旧式 spec（不含 concurrency）",
            case, case["buggy"], with_concurrency=False, all_bugs=False,
            note="旧式 spec 只有 signature/pre/post 三个基础字段，"
                 "并发约定传不到检查里，并发 bug 预期不可见。",
        )
        result_b = run_scenario(
            f"B（{name}）", "buggy 版 + 完整 spec（含 concurrency，all_bugs=True）",
            case, case["buggy"], with_concurrency=True, all_bugs=True,
            note="完整 spec 携带 concurrency 约定，逐块并发检查应发现违规，"
                 f"违规 kind=concurrency。bug: {case['bug_note']}。",
        )
        result_c = run_scenario(
            f"C（{name}）", "fixed 版 + 同一份完整 spec（all_bugs=True）",
            case, case["fixed"], with_concurrency=True, all_bugs=True,
            note="修复版消除并发违规，逐块并发检查应全部通过。",
        )

        passed_a = (isinstance(result_a, str)
                    and result_a.startswith("The function passes"))
        rows.append({
            "name": name,
            "without": "漏报（通过）" if passed_a else "检出（FAILED）",
            "with_buggy": (result_b.get("status") if isinstance(result_b, dict)
                           else "ERROR"),
            "fixed": (result_c.get("status") if isinstance(result_c, dict)
                      else "ERROR"),
        })

    print_summary(rows)
    print("基准运行完成。", flush=True)


if __name__ == "__main__":
    main()
