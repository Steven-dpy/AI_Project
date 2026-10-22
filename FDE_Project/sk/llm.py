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

try:
    import cache
except ImportError:  # 直接单文件运行时兜底
    cache = None

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

# 最近一次调用的 token 用完，供上层打印成本
last_usage = {}


KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apikey.txt")


def read_key_file():
    """读 sk/apikey.txt。支持裸 key，也支持 KEY=value 形式；# 开头是注释。

    为什么还要支持文件：让不习惯环境变量的人改一个文件就能用，
    免得每开一个新终端都要重新设置一遍。
    """
    vals = {}
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if "=" in s:
                    k, v = s.split("=", 1)
                    vals[k.strip().upper()] = v.strip()
                else:
                    vals.setdefault("KEY", s)
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return {}
    return vals


def _cfg():
    f = read_key_file()
    key = (os.environ.get("LLM_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY")
           or os.environ.get("OPENAI_API_KEY")
           or f.get("LLM_API_KEY") or f.get("DEEPSEEK_API_KEY")
           or f.get("OPENAI_API_KEY") or f.get("KEY")
           or "").strip()
    base = (os.environ.get("LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or f.get("BASE_URL") or f.get("LLM_BASE_URL")
            or DEFAULT_BASE).rstrip("/")
    model = os.environ.get("MODEL_NAME") or f.get("MODEL") or DEFAULT_MODEL
    return key, base, model


def key_source():
    """key 是从哪里来的，用于控制台显示。"""
    if (os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")):
        return "环境变量"
    if read_key_file():
        return "sk/apikey.txt"
    return "缺失"


def vision_cfg():
    """图片识别用的配置。和主模型分开，因为 DeepSeek 没有视觉模型。"""
    key, base, _model = _cfg()
    f = read_key_file()
    vmodel = (os.environ.get("VISION_MODEL") or f.get("VISION_MODEL") or "").strip()
    vbase = (os.environ.get("VISION_BASE_URL")
             or f.get("VISION_BASE_URL") or base).rstrip("/")
    vkey = (os.environ.get("VISION_API_KEY")
            or f.get("VISION_API_KEY") or key).strip()
    return vkey, vbase, vmodel


def chat_vision(prompt, data_uri, timeout=180):
    """把一张图片（data URI）交给视觉模型，返回纯文本。"""
    vkey, vbase, vmodel = vision_cfg()
    if not vmodel:
        raise RuntimeError(
            "上传图片需要视觉模型——DeepSeek 的对话模型不能看图，这是模型能力限制，不是没做。\n"
            "二选一，把几行追加到 sk/apikey.txt，保存后刷新页面即可（不用重启服务）：\n"
            "① 智谱 GLM-4V-Flash（免费，注册最简单）\n"
            "     VISION_MODEL=glm-4v-flash\n"
            "     VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4\n"
            "     VISION_API_KEY=你的智谱密钥   ← https://open.bigmodel.cn\n"
            "② 通义千问 Qwen-VL（阿里云百炼，有免费额度）\n"
            "     VISION_MODEL=qwen-vl-plus\n"
            "     VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1\n"
            "     VISION_API_KEY=sk-你的百炼密钥\n"
            "不想配也行：txt / pdf / docx 全部正常——或者把图片里的文字复制粘贴出来。"
        )
    payload = {
        "model": vmodel,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }],
        "temperature": 0.1,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        vbase + "/chat/completions", data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + vkey})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("视觉模型调用失败 HTTP %s：%s"
                           % (e.code, e.read().decode("utf-8", "replace")[:300]))
    except Exception as e:
        raise RuntimeError("视觉模型调用失败：%s: %s" % (type(e).__name__, e))
    try:
        return body["choices"][0]["message"]["content"] or ""
    except Exception:
        raise RuntimeError("视觉模型返回结构异常：%s" % str(body)[:300])


def has_key():
    return bool(_cfg()[0])


def config_summary():
    key, base, model = _cfg()
    return "%s @ %s（key：%s）" % (model, base, key_source())


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
            "没有配置 LLM API Key。两种方式二选一：\n"
            "  ① 把 Key 粘贴到 sk/apikey.txt 里（推荐，改完存盘即可）\n"
            "  ② 设置环境变量：$env:DEEPSEEK_API_KEY = \"sk-...\"\n"
            "Key 在 https://platform.deepseek.com 「API keys」里创建。"
        )
    # 粘贴时最容易带上的东西：引号、空格、整句话
    if " " in key or "\t" in key or len(key) < 16:
        raise RuntimeError(
            "读到的 Key 不像有效的 API Key（长度 %d，或含空格/引号）。\n"
            "请检查 sk/apikey.txt：只粘贴 sk- 开头那一串，不要引号、不要说明文字。"
            % len(key)
        )

    # 缓存 key 必须包含**完整** system prompt —— 只用前 N 个字符会导致
    # 改了 prompt 后半部分却仍然命中旧缓存。
    cache_name = "chat|%s|%s" % (model, system)
    if cache is not None:
        hit = cache.get(cache_name, user)
        if hit is not None:
            return hit

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
            obj = json.loads(_strip_fence(content))
        except Exception as e:
            err = "JSON 解析失败（%s）：%s" % (e, (content or "")[:200])
            continue
        if cache is not None:
            cache.put(cache_name, user, obj)
        return obj

    raise RuntimeError("LLM 调用失败：" + str(err))
