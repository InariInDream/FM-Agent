#!/usr/bin/env python3
"""资源/时序约定检查 before/after 演示：判断由大模型实时完成（无需 API key）。

==============================================================================
说明 / NOTE
  本脚本跑到每个需要模型判断的环节（生成块后条件、后条件对照 spec、
  逐块约定检查）时，会把代码段和问题写入 live/request.json 并等待
  live/response.json 出现——响应由外部的大模型实时给出。切块、条件逐段
  传递、逐块检查、违规汇总走的是 src/reasoner.py 的真实管线代码。
  All model judgments are produced live by an external LLM process through
  the live/ file exchange; the pipeline itself is real code.
==============================================================================

三个场景：
  A (before): buggy 代码 + 不含 resources/ordering 的旧式 spec → 验证通过（bug 不可见）
  B (after):  buggy 代码 + 含 resources/ordering 的 spec        → MISMATCH（两处违规）
  C (after):  fixed 代码 + 同一份 spec                          → MATCH

运行方式：
  uv run python docs/examples/property-contracts-demo/run_demo_live.py
  然后由外部的模型侧进程逐个应答 live/ 目录下的 request.json。
"""

import json
import os
import sys
import time

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
    return passed, resp.get("statements"), post_condition, resp.get("reason")


_PROPERTY_TASKS = {
    "invariants": "假设进入该段时不变式成立，判断该段自身的执行是否会在某个"
                  "中间时刻破坏不变式（不只退出点）；若可能，给出触发语句"
                  "（保留 Line N: 前缀）和具体反例。",
    "resources": "判断该段自身的执行是否可能违反资源约定（获取未配对释放、"
                 "或容器跨迭代无界累积）；若可能，给出触发语句"
                 "（保留 Line N: 前缀）和具体反例。",
    "ordering": "判断该段自身的执行是否可能违反操作顺序约定；若可能，"
                "给出触发语句（保留 Line N: 前缀）和具体反例。",
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
    reason = resp.get("reason")
    print(f"    [块 {idx + 1}] 模型判定: {'通过 MATCH' if passed else '违反 MISMATCH'}")
    return passed, stmts, reason


reasoner_mod._generate_block_post_condition = live_generate_block_post_condition
reasoner_mod._check_post_implies_spec = live_check_post_implies_spec
reasoner_mod._check_block_property = live_check_block_property


def load_numbered_function(filename):
    with open(os.path.join(DEMO_DIR, filename), "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().split("\n") if ln.strip()]
    return "\n".join(f"Line {i + 1}: {ln}" for i, ln in enumerate(lines))


def load_spec(filename):
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


def print_result(result, all_bugs):
    if all_bugs:
        print(f"  最终状态: {result['status']}")
        if result["violations"]:
            print(f"  违规汇总（all_bugs 模式，共 {len(result['violations'])} 处）:")
            for v in result["violations"]:
                print(f"    - kind = {v['kind']}")
                stmts = v.get("statements") or "(模型未给出具体语句)"
                reason = v.get("reason") or "(模型未给出原因)"
                print(f"      触发语句:\n        " + stmts.replace("\n", "\n        "))
                print(f"      原因: {reason}")
    else:
        print(f"  返回值（非 all_bugs 模式的字符串结果）:\n    {result}")


def run_scenario(tag, title, func_file, spec, all_bugs, note):
    print("=" * 76)
    print(f"场景 {tag}: {title}")
    print("=" * 76)
    print(f"  说明: {note}")
    func = load_numbered_function(func_file)
    spec_text = format_spec_for_reasoner(spec)
    print(f"  目标函数: {func_file}（{len(func.splitlines())} 行）")
    has_res = "Resource-contracts:" in spec_text
    has_ord = "Ordering-constraints:" in spec_text
    print(f"  spec 含 Resource-contracts 段: {'是' if has_res else '否'}，"
          f"含 Ordering-constraints 段: {'是' if has_ord else '否'}")
    print_block_layout(func)
    print("  --- 逐段检查过程（真实管线，模型实时应答） ---", flush=True)
    result = reasoner_mod.reasoner(func, spec_text, None, "python", all_bugs=all_bugs)
    print("  --- 结果 ---")
    print_result(result, all_bugs)
    print()
    return result


def main():
    print("*" * 76)
    print("  资源/时序约定检查 before/after 演示 —— task_worker（cache 有界性 + 锁顺序）")
    print("  模型判断由外部大模型实时给出（经 live/ 文件交换，无需 API key）。")
    print("*" * 76)
    print(flush=True)

    full_spec = load_spec("worker.spec.json")
    legacy_spec = {k: v for k, v in full_spec.items()
                   if k not in ("resources", "ordering")}

    run_scenario(
        "A（before）", "buggy 代码 + 不含 resources/ordering 的旧式 spec",
        "task_worker.py", legacy_spec, all_bugs=False,
        note="旧式 spec 没有资源/时序约定段，reasoner 只做后条件对照；"
             "该函数没有显式 return，锁顺序相反和 cache 无界增长两个 bug "
             "完全不可见。",
    )
    run_scenario(
        "B（after）", "buggy 代码 + 含 resources/ordering 的 spec",
        "task_worker.py", full_spec, all_bugs=True,
        note="spec 声明两类约定后，每段代码都要过一遍资源检查（cache 是否有界、"
             "缓冲区是否有归宿）和时序检查（锁获取顺序）；all_bugs=True "
             "汇总全部违规，预期报出两处。",
    )
    run_scenario(
        "C（after 对照）", "fixed 代码 + 同一份完整 spec",
        "task_worker_fixed.py", full_spec, all_bugs=True,
        note="修复版统一先 lock_a 后 lock_b，cache 写满时淘汰最旧条目并释放"
             "其缓冲区；逐段约定检查应全部通过。",
    )
    print("全部场景完成。", flush=True)


if __name__ == "__main__":
    main()
