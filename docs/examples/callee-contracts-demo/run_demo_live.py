#!/usr/bin/env python3
"""callee 约定跨函数传递 before/after 演示：判断由大模型实时完成（无需 API key）。

==============================================================================
说明 / NOTE
  本脚本跑到每个需要模型判断的环节（生成块后条件、后条件对照 spec、
  逐块约定检查）时，会把代码段和问题写入 live/request.json 并等待
  live/response.json 出现——响应由外部的大模型实时给出。切块、条件逐段
  传递、逐块检查、违规汇总走的是 src/reasoner.py 的真实管线代码；
  callee 信息经 src/parser.py 的 format_info_for_reasoner 真实构建。
  All model judgments are produced live by an external LLM process through
  the live/ file exchange; the pipeline itself is real code.
==============================================================================

三个场景（检查对象都是 caller run_worker，callee 是 lease_buffer）：
  A (before): buggy caller + 旧格式 callee info（不含 resources 字段）
              → 验证通过（callee 的资源约定传不过来，bug 不可见）
  B (after):  buggy caller + 含 resources 的 callee info
              → MISMATCH（资源检查发现 bug，违规类别 resource）
  C (after):  fixed caller + 同一份含 resources 的 callee info → MATCH

运行方式：
  uv run python docs/examples/callee-contracts-demo/run_demo_live.py
  然后由外部的模型侧进程逐个应答 live/ 目录下的 request.json。
"""

import json
import os
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

from src import reasoner as reasoner_mod  # noqa: E402
from src.parser import format_info_for_reasoner, format_spec_for_reasoner  # noqa: E402

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
        "knowledge": _knowledge_text(info),
        "block": block,
        "task": "给定该代码段及其执行前的条件，生成该段执行完之后的条件"
                "（覆盖所有执行路径）。knowledge 是被调函数的 spec，"
                "可用来推断被调函数的行为。",
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
        "knowledge": _knowledge_text(info),
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
                 "（保留 Line N: 前缀）和具体反例。knowledge 是被调函数的 spec："
                 "只有当约定文本和 knowledge 能确定违规行为时才算违反；"
                 "knowledge 里没有的信息不要自行假设。",
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
        "knowledge": _knowledge_text(info),
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


def load_numbered_function(filename):
    with open(os.path.join(DEMO_DIR, filename), "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().split("\n") if ln.strip()]
    return "\n".join(f"Line {i + 1}: {ln}" for i, ln in enumerate(lines))


def load_json(filename):
    with open(os.path.join(DEMO_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def build_callee_info(with_properties):
    """用 callee 的 spec 构造 caller 视角的 .info.json 内容。

    with_properties=False 模拟旧格式：callee 条目只有四个基础字段，
    resources 等约定字段传不过来。
    """
    callee_spec = load_json("lease_buffer.spec.json")
    entry = {
        "name": "lease_buffer",
        "signature": callee_spec["signature"],
        "pre_condition": callee_spec["pre_condition"],
        "post_condition": callee_spec["post_condition"],
    }
    if with_properties:
        for key in ("invariants", "resources", "ordering"):
            if key in callee_spec:
                entry[key] = callee_spec[key]
    return {"callees": [entry]}


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


def run_scenario(tag, title, func_file, info_dict, all_bugs, note):
    print("=" * 76)
    print(f"场景 {tag}: {title}")
    print("=" * 76)
    print(f"  说明: {note}")
    func = load_numbered_function(func_file)
    spec_text = format_spec_for_reasoner(load_json("worker_caller.spec.json"))
    knowledge = format_info_for_reasoner(info_dict)
    print(f"  目标函数: {func_file}（{len(func.splitlines())} 行）")
    has_res = "Resource-contracts:" in spec_text
    print(f"  caller spec 含 Resource-contracts 段: {'是' if has_res else '否'}")
    print(f"  callee info 内容:\n    " + str(knowledge).replace("\n", "\n    "))
    print_block_layout(func)
    print("  --- 逐段检查过程（真实管线，模型实时应答） ---", flush=True)
    result = reasoner_mod.reasoner(func, spec_text, knowledge, "python",
                                   all_bugs=all_bugs)
    print("  --- 结果 ---")
    print_result(result, all_bugs)
    print()
    return result


def main():
    print("*" * 76)
    print("  callee 约定跨函数传递 before/after 演示")
    print("  —— run_worker 调用 lease_buffer，缓冲区用完未归还")
    print("  模型判断由外部大模型实时给出（经 live/ 文件交换，无需 API key）。")
    print("*" * 76)
    print(flush=True)

    legacy_info = build_callee_info(with_properties=False)
    full_info = build_callee_info(with_properties=True)

    run_scenario(
        "A（before）", "buggy caller + 旧格式 callee info（不含 resources）",
        "worker_caller.py", legacy_info, all_bugs=False,
        note="旧格式的 callee 条目只有 name/signature/pre/post 四个字段，"
             "lease_buffer 的资源约定（缓冲区由调用方在同一迭代内释放）"
             "传不到 caller 的检查里；模型无法确定 buf 需要归还，bug 不可见。",
    )
    run_scenario(
        "B（after）", "buggy caller + 含 resources 的 callee info",
        "worker_caller.py", full_info, all_bugs=True,
        note="callee 条目允许携带 resources 后，lease_buffer 的约定随 info "
             "进入 caller 的逐块检查：buf 由 lease_buffer 从 pool 取出、"
             "应由调用方在同一迭代内 release，而代码里没有 release。",
    )
    run_scenario(
        "C（after 对照）", "fixed caller + 同一份含 resources 的 callee info",
        "worker_caller_fixed.py", full_info, all_bugs=True,
        note="修复版每轮迭代用完 buf 后 pool.release(buf) 归还；"
             "逐块资源检查应全部通过。",
    )
    print("全部场景完成。", flush=True)


if __name__ == "__main__":
    main()
