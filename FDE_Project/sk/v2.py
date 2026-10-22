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

    ⚠️ 关键设计决策（踩过坑才定下来的）：
      · **规则库的词负责算分** —— 它们是短词、有 RELATED 锚点、历史数值可对标
      · **模型的词只负责补覆盖** —— 它们是 JD 原话（长短语），贴近真实搜索，
        但字面几乎不可能在简历里原样出现，拿来当分母会把指标打成 0%

    所以这里返回的是「规则库 ∪ 模型独有词」的并集，每项带 src 标记；
    core.score 只对 src=rules 的那部分算覆盖率，保证数字稳定可比。
    """
    rules = [{"layer": l, "term": t, "aliases": [], "src": "rules"}
             for l, t in core.find_jd_keywords(jd_text)]
    rules = core.dedupe_substrings(rules)
    rule_terms = {x["term"] for x in rules}

    meta = {"source": "rules", "job_title": "", "job_context": "",
            "notes_cn": "", "llm_only": 0, "reason": "未配置 API Key，使用规则库"}

    if not (use_llm and llm.has_key()):
        return rules, meta

    try:
        obj = llm.chat_json(prompts.EXTRACT_PROMPT, jd_text)
    except RuntimeError as e:
        meta["reason"] = str(e)
        return rules, meta

    llm_list = []
    for k in (obj.get("keywords") or []):
        term = (k.get("term") or "").strip()
        layer = (k.get("layer") or "").strip()
        if not term or layer not in VALID_LAYERS:
            continue
        aliases = [a.strip() for a in (k.get("aliases") or [])
                   if isinstance(a, str) and a.strip() and a.strip() != term]
        llm_list.append({"layer": layer, "term": term,
                         "aliases": aliases, "src": "llm"})
    llm_list = core.dedupe_substrings(llm_list)
    extra = [x for x in llm_list if x["term"] not in rule_terms]

    meta.update({
        "source": "llm+rules",
        "job_title": (obj.get("job_title") or "").strip(),
        "job_context": (obj.get("job_context") or "").strip(),
        "notes_cn": (obj.get("notes_cn") or "").strip(),
        "llm_only": len(extra),
        "reason": "",
    })
    return rules + extra, meta


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


# ---------------------------------------------------------------------------
# 四、针对"真缺"的必需词，反过来问候选人（可选环节）
# ---------------------------------------------------------------------------
def make_questions(res, jd_text, resume_text, limit=5):
    """工具判"真缺"的词，可能只是候选人没写。让模型生成核实问题。

    用户回答了「有」，这个词才算数；不答或答「没有」，就不能写进简历。
    没有 API Key 时用模板兜底，保证功能不中断。
    """
    missing = [x for x in res["rows"]
               if not x["hit_lenient"] and x["necessity"] == "must"]
    if not missing:
        return []

    if llm.has_key():
        try:
            brief = "\n".join("- %s（%s）" % (x["term"], x["layer_cn"])
                              for x in missing[:12])
            obj = llm.chat_json(
                prompts.ASK_PROMPT,
                "【岗位 JD】\n%s\n\n【简历里没命中的必需关键词】\n%s"
                % (jd_text[:3000], brief))
            qs = []
            for q in (obj.get("questions") or []):
                question = (q.get("question") or "").strip()
                if not question:
                    continue
                qs.append({
                    "keyword": (q.get("keyword") or "").strip(),
                    "question": question,
                    "why": (q.get("why") or "").strip(),
                })
            if qs:
                return qs[:limit]
        except RuntimeError:
            pass

    return [{
        "keyword": x["term"],
        "question": "你是否有「%s」相关的实际经历？有的话用一句话说说。" % x["term"],
        "why": "未在简历中体现",
    } for x in missing[:limit]]
