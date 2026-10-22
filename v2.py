# -*- coding: utf-8 -*-
"""v2：在 v1 的确定性匹配之上，加一层 LLM 的「理解」。

分工是刻意的，也是这个项目最该讲清楚的一件事：
  · LLM 负责理解 JD、提候选词、写改写建议
  · 代码负责判定命中、复核锚点、拒绝没有依据的建议
  · 任何 LLM 说法都必须能在原始文本里被代码验证，否则降级
"""
import json

import core
import kwlib
import llm
import prompts

VALID_LAYERS = set(kwlib.LAYERS)


# ---------------------------------------------------------------------------
# 一、从 JD 抽关键词（LLM 优先，失败回退规则库）
# ---------------------------------------------------------------------------
def extract_keywords(jd_text, use_llm=True):
    """返回 (keywords, meta)。

    keywords 形如 [(layer, term), ...]，与 core.match_resume 期望的一致。
    meta 记录来源与模型给出的补充信息。
    """
    if use_llm and llm.has_key():
        try:
            obj = llm.chat_json(prompts.EXTRACT_PROMPT, jd_text)
            kws = []
            for k in (obj.get("keywords") or []):
                term = (k.get("term") or "").strip()
                layer = (k.get("layer") or "").strip()
                if term and layer in VALID_LAYERS:
                    kws.append((layer, term))
            if len(kws) >= 5:
                return core.dedupe_substrings(kws), {
                    "source": "llm",
                    "job_title": (obj.get("job_title") or "").strip(),
                    "job_context": (obj.get("job_context") or "").strip(),
                    "notes_cn": (obj.get("notes_cn") or "").strip(),
                    "count": len(kws),
                }
            fallback_reason = "模型只给出 %d 个有效关键词，已回退规则库" % len(kws)
        except RuntimeError as e:
            fallback_reason = str(e)
    else:
        fallback_reason = "未配置 API Key，使用规则库"

    return core.find_jd_keywords(jd_text), {
        "source": "rules",
        "job_title": "",
        "job_context": "",
        "notes_cn": "",
        "count": None,
        "reason": fallback_reason,
    }


# ---------------------------------------------------------------------------
# 二、把命中结果压成一段给 LLM 看的简报
# ---------------------------------------------------------------------------
def build_hit_brief(res, limit=40):
    lines = []
    for x in res["rows"][:limit]:
        lines.append("- %s｜%s｜%s｜%s" % (
            x["term"],
            x["layer_cn"],
            "必需" if x["necessity"] == "must" else "加分",
            ("已命中×%d" % x["count"]) if x["hit"]
            else ("未命中，但简历里有相关说法：" + "、".join(x["anchors"])
                  if x["hit_lenient"] else "未命中，简历里无相关迹象"),
        ))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 三、生成改写建议 + 锚点复核（护栏）
# ---------------------------------------------------------------------------
def verify_anchors(sugg, resume_text):
    """逐条检查 must_add 的 anchor 是否真的逐字出现在简历里。

    这是整个 v2 的安全阀：模型很擅长编一个"看起来很合理"的原文片段。
    只要 anchor 在简历里找不到，这条建议就降级进 do_not_add。
    """
    norm_resume = core._norm(resume_text)
    keep, dropped = [], []
    for item in (sugg.get("must_add") or []):
        anchor = (item.get("anchor") or "").strip()
        term = (item.get("term") or "").strip()
        if not term:
            continue
        if anchor and core._norm(anchor) in norm_resume:
            keep.append(item)
        else:
            dropped.append({
                "term": term,
                "why": "模型给的依据（anchor）在简历原文中找不到，已拦截——防止编造",
            })
    out = dict(sugg)
    out["must_add"] = keep
    out["do_not_add"] = list(sugg.get("do_not_add") or []) + dropped
    return out, dropped


def suggest(res, resume_text, jd_text, use_llm=True):
    """返回 (sugg, meta)。没有 key 时返回 None，调用方继续用 v1 输出。"""
    if not (use_llm and llm.has_key()):
        return None, {"source": "rules", "reason": "未配置 API Key"}

    user = (
        "【目标 JD 原文】\n" + jd_text.strip()[:6000] +
        "\n\n【候选人简历原文】\n" + resume_text.strip()[:6000] +
        "\n\n【代码算出的关键词命中结果（确定，不要推翻）】\n" + build_hit_brief(res)
    )
    try:
        raw = llm.chat_json(prompts.SUGGEST_PROMPT, user)
    except RuntimeError as e:
        return None, {"source": "rules", "reason": str(e)}

    fixed, dropped = verify_anchors(raw, resume_text)
    return fixed, {
        "source": "llm",
        "dropped": len(dropped),
        "usage": dict(llm.last_usage),
    }


def usage_line(usage):
    if not usage:
        return "—"
    pt = usage.get("prompt_tokens")
    ct = usage.get("completion_tokens")
    if pt is None and ct is None:
        return json.dumps(usage, ensure_ascii=False)
    return "输入 %s tok / 输出 %s tok" % (pt, ct)
