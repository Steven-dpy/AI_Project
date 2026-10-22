# -*- coding: utf-8 -*-
"""诊断：打印某个 JD 抽出的关键词，用于排查词库与匹配问题。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import core  # noqa: E402

if len(sys.argv) < 2:
    raise SystemExit("用法: python sk/diag.py <jd文件> [简历文件]")

jd_text = core.read_text(sys.argv[1])
kws = core.find_jd_keywords(jd_text)
print("JD: %s" % os.path.basename(sys.argv[1]))
print("抽出关键词 %d 个：" % len(kws))
for layer, term in kws:
    print("  [%-10s] %s" % (layer, term))

if len(sys.argv) >= 3:
    resume = core.read_text(sys.argv[2])
    rows = core.match_resume(resume, kws)
    hit = [x for x in rows if x["hit"]]
    print("\n命中 %d / %d" % (len(hit), len(rows)))
    print("命中：" + "、".join(x["term"] for x in hit))
    miss = [x for x in rows if not x["hit"]]
    print("未命中：" + "、".join(x["term"] for x in miss))
