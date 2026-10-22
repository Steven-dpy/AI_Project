# -*- coding: utf-8 -*-
"""A/B 对比两版简历：① 正文差异 ② 每份 JD 的覆盖率差异。

这是「改前 vs 改后」那条数字链的工具化——case study 里最硬的那张表由它产出。

用法
----
  python sk/compare.py --a inputs/resume_old.txt --b inputs/resume_new.txt
"""
import argparse
import difflib
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import core  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def squeeze(t):
    """去掉项目符号与所有空白，只留正文，用于判断"内容是否真变了"。"""
    return re.sub(r"[•·\u2022\s]+", "", t or "")


def show_diff(a, b):
    na, nb = squeeze(a), squeeze(b)
    print("=" * 78)
    print("① 正文差异")
    print("=" * 78)
    if na == nb:
        print("两版正文完全一致（归一化后 %d 字，零差异）" % len(na))
        print("→ 如果这不符合预期，说明你改的文件没保存，或者改了没重新导出。")
        return True
    print("A=%d 字，B=%d 字" % (len(na), len(nb)))
    sm = difflib.SequenceMatcher(None, na, nb)
    n = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        n += 1
        print("  %-8s A: %s" % (tag, (na[i1:i2] or "(空)")[:60]))
        print("  %-8s B: %s" % ("", (nb[j1:j2] or "(空)")[:60]))
    print("→ 共 %d 处改动" % n)
    return False


def main():
    ap = argparse.ArgumentParser(description="A/B 对比两版简历")
    ap.add_argument("--a", required=True, help="改前简历")
    ap.add_argument("--b", required=True, help="改后简历")
    ap.add_argument("--jd-dir", default=os.path.join(ROOT, "inputs"))
    args = ap.parse_args()

    ta, tb = core.read_text(args.a), core.read_text(args.b)
    same = show_diff(ta, tb)

    jd_files = sorted(glob.glob(os.path.join(args.jd_dir, "jd_*.txt")))
    print()
    print("=" * 78)
    print("② 逐份 JD 覆盖率（A 改前 → B 改后）")
    print("=" * 78)
    print("%-28s %13s %10s %15s" % ("JD", "精确覆盖", "变化", "宽松覆盖"))
    print("-" * 78)

    tot_a = tot_b = 0.0
    n = 0
    for path in jd_files:
        jd = core.read_text(path)
        ra = core.analyze(jd, ta, os.path.basename(path))
        rb = core.analyze(jd, tb, os.path.basename(path))
        sa = ra["scores"]["精确"]["必需词"] or 0
        sb = rb["scores"]["精确"]["必需词"] or 0
        la = ra["scores"]["宽松"]["必需词"] or 0
        lb = rb["scores"]["宽松"]["必需词"] or 0
        tot_a += sa
        tot_b += sb
        n += 1
        name = os.path.basename(path).replace("jd_", "")[:28]
        print("%-28s %5.0f%% → %5.0f%% %9s %5.0f%% → %5.0f%%"
              % (name, sa, sb, "%+.0f pt" % (sb - sa), la, lb))
    print("-" * 78)
    if n:
        print("%-28s %5.0f%% → %5.0f%% %9s"
              % ("六份平均", tot_a / n, tot_b / n, "%+.0f pt" % ((tot_b - tot_a) / n)))

    if same:
        print()
        print("⚠️  正文没变，所以覆盖率不会有任何变化。")
        print("   要拿到「改前 / 改后」的数字，得先真的改内容。")

    print()
    print("> 本工具优化的是「被看见」，不是「被录用」。")


if __name__ == "__main__":
    main()
