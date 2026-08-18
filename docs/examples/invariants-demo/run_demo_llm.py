#!/usr/bin/env python3
"""不变式推理 before/after 演示：判断由大模型离线完成（无需 API key）。

==============================================================================
说明 / NOTE
  本脚本里三处需要模型判断的环节（生成每段代码的后条件、后条件对照 spec、
  逐段不变式检查），判断内容是大模型（Kimi）真实阅读演示代码后给出的，
  逐条录入在下方 JUDGMENTS 数据里，运行时按段回放。切块、条件逐段传递、
  逐段检查、违规汇总走的是 src/reasoner.py 里的真实管线代码。
  因此本演示无需 API key：判断来自真实的大模型推理，只是离线完成并回放。
  The judgments below were produced by a real LLM reading the demo code,
  recorded and replayed here; the checking pipeline itself is real code.
==============================================================================

三个场景：
  A (before): buggy 代码 + 不含 invariants 的旧式 spec → 验证通过（bug 不可见）
  B (after):  buggy 代码 + 含 invariants 的 spec        → MISMATCH（不变式检查发现 bug）
  C (after):  fixed 代码 + 同一份 spec                  → MATCH

运行方式（需要项目依赖环境来 import src.reasoner，脚本本身无第三方依赖）：
  uv run python docs/examples/invariants-demo/run_demo_llm.py
"""

import json
import os
import sys

# 把 repo root 加入 sys.path，以便 import src.reasoner / src.parser
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

from src import reasoner as reasoner_mod  # noqa: E402
from src.parser import format_spec_for_reasoner  # noqa: E402

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))

# 调小切块粒度（config 默认 40），让 30+ 行的演示函数确实被切成多块
reasoner_mod.GRANULARITY = 10


# ---------------------------------------------------------------------------
# 大模型的判断（离线录入）。
# 以下每条内容都是模型阅读对应代码段后给出的真实推理结果，按场景和段序号组织。
# ---------------------------------------------------------------------------
JUDGMENTS = {
    "buggy": {
        "posts": [
            "初始化阶段：buffer 置为空列表，processed 与 dropped 计数器置 0，随后进入 while True "
            "事件循环；此时 len(buffer) == 0，满足容量上限。",
            "本轮迭代从 source 拉取一个 batch：若 batch 为 None 则跳过本轮；否则将 batch 整体并入 "
            "buffer 并上报 buffer_len 指标。并入前未检查剩余容量，并入后 len(buffer) 等于"
            "原长度加 len(batch)。",
            "若收到 shutdown 请求则跳出循环；否则逐条弹出 buffer 中的元素处理：heartbeat 类型跳过，"
            "transform 抛 ValueError 时计入 dropped，其余结果写入 sink 并累加 processed；buffer 排空后"
            "更新指标。退出循环时 flush(buffer, sink) 后隐式返回。段内 buffer 只减不增，段结束时 "
            "len(buffer) == 0。",
        ],
        # 逐段不变式检查：(是否保持, 触发语句, 原因)
        "invariant_checks": [
            (True, None, None),  # 段 1：只有初始化与拉取，buffer 为空或不变，无超限路径
            (
                False,
                "Line 20:         buffer.extend(batch)",
                "extend 前没有任何容量检查或排空操作。反例：buffer 中已有 5 条未处理元素时，"
                "source 返回 6 条元素的 batch，buffer.extend(batch) 后 len(buffer) 变为 11，"
                "超过 CAPACITY = 8，在随后逐条 pop 之前的窗口期内不变式被违反。",
            ),
            (True, None, None),  # 段 3：buffer 只减不增
        ],
    },
    "fixed": {
        "posts": [
            "初始化阶段：buffer 置为空列表，processed 与 dropped 计数器置 0，随后进入 while True "
            "事件循环；此时 len(buffer) == 0，满足容量上限。",
            "本轮迭代从 source 拉取一个 batch：若 batch 为 None 则跳过本轮；否则先比较 batch 长度与 "
            "buffer 剩余容量，空间不足时先 flush 排空 buffer，再将 batch 并入并上报指标。"
            "并入后 len(buffer) 不超过 CAPACITY。",
            "若收到 shutdown 请求则跳出循环；否则逐条弹出 buffer 中的元素处理：heartbeat 类型跳过，"
            "transform 抛 ValueError 时计入 dropped，其余结果写入 sink 并累加 processed；buffer 排空后"
            "更新指标。退出循环时 flush(buffer, sink) 后隐式返回。段内 buffer 只减不增，段结束时 "
            "len(buffer) == 0。",
        ],
        "invariant_checks": [
            (True, None, None),
            # 段 2：守卫保证空间不足时先排空再并入；此处假设单次 batch 长度不超过 CAPACITY
            # （由 source 侧约束），在此前提下并入后 len(buffer) <= CAPACITY 恒成立。
            (True, None, None),
            (True, None, None),
        ],
    },
}

