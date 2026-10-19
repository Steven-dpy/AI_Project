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
def render(res, resume_name):
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
    A("> **结论**：" + verdict(sc, res["title_align"]))
    A("")

    A("## 一、两个覆盖率，以及它们之间的差")
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

    A("## 三、缺口怎么处理（这一节才是重点）")
    A("")
    A("### 🟡 只缺词：经历在，只是没用招聘方的说法（**可以补，优先补**）")
    A("")
    word_only = [x for x in rows if not x["hit"] and x["hit_lenient"]]
    if word_only:
        A("| 关键词 | 必需? | 你简历里已有的说法 |")
        A("|---|:---:|---|")
        for x in word_only:
            A("| **%s** | %s | %s |" % (
                x["term"],
                "必需" if x["necessity"] == "must" else "加分",
                "、".join(x["anchors"]) or "—"))
    else:
        A("（无）")
    A("")

    A("### ❌ 真缺：简历里连相关痕迹都没有（**不要硬加**）")
    A("")
    no_exp = [x for x in rows if not x["hit_lenient"]]
    if no_exp:
        A("| 关键词 | 必需? | 为什么不要加 |")
        A("|---|:---:|---|")
        for x in no_exp:
            A("| %s | %s | 无任何相关迹象，硬加会在面试被追问时崩 |" % (
                x["term"], "必需" if x["necessity"] == "must" else "加分"))
    else:
        A("（无）")
    A("")

    A("## 四、最后的提醒")
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
    args = ap.parse_args()

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
    print("=" * 82)
    print("%-32s %8s %8s %8s %8s" % ("JD", "精确", "宽松", "可补", "职位名"))
    print("-" * 82)

    for path in jd_files:
        name = os.path.splitext(os.path.basename(path))[0]
        res = core.analyze(core.read_text(path), resume_text, jd_name=name)
        results.append(res)

        with open(os.path.join(args.out, "%s__%s.md"
                              % (name, os.path.splitext(resume_name)[0])),
                  "w", encoding="utf-8") as f:
            f.write(render(res, resume_name))

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
