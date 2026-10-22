# -*- coding: utf-8 -*-
"""v2 离线自检：不调用任何 API，用假响应验证三段逻辑是否都通。

为什么需要它：v2 的核心不是「模型写得好」，而是**模型编造时能被代码拦住**。
这条护栏必须在没有 API Key 的情况下也能被验证，否则就是一个没测过的承诺。

跑法：  python sk/selftest.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import core      # noqa: E402
import llm       # noqa: E402
import v2        # noqa: E402

FIXTURE_RESUME = """
求职意向：AI 产品经理
• 独立主导过 AI 工具从需求到上线：为世界 500 强客户交付识别系统，完成需求拆解与方案取舍。
• 需求拆解：把客户那句"帮我识别编号"结构化拆成四步，明确每步输入输出与失败兜底。
• 技能：Python、Word、PowerPoint。
"""

# 半真半假的模型响应：第一条 anchor 真实存在，第二条是编的
FAKE_SUGGEST = {
    "verdict": "测试用",
    "must_add": [
        {"term": "问题拆解", "where": "核心优势", "how": "把需求拆解改成问题拆解",
         "anchor": "需求拆解"},                      # ✅ 简历里真有
        {"term": "投标", "where": "项目经历", "how": "补充投标经历",
         "anchor": "主导过三次国际投标并中标"},        # ❌ 简历里根本没有
    ],
    "do_not_add": [],
    "rewrite_sample": "示例",
}

FAILS = []


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  → " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 70)
    print("v2 离线自检（不需要 API Key）")
    print("=" * 70)

    # ---- 1. 归一化 ----
    print("\n1) 归一化：中文空格 / 中英混排空格")
    check("「需求 评审」去掉空格", "需求评审" in core._norm("需求 评审"))
    check("「B 端」→「b端」", "b端" in core._norm("B 端"))
    check("「AI 工具」→「ai工具」", "ai工具" in core._norm("AI 工具"))

    # ---- 2. 命中判定 ----
    print("\n2) 命中判定：精确 vs 宽松")
    rows = core.match_resume(FIXTURE_RESUME, [("hard_skill", "需求拆解"),
                                              ("hard_skill", "投标")])
    d = {r["term"]: r for r in rows}
    check("「需求拆解」精确命中", d["需求拆解"]["hit"])
    check("「投标」精确未命中", not d["投标"]["hit"])
    check("「投标」也没有相关痕迹（判为真缺）", not d["投标"]["hit_lenient"])

    # ---- 3. 护栏：拦截编造的锚点 ----
    print("\n3) 护栏：anchor 必须在简历原文里能找到")
    fixed, dropped = verify = v2.verify_anchors(FAKE_SUGGEST, FIXTURE_RESUME)
    kept = [x["term"] for x in fixed["must_add"]]
    dont = [x["term"] for x in fixed["do_not_add"]]
    check("真实锚点的建议被保留", "问题拆解" in kept, "kept=%s" % kept)
    check("编造锚点的建议被拦截", "投标" not in kept and "投标" in dont, "dropped=%s" % dont)
    check("拦截条数正确", len(dropped) == 1, "dropped=%d" % len(dropped))

    # ---- 4. 无 Key 时回退到规则库 ----
    print("\n4) 无 API Key 时自动回退规则库")
    saved = {k: os.environ.get(k) for k in
             ("LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")}
    for k in saved:
        os.environ[k] = ""
    # 排除 sk/apikey.txt 里已经填了真 key 的干扰，否则这一节测不出回退逻辑
    saved_keyfile = llm.KEY_FILE
    llm.KEY_FILE = os.path.join(HERE, "_no_such_apikey.txt")
    try:
        check("has_key() 为 False", not llm.has_key())
        kws, meta = v2.extract_keywords("需要熟悉 Python 与需求拆解，负责技术培训",
                                        use_llm=True)
        check("回退来源标记为 rules", meta["source"] == "rules", str(meta.get("reason", "")))
        check("规则库仍能抽出关键词", len(kws) >= 2, "count=%d" % len(kws))
        sugg, smeta = v2.suggest({"rows": []}, FIXTURE_RESUME, "JD", use_llm=True)
        check("无 Key 时 suggest 返回 None", sugg is None)
    finally:
        llm.KEY_FILE = saved_keyfile
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ---- 5. 报告渲染不报错 ----
    print("\n5) 报告渲染（含 v2 建议段）")
    try:
        import main as M
        res = core.analyze("需要熟悉 Python 与需求拆解", FIXTURE_RESUME, jd_name="t")
        md = M.render(res, "fixture.txt", FAKE_SUGGEST, {"source": "llm", "dropped": 1})
        check("渲染成功且包含护栏提示", "护栏拦截" in md, "%d 字符" % len(md))
    except Exception as e:
        check("渲染成功", False, "%s: %s" % (type(e).__name__, e))

    print("\n" + "=" * 70)
    if FAILS:
        print("结果：%d 项失败 → %s" % (len(FAILS), "、".join(FAILS)))
        raise SystemExit(1)
    print("结果：全部通过")


if __name__ == "__main__":
    main()