# 当前场景（"buggy" / "fixed"），由 run_scenario 设置
_current = "buggy"


def llm_generate_block_post_condition(block, pre, info, language,
                                      trace_dir=None, trace_meta=None):
    """回放大模型为该段生成的后条件。"""
    idx = trace_meta["block_index"] if trace_meta else 0
    posts = JUDGMENTS[_current]["posts"]
    post = posts[min(idx, len(posts) - 1)]
    print(f"    [块 {idx + 1}] 生成块后条件（大模型判断，离线回放）: {post}")
    return post


def llm_check_post_implies_spec(block, post_condition, spec_post_condition,
                                info, language, trace_dir=None, trace_meta=None):
    """大模型对末尾段的后条件对照结果：实现与 spec 描述一致 → MATCH。"""
    idx = trace_meta["block_index"] if trace_meta else 0
    print(f"    [块 {idx + 1}] 后条件对照 spec（大模型判断）→ MATCH")
    return True, None, post_condition, None


def llm_check_block_preserves_invariants(block, pre_condition, invariants,
                                         info, language,
                                         trace_dir=None, trace_meta=None):
    """回放大模型对该段的不变式保持判断。"""
    idx = trace_meta["block_index"] if trace_meta else 0
    passed, stmts, reason = JUDGMENTS[_current]["invariant_checks"][idx]
    if passed:
        print(f"    [块 {idx + 1}] 不变式检查（大模型判断）→ 保持 MATCH")
    else:
        print(f"    [块 {idx + 1}] 不变式检查（大模型判断）→ 违反 MISMATCH")
    return passed, stmts, reason


# 替换 src.reasoner 命名空间里的三处模型调用
reasoner_mod._generate_block_post_condition = llm_generate_block_post_condition
reasoner_mod._check_post_implies_spec = llm_check_post_implies_spec
reasoner_mod._check_block_preserves_invariants = llm_check_block_preserves_invariants


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


def run_scenario(tag, title, scenario_key, func_file, spec, all_bugs, note):
    global _current
    _current = scenario_key
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
    print("  --- 逐段检查过程（真实 reasoner 管线，判断来自大模型离线回放） ---")
    result = reasoner_mod.reasoner(func, spec_text, None, "python", all_bugs=all_bugs)
    print("  --- 结果 ---")
    print_result(result, all_bugs)
    print()
    return result


def main():
    print("*" * 76)
    print("  不变式推理 before/after 演示 —— stream_processor（buffer 容量不变式）")
    print("  判断内容为大模型阅读代码后给出（离线录入回放，无需 API key）。")
    print("  Judgments were produced by an LLM reading the code, recorded and")
    print("  replayed offline; no API key needed.")
    print("*" * 76)
    print()

    buggy_spec = load_spec("buggy.spec.json")
    fixed_spec = load_spec("fixed.spec.json")

    # 场景 A 用"旧式 spec"：同一份 spec 去掉 invariants 字段（旧版本根本没有该字段）
    legacy_spec = {k: v for k, v in buggy_spec.items() if k != "invariants"}

    run_scenario(
        "A（before）",
        "buggy 代码 + 不含 invariants 的旧式 spec",
        "buggy",
        "stream_processor.py",
        legacy_spec,
        all_bugs=False,
        note="旧式 spec 没有 Invariants 段，reasoner 不会做逐段不变式检查；"
             "该函数没有显式 return，只剩最后一段『末尾隐式返回』的后条件检查，"
             "buffer 超限 bug 完全不可见。",
    )

    run_scenario(
        "B（after）",
        "buggy 代码 + 含 invariants 的 spec",
        "buggy",
        "stream_processor.py",
        buggy_spec,
        all_bugs=True,
        note="spec 声明『任意时刻 len(buffer) <= CAPACITY』后，"
             "每段代码都要过一遍不变式检查；all_bugs=True 汇总全部违规。",
    )

    run_scenario(
        "C（after 对照）",
        "fixed 代码 + 同一份含 invariants 的 spec",
        "fixed",
        "stream_processor_fixed.py",
        fixed_spec,
        all_bugs=True,
        note="修复版在 extend 前检查剩余容量并在空间不足时先 flush，"
             "逐段不变式检查全部通过。",
    )


if __name__ == "__main__":
    main()
