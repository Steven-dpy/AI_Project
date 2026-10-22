# -*- coding: utf-8 -*-
"""极简 LLM 客户端：走 OpenAI 兼容协议，只用标准库（urllib）。

为什么不装 openai 包：本项目的 v1 是零依赖的，v2 也不想因为一个 HTTP 调用
就把环境搞复杂。协议本身很简单，urllib 足够。

配置（全部从环境变量读，不写死任何密钥）
--------------------------------------
  LLM_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY   任一即可
  LLM_BASE_URL / OPENAI_BASE_URL                    默认 https://api.deepseek.com/v1
  MODEL_NAME                                        默认 deepseek-chat

用法
----
  from llm import has_key, chat_json
  if has_key():  obj = chat_json(system, user)
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# 最近一次调用的 token 用完，供上层打印成本
last_usage = {}


def _cfg():
    key = (os.environ.get("LLM_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY")
           or os.environ.get("OPENAI_API_KEY")
           or "")
    base = (os.environ.get("LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or DEFAULT_BASE).rstrip("/")
    model = os.environ.get("MODEL_NAME") or DEFAULT_MODEL
    return key, base, model


def has_key():
    return bool(_cfg()[0])


def config_summary():
    key, base, model = _cfg()
    return "%s @ %s（key %s）" % (model, base, "已配置" if key else "缺失")


def _strip_fence(s):
    s = (s or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def chat_json(system, user, timeout=120, retries=1):
    """发一次对话，返回解析好的 dict。失败抛 RuntimeError（带可读原因）。"""
    key, base, model = _cfg()
    if not key:
        raise RuntimeError(
            "没有配置 LLM API Key。请设置环境变量后再跑 v2：\n"
            "    $env:DEEPSEEK_API_KEY = \"sk-...\"\n"
            "（DeepSeek 开放平台注册后充值即可，跑本项目几百次大约几元）"
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )

    err = None
    for _ in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            err = "HTTP %s：%s" % (e.code, detail)
            continue
        except Exception as e:  # 网络/超时
            err = "%s: %s" % (type(e).__name__, e)
            continue

        try:
            content = body["choices"][0]["message"]["content"]
        except Exception:
            err = "返回结构异常：%s" % str(body)[:300]
            continue

        global last_usage
        last_usage = body.get("usage") or {}

        try:
            return json.loads(_strip_fence(content))
        except Exception as e:
            err = "JSON 解析失败（%s）：%s" % (e, (content or "")[:200])

    raise RuntimeError("LLM 调用失败：" + str(err))
