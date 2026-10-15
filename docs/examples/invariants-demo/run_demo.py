#!/usr/bin/env python3
"""不变式推理 before/after 确定性演示（无需 LLM API key）。

==============================================================================
注意 / NOTE
  本脚本中三次 LLM 调用（_generate_block_post_condition、
  _check_post_implies_spec、_check_block_preserves_invariants）全部由
  确定性桩替代；切块、pre/post 逐块传播、逐块不变式检查、违规汇总走的都是
  src/reasoner.py 里的真实管线代码。演示的是机制链路；判断质量仍取决于真实模型。
  All LLM judgments in this script are replaced by deterministic stubs.
  Block splitting, pre/post propagation, per-block invariant checking and
  violation aggregation run the REAL pipeline code in src/reasoner.py.
  The demo shows the mechanism; judgment quality still depends on the real model.
==============================================================================

三个场景：
  A (before): buggy 代码 + 不含 invariants 的旧式 spec → 验证通过（bug 不可见）
  B (after):  buggy 代码 + 含 invariants 的 spec        → MISMATCH（逐块不变式检查逮到 bug）
  C (after):  fixed 代码 + 同一份 spec                  → MATCH

运行方式（需要项目依赖环境来 import src.reasoner，脚本本身无第三方依赖）：
  uv run python docs/examples/invariants-demo/run_demo.py
  # 或 .venv/bin/python docs/examples/invariants-demo/run_demo.py
"""

import json
import os
import re
import sys

# 把 repo root 加入 sys.path，以便 import src.reasoner / src.parser
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

from src import reasoner as reasoner_mod  # noqa: E402
from src.parser import format_spec_for_reasoner  # noqa: E402

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))

# 调小切块粒度（config 默认 40），让 30+ 行的演示函数确实被切成多块，
# 使"连续行为 / 逐块检查"在输出中肉眼可见。
reasoner_mod.GRANULARITY = 10


# ---------------------------------------------------------------------------
# 桩 1: _generate_block_post_condition —— 按块序号返回预写好的自然语言后条件
# ---------------------------------------------------------------------------
PREWRITTEN_POSTS = [
    "已初始化空 buffer 与计数器并进入事件循环；此刻 len(buffer) == 0，满足容量上限",
    "已拉取一个 batch 并入 buffer，等待逐条处理；若收到 shutdown 则跳出循环",
    "本 batch 已处理完毕（或走到退出路径）；退出前 buffer 已排空并 flush 到 sink",
]


def fake_generate_block_post_condition(block, pre, info, language,
                                       trace_dir=None, trace_meta=None):
    idx = trace_meta["block_index"] if trace_meta else 0
    post = PREWRITTEN_POSTS[min(idx, len(PREWRITTEN_POSTS) - 1)]
    print(f"    [块 {idx + 1}] 生成块后条件（桩）: {post}")
    return post


# ---------------------------------------------------------------------------
# 桩 2: _check_post_implies_spec —— 恒返回通过（4 元组）
# ---------------------------------------------------------------------------
def fake_check_post_implies_spec(block, post_condition, spec_post_condition,
                                 info, language, trace_dir=None, trace_meta=None):
    idx = trace_meta["block_index"] if trace_meta else 0
    print(f"    [块 {idx + 1}] 后条件蕴含检查（桩，终止块/末尾隐式返回）→ 通过 PASS")
    return True, None, post_condition, None


# ---------------------------------------------------------------------------
# 桩 3: _check_block_preserves_invariants —— 确定性的玩具检查器
#   规则：块内代码（去掉 # 注释后）出现 buffer.extend( / buffer.append( ，
#   且同块没有任何容量守卫关键词（CAPACITY / flush）→ 判定违反不变式。
# ---------------------------------------------------------------------------
GROW_RE = re.compile(r"buffer\.(?:extend|append)\(")
GUARD_KEYWORDS = ("CAPACITY", "flush")


def toy_check_block_preserves_invariants(block, pre_condition, invariants,
                                         info, language,
                                         trace_dir=None, trace_meta=None):
    idx = trace_meta["block_index"] if trace_meta else 0
    lines = block.split("\n")
    code_only = [ln.split("#", 1)[0] for ln in lines]  # 去掉行内注释再匹配
    grow_lines = [ln for ln, code in zip(lines, code_only) if GROW_RE.search(code)]
    if not grow_lines:
        print(f"    [块 {idx + 1}] 不变式检查（玩具桩）: 块内无 buffer 增长操作 → 保持 PASS")
        return True, None, None
    joined_code = "\n".join(code_only)
    guards_found = [kw for kw in GUARD_KEYWORDS if kw in joined_code]
    if guards_found:
        print(f"    [块 {idx + 1}] 不变式检查（玩具桩）: 发现容量守卫 "
              f"{'/'.join(guards_found)} → 保持 PASS")
        return True, None, None
    stmts = "\n".join(grow_lines)
    reason = (
        "该块调用 buffer.extend(batch) 前没有任何容量守卫（未检查 CAPACITY，"
        "也未先 flush 排空）：突发 batch 会让 len(buffer) 在并入后瞬时超过 "
        "CAPACITY = 8，违反不变式『任意时刻 len(buffer) <= CAPACITY』。"
    )
    print(f"    [块 {idx + 1}] 不变式检查（玩具桩）: extend 前无容量守卫 → 违反 VIOLATION")
    return False, stmts, reason


