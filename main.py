# -*- coding: utf-8 -*-
"""可被搜索性诊断器 · v1（规则版，零第三方依赖）。

核心指标不是「覆盖率」本身，而是两个覆盖率之间的差：
  精确覆盖 = 现在这份简历，招聘方字面能不能搜到它说的东西
  宽松覆盖 = 把「同一段经历的另一种说法」也算上，即补齐措辞后的上限
  差额     = 「只换个说法就能拿到的分」——这才是可执行的部分

用法
----
  python sk/main.py --resume inputs/resume_解决方案版.txt
  python sk/main.py --resume inputs/resume_解决方案版.txt --jd inputs/jd_02_古茗_AI应用管培生.txt
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import core  # noqa: E402
import llm   # noqa: E402
import v2    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BAR = 14
HONESTY_NOTE = (
    "本工具优化的是「被看见」，不是「被录用」。关键词帮你进入候选池，"
    "能否拿到 offer 取决于经历本身。所有建议只在你确实做过的前提下采纳。"
)


def pct(v):
    return "  n/a" if v is None else "%4.0f%%" % v


def bar(v):
    if v is None:
        return " " * BAR
    n = max(0, min(BAR, int(round(v / 100.0 * BAR))))
    return "█" * n + "·" * (BAR - n)


def gap_of(sc):
    s, l = sc["精确"]["必需词"], sc["宽松"]["必需词"]
    if s is None or l is None:
        return None
    return l - s


def verdict(sc, title_align):
    s, l = sc["精确"]["必需词"], sc["宽松"]["必需词"]
    if s is None:
        return "无法判定（这份 JD 在词库里没识别到必需词）"
    if s >= 85:
        core_txt = "现在就能被搜到"
    elif l is not None and l >= 70:
        core_txt = "字面搜不到，但你有经历、只是没用招聘方的说法"
    elif l is not None and l >= 40:
        core_txt = "缺口较大，需要补经历或换更匹配的岗位"
    else:
        core_txt = "匹配度偏低，建议先确认这个岗位值不值得投"
    msg = "精确覆盖 %s，换个说法可达 %s。%s。" % (pct(s).strip(), pct(l).strip(), core_txt)
    if title_align is not None and title_align < 60:
        msg += "另外职位名对齐度只有 %s，这是最该先修、也最好修的一项。" % pct(title_align).strip()
    return msg


def mark(x):
    if x["hit"]:
        return "✅ 命中"
    if x["hit_lenient"]:
        return "🟡 只缺词"
    return "❌ 真缺"


# ---------------------------------------------------------------------------
def render(res, resume_name, sugg=None, meta=None):
    rows, sc = res["rows"], res["scores"]
    strict, lenient = sc["精确"], sc["宽松"]
    L = []
    A = L.append

    A("# 可被搜索性诊断报告")
    A("")
    A("| 项 | 内容 |")
    A("|---|---|")
    A("| 目标 JD | **%s** |" % res["jd_title"])
    A("| 简历 | `%s` |" % resume_name)
    A("| 简历求职意向 | %s |" % (res["resume_title"] or "(未识别)"))
    A("| 职位名对齐度 | %s |" % pct(res["title_align"]).strip())
    A("")
    _v = (sugg or {}).get("verdict") or ""
    A("> **结论**：" + (_v if _v else verdict(sc, res["title_align"])))
    A("")

    A("## 一、两个覆盖率，以及它们之间的差")
    A("")
    if sugg:
        A("> ⚠️ 这两个数是**纯字面口径**。模型抽出的关键词更贴 JD 原话（如「AI 场景探索」），"
          "而你简历写的是「场景探索」——字面确实搜不到，所以这个比例会偏低。")
        A("> **谁该补、谁不能补，以第三、四节的模型判定为准。**")
        A("")
    A("| 分项 | 精确覆盖 | 宽松覆盖 | 差额（可补空间） |")
    A("|---|---:|---:|---:|")
    for k in ("必需词", "职位名", "硬技能", "工具领域", "软性"):
        s, l = strict.get(k), lenient.get(k)
        d = None if (s is None or l is None) else l - s
        A("| %s | `%s` %s | `%s` %s | %s |" % (
            k, bar(s), pct(s), bar(l), pct(l), "—" if d is None else "+%.0f pt" % d))
    A("")
    A("> **精确覆盖**=招聘方字面能不能搜到；**宽松覆盖**=把你的经历换成招聘方的说法之后的上限。")
    A("> **差额就是最容易拿的分**：经历都在，只是措辞对不上。")
    A("")

    must = [x for x in rows if x["necessity"] == "must"]
    A("本份 JD 共抽出 **%d** 个分层关键词，其中必需词 **%d** 个；"
      "字面命中 **%d** 个，加上「只缺词」可达 **%d** 个。"
      % (len(rows), len(must),
         sum(1 for x in must if x["hit"]),
         sum(1 for x in must if x["hit_lenient"])))
    A("")

    A("## 二、招聘方在找什么")
    A("")
    A("| 层 | 关键词 | 必需? | 状态 | 字面出现次数 |")
    A("|---|:---:|:---:|:---:|:---:|")
    for x in rows:
        A("| %s | %s | %s | %s | %d |" % (
            x["layer_cn"], x["term"],
            "必需" if x["necessity"] == "must" else "加分",
            mark(x), x["count"]))
    A("")

    # 第三节的判定依据：v2 用模型 + 锚点复核；v1 用规则库 RELATED
    if sugg:
        wo_map = {x.get("term", ""): x for x in (sugg.get("must_add") or [])}
        ne_set = {x.get("term", "") for x in (sugg.get("do_not_add") or [])}
        word_only = [(x, (wo_map.get(x["term"]) or {}).get("anchor", ""))
                     for x in rows if not x["hit"] and x["term"] in wo_map]
        no_exp = [(x, "模型判定：简历里没有事实支撑")
                  for x in rows if not x["hit"] and x["term"] in ne_set]
        unjudged = [x for x in rows if not x["hit"]
                    and x["term"] not in wo_map and x["term"] not in ne_set]
        sec3 = "## 三、缺口怎么处理（v2 · 模型判定，锚点已逐字复核）"
        wo_hint, ne_hint = "简历里的原文依据（已复核）", "原因"
    else:
        word_only = [(x, "、".join(x["anchors"])) for x in rows
                     if not x["hit"] and x["hit_lenient"]]
        no_exp = [(x, "无任何相关迹象，硬加会在面试被追问时崩")
                  for x in rows if not x["hit_lenient"]]
        unjudged = []
        sec3 = "## 三、缺口怎么处理（v1 · 规则库判定）"
        wo_hint, ne_hint = "你简历里已有的说法", "为什么不要加"

    A(sec3)
    A("")
    A("### 🟡 只缺词：经历在，只是没用招聘方的说法（**可以补，优先补**）")
    A("")
    if word_only:
        A("| 关键词 | 必需? | %s |" % wo_hint)
        A("|---|:---:|---|")
        for x, extra in word_only:
            A("| **%s** | %s | %s |" % (
                x["term"], "必需" if x["necessity"] == "must" else "加分",
                extra or "—"))
    else:
        A("（无）")
    A("")

    A("### ❌ 真缺：简历里没有事实支撑（**不要硬加**）")
    A("")
    if no_exp:
        A("| 关键词 | 必需? | %s |" % ne_hint)
        A("|---|:---:|---|")
        for x, why in no_exp:
            A("| %s | %s | %s |" % (
                x["term"], "必需" if x["necessity"] == "must" else "加分", why))
    else:
        A("（无）")
    A("")

    if unjudged:
        A("### ⚪ 模型未涉及（%d 个，自己判断）" % len(unjudged))
        A("")
        A("、".join(x["term"] for x in unjudged))
        A("")

    if sugg:
        A("## 四、改写建议（v2 · 模型生成，锚点已由代码复核）")
        A("")
        if sugg.get("verdict"):
            A("> " + sugg["verdict"])
            A("")
        adds = sugg.get("must_add") or []
        if adds:
            A("### 可以补（每条都附了简历里的原文依据）")
            A("")
            A("| 补什么 | 加在哪 | 怎么改 | 简历里的依据 |")
            A("|---|---|---|---|")
            for it in adds:
                A("| **%s** | %s | %s | 「%s」 |" % (
                    it.get("term", ""), it.get("where", ""),
                    it.get("how", ""), it.get("anchor", "")))
            A("")
        dont = sugg.get("do_not_add") or []
        if dont:
            A("### 不要补")
            A("")
            A("| 不要补 | 原因 |")
            A("|---|---|")
            for it in dont:
                A("| %s | %s |" % (it.get("term", ""), it.get("why", "")))
            A("")
        if sugg.get("rewrite_sample"):
            A("### 改写示例")
            A("")
            A("> " + sugg["rewrite_sample"])
            A("")

    if meta:
        A("## 附 · 本次运行")
        A("")
        A("| 项 | 值 |")
        A("|---|---|")
        A("| 关键词来源 | %s |" % meta.get("source", "?"))
        if meta.get("job_context"):
            A("| 岗位理解 | %s |" % meta["job_context"])
        if meta.get("notes_cn"):
            A("| 国内平台提示 | %s |" % meta["notes_cn"])
        if meta.get("dropped"):
            A("| 护栏拦截 | %d 条建议因依据在简历原文中找不到，已移入「不要补」 |" % meta["dropped"])
        if meta.get("usage"):
            A("| Token 用量 | %s |" % v2.usage_line(meta["usage"]))
        if meta.get("reason"):
            A("| 说明 | %s |" % meta["reason"])
        A("")

    A("## 最后的提醒")
    A("")
    A("> " + HONESTY_NOTE)
    A("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="可被搜索性诊断器 v1")
    ap.add_argument("--resume", required=True)
    ap.add_argument("--jd")
    ap.add_argument("--jd-dir", default=os.path.join(ROOT, "inputs"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    ap.add_argument("--no-llm", action="store_true",
                    help="强制只用规则库（v1），不调用模型")
    args = ap.parse_args()
    args.llm = (not args.no_llm) and llm.has_key()

    resume_text = core.read_text(args.resume)
    resume_name = os.path.basename(args.resume)

    jd_files = ([args.jd] if args.jd
                else sorted(glob.glob(os.path.join(args.jd_dir, "jd_*.txt"))))
    if not jd_files:
        raise SystemExit("没找到 JD 文件（%s/jd_*.txt）" % args.jd_dir)

    os.makedirs(args.out, exist_ok=True)
    results = []

    print("=" * 82)
    print("简历：%s" % resume_name)
    print("求职意向：%s" % (core.parse_resume_title(resume_text) or "(未识别)"))
    print("模式：%s    %s" % ("v2 · LLM + 规则" if args.llm else "v1 · 纯规则",
                            llm.config_summary()))
    if not args.llm and not args.no_llm:
        print("      （没检测到 API Key，已回退 v1；设置 DEEPSEEK_API_KEY 后自动启用 v2）")
    print("=" * 82)
    print("%-32s %8s %8s %8s %8s" % ("JD", "精确", "宽松", "可补", "职位名"))
    print("-" * 82)

    for path in jd_files:
        name = os.path.splitext(os.path.basename(path))[0]
        jd_text = core.read_text(path)
        kws, kmeta = v2.extract_keywords(jd_text, use_llm=args.llm)
        res = core.analyze(jd_text, resume_text, jd_name=name, keywords=kws)
        results.append(res)

        sugg, smeta = v2.suggest(res, resume_text, jd_text, use_llm=args.llm)
        meta = dict(kmeta)
        meta.update(smeta)

        with open(os.path.join(args.out, "%s__%s.md"
                              % (name, os.path.splitext(resume_name)[0])),
                  "w", encoding="utf-8") as f:
            f.write(render(res, resume_name, sugg, meta))

        sc = res["scores"]
        s, l = sc["精确"]["必需词"], sc["宽松"]["必需词"]
        print("%-32s %8s %8s %8s %8s" % (
            name.replace("jd_", "")[:32],
            pct(s), pct(l),
            "  n/a" if (s is None or l is None) else "%4.0f pt" % (l - s),
            pct(res["title_align"])))

    print("-" * 82)

    lines = ["# 可被搜索性诊断 · 汇总", "",
             "简历：`%s`" % resume_name,
             "求职意向：%s" % (core.parse_resume_title(resume_text) or "(未识别)"), "",
             "| JD | 精确 | 宽松 | 可补空间 | 职位名对齐 |",
             "|---|:---:|:---:|:---:|:---:|"]
    for r in results:
        sc = r["scores"]
        s, l = sc["精确"]["必需词"], sc["宽松"]["必需词"]
        lines.append("| %s | %s | %s | %s | %s |" % (
            r["jd_title"], pct(s).strip(), pct(l).strip(),
            "—" if (s is None or l is None) else "+%.0f pt" % (l - s),
            pct(r["title_align"]).strip()))
    lines += ["", "> " + HONESTY_NOTE, ""]
    with open(os.path.join(args.out, "_汇总.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("报告已写入：%s" % args.out)


if __name__ == "__main__":
    main()