# 用桩替换 src.reasoner 命名空间里的三次 LLM 调用（与 tests/test_reasoner.py 同款手法）
def toy_check_block_property(block, pre_condition, property_kind, contract_text,
                             info, language, trace_dir=None, trace_meta=None):
    # 本 demo 的 spec 只声明 invariants，属性检查统一走 _check_block_property。
    assert property_kind == "invariants"
    return toy_check_block_preserves_invariants(
        block, pre_condition, contract_text, info, language,
        trace_dir=trace_dir, trace_meta=trace_meta)


reasoner_mod._generate_block_post_condition = fake_generate_block_post_condition
reasoner_mod._check_post_implies_spec = fake_check_post_implies_spec
reasoner_mod._check_block_property = toy_check_block_property


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def load_numbered_function(filename):
    """读入演示源文件，去掉空行并加 "Line N: " 前缀（与 src/parser.py 的
    parse_input_function 喂给 reasoner 的格式一致）。"""
    with open(os.path.join(DEMO_DIR, filename), "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().split("\n") if ln.strip()]
    return "\n".join(f"Line {i + 1}: {ln}" for i, ln in enumerate(lines))


def load_spec(filename):
    with open(os.path.join(DEMO_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def print_block_layout(func):
    """用真实的 _split_into_blocks_braced 切块并打印每块的行号边界。"""
    blocks = reasoner_mod._split_into_blocks_braced(func, "python")
    print(f"  切块结果（GRANULARITY={reasoner_mod.GRANULARITY}）：共 {len(blocks)} 块")
    for i, block in enumerate(blocks):
        block_lines = block.split("\n")
        first = block_lines[0].split(":", 1)[0]
        last = block_lines[-1].split(":", 1)[0]
        print(f"    块 {i + 1}: {first} ~ {last}（{len(block_lines)} 行）")
    return blocks


def print_result(result, all_bugs):
    if all_bugs:
        print(f"  最终状态: {result['status']}")
        if result["violations"]:
            print(f"  违规汇总（all_bugs 模式，共 {len(result['violations'])} 处）:")
            for v in result["violations"]:
                print(f"    - kind = {v['kind']}")
                print(f"      触发语句:\n        " + v["statements"].replace("\n", "\n        "))
                print(f"      原因: {v['reason']}")
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
    has_inv = "Invariants:" in spec_text
    print(f"  spec 含 Invariants 段: {'是' if has_inv else '否（旧式 spec）'}")
    print_block_layout(func)
    print("  --- 逐块推理序列（真实 reasoner 管线，LLM 判断为桩） ---")
    result = reasoner_mod.reasoner(func, spec_text, None, "python", all_bugs=all_bugs)
    print("  --- 结果 ---")
    print_result(result, all_bugs)
    print()
    return result


def main():
    print("*" * 76)
    print("  不变式推理 before/after 演示 —— stream_processor（buffer 容量不变式）")
    print("  LLM 判断由确定性桩替代，演示的是机制链路；判断质量仍取决于真实模型。")
    print("  LLM judgments are stubbed deterministically; this demos the mechanism,")
    print("  not model quality.")
    print("*" * 76)
    print()

    buggy_spec = load_spec("buggy.spec.json")
    fixed_spec = load_spec("fixed.spec.json")

    # 场景 A 用"旧式 spec"：同一份 spec 去掉 invariants 字段（旧版本根本没有该字段）
    legacy_spec = {k: v for k, v in buggy_spec.items() if k != "invariants"}

    run_scenario(
        "A（before）",
        "buggy 代码 + 不含 invariants 的旧式 spec",
        "stream_processor.py",
        legacy_spec,
        all_bugs=False,
        note="旧式 spec 没有 Invariants 段，reasoner 不会做逐块不变式检查；"
             "该函数没有显式 return，只剩最后一块『末尾隐式返回』的后条件检查，"
             "buffer 超限 bug 完全不可见。",
    )

    run_scenario(
        "B（after）",
        "buggy 代码 + 含 invariants 的 spec",
        "stream_processor.py",
        buggy_spec,
        all_bugs=True,
        note="spec 声明『任意时刻 len(buffer) <= CAPACITY』后，"
             "每个块都要过一遍不变式检查；all_bugs=True 汇总全部违规。",
    )

    run_scenario(
        "C（after 对照）",
        "fixed 代码 + 同一份含 invariants 的 spec",
        "stream_processor_fixed.py",
        fixed_spec,
        all_bugs=True,
        note="修复版在 extend 前检查 CAPACITY 并在空间不足时先 flush，"
             "逐块不变式检查全部通过。",
    )


if __name__ == "__main__":
    main()
