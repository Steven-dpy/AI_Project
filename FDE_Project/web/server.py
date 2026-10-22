# -*- coding: utf-8 -*-
"""本地网页服务：可被搜索性诊断器。

安全边界（写在这里，也写在页面上）：
  · 只监听 127.0.0.1，同一局域网的其他机器访问不到
  · 上传的简历 / JD / 生成的 Word，全部落在 web/uploads 与 web/outputs
  · 全流程只有一件事会联网：调用模型 API（你和 apikey.txt 里配置的那个）
  · 不做任何统计上报、不做远程更新

运行：  python web/server.py
或双击根目录的「启动.bat」
"""
import base64
import io
import json
import os
import re
import sys
import threading
import webbrowser
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "sk"))
sys.path.insert(0, HERE)

import core      # noqa: E402
import docgen    # noqa: E402
import llm       # noqa: E402
import prompts   # noqa: E402
import v2        # noqa: E402

try:
    # 如果启动脚本已经指定了编码（PYTHONIOENCODING），就尊重它——
    # 否则中文 Windows 的控制台是 GBK，强行输出 UTF-8 会乱码。
    if not os.environ.get("PYTHONIOENCODING"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STATIC = os.path.join(HERE, "static")
UPLOADS = os.path.join(HERE, "uploads")
OUTPUTS = os.path.join(HERE, "outputs")

HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "8765"))
MAX_BODY = 30 * 1024 * 1024

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


# ---------------------------------------------------------------------------
# 文本提取
# ---------------------------------------------------------------------------
def _unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&apos;", "'").replace("&amp;", "&"))


def _docx_text(raw):
    """不依赖 python-docx：直接解析 word/document.xml。

    注意正则必须写成 <w:t(?:\\s[^>]*)?>：只写 <w:t[^>]*> 会把 <w:tabs>、<w:tab .../>
    这些标签一起匹配进来，正文里就会混进 XML 字符串。
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    rx = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
    out = []
    for p in re.split(r"</w:p>", xml):
        t = _unescape("".join(rx.findall(p))).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def _pdf_text(raw):
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "读取 PDF 需要 pdfplumber。请关掉窗口，重新双击「启动.bat」——"
            "它会自动安装（只需联网一次）。"
        )
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def extract_text(name, mime, b64):
    """返回 (纯文本, 原始字节)。"""
    raw = base64.b64decode(b64)
    ext = os.path.splitext(name or "")[1].lower()
    mime = mime or ""

    if ext in (".txt", ".md", "") or mime.startswith("text/"):
        for enc in ("utf-8", "gbk", "utf-16"):
            try:
                return raw.decode(enc), raw
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace"), raw

    if ext == ".docx":
        return _docx_text(raw), raw

    if ext == ".pdf":
        return _pdf_text(raw), raw

    if ext in IMG_EXT or mime.startswith("image/"):
        data_uri = "data:%s;base64,%s" % (
            mime or "image/png", base64.b64encode(raw).decode())
        txt = llm.chat_vision(
            "请把这张图片里的全部文字完整提取出来，保持原有的段落与条目结构；"
            "不要总结、不要翻译、不要添加任何解释。只输出文字本身。", data_uri)
        return txt, raw

    raise RuntimeError("不支持的文件类型：%s" % (ext or "未知"))


def _safe_stem(name, default="file"):
    s = os.path.splitext(os.path.basename(name or ""))[0]
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", s).strip("._")[:40]
    return s or default


def flatten_spec(spec):
    """把改写后的结构化简历拍平成纯文本，用于重新算覆盖率。"""
    parts = [spec.get("name") or "", spec.get("title") or ""]
    parts += [str(c) for c in (spec.get("contact") or [])]
    for sec in (spec.get("sections") or []):
        parts.append(sec.get("title") or "")
        for it in (sec.get("items") or []):
            if isinstance(it, dict):
                parts.append("%s %s" % (it.get("label") or "", it.get("text") or ""))
            else:
                parts.append(str(it or ""))
    return "\n".join(p for p in parts if p and p.strip())


# ---------------------------------------------------------------------------
# HTTP 处理器
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "SearchKit/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静音默认访问日志

    def handle_one_request(self):
        """浏览器/客户端断开连接时会抛 ConnectionResetError。
        默认实现会打一整段 traceback，用户会以为程序坏了，这里吞掉。"""
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError,
                BrokenPipeError, TimeoutError):
            self.close_connection = True

    # ---- 基础响应 ----
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _file(self, path, ctype, download=None):
        if not os.path.isfile(path):
            return self._send(404, "文件不存在")
        with open(path, "rb") as f:
            data = f.read()
        extra = {}
        if download:
            extra["Content-Disposition"] = (
                "attachment; filename*=UTF-8''%s" % quote(download))
        self._send(200, data, ctype, extra)

    # ---- GET ----
    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"),
                              "text/html; charset=utf-8")
        if p.startswith("/static/"):
            fn = os.path.basename(unquote(p[len("/static/"):]))
            ext = os.path.splitext(fn)[1].lower()
            ct = {".css": "text/css; charset=utf-8",
                  ".js": "application/javascript; charset=utf-8",
                  ".svg": "image/svg+xml"}.get(ext, "text/plain; charset=utf-8")
            return self._file(os.path.join(STATIC, fn), ct)
        if p.startswith("/download/"):
            fn = os.path.basename(unquote(p[len("/download/"):]))
            return self._file(
                os.path.join(OUTPUTS, fn),
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document", download=fn)
        if p == "/api/health":
            vm = llm.vision_cfg()[2]
            return self._json({
                "ok": True,
                "llm": llm.has_key(),
                "key_source": llm.key_source(),
                "config": llm.config_summary(),
                "vision_model": vm,
                "model": llm.config_summary(),
            })
        self._send(404, "404")

    # ---- POST ----
    def do_POST(self):
        p = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._json({"ok": False, "error": "请求体为空或超过 30MB"}, 400)
        try:
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": "请求解析失败：%s" % e}, 400)

        if p == "/api/analyze":
            return self._analyze(payload)
        if p == "/api/ask":
            return self._ask(payload)
        if p == "/api/docx":
            return self._docx(payload)
        self._send(404, "404")

    # ---- 业务：诊断 ----
    def _analyze(self, payload):
        try:
            jd = payload["jd"]
            rs = payload["resume"]
        except (KeyError, TypeError):
            return self._json({"ok": False, "error": "缺少简历或 JD"}, 400)

        try:
            jd_text, jd_raw = extract_text(jd.get("name"), jd.get("mime"), jd["b64"])
            rs_text, rs_raw = extract_text(rs.get("name"), rs.get("mime"), rs["b64"])
        except RuntimeError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self._json({"ok": False, "error": "文件解析失败：%s" % e}, 400)

        if len(jd_text.strip()) < 30:
            return self._json({"ok": False,
                               "error": "JD 提取到的文字太少（可能是扫描件或空文件）"}, 400)
        if len(rs_text.strip()) < 30:
            return self._json({"ok": False,
                               "error": "简历提取到的文字太少（可能是扫描件或空文件）"}, 400)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(UPLOADS, exist_ok=True)
        os.makedirs(OUTPUTS, exist_ok=True)
        jd_stem = "jd_%s_%s" % (stamp, _safe_stem(jd.get("name"), "jd"))
        rs_stem = "resume_%s_%s" % (stamp, _safe_stem(rs.get("name"), "resume"))
        for stem, raw, text in ((jd_stem, jd_raw, jd_text), (rs_stem, rs_raw, rs_text)):
            with open(os.path.join(UPLOADS, stem + ".raw"), "wb") as f:
                f.write(raw)
            with open(os.path.join(UPLOADS, stem + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)

        try:
            kws, kmeta = v2.extract_keywords(jd_text, use_llm=True)
            res = core.analyze(jd_text, rs_text, jd_name=jd_stem, keywords=kws)
            sugg, smeta = v2.suggest(res, rs_text, jd_text, use_llm=True)
        except Exception as e:
            return self._json({"ok": False, "error": "分析失败：%s" % e}, 500)

        meta = dict(kmeta)
        meta.update(smeta)

        rows = []
        for x in res["rows"]:
            rows.append({
                "layer": x["layer_cn"], "term": x["term"],
                "src": x.get("src", "rules"),
                "necessity": x["necessity"],
                "hit": x["hit"], "lenient": x["hit_lenient"],
                "count": x["count"], "anchors": x.get("anchors") or [],
            })

        return self._json({
            "ok": True,
            "jd": {"title": res["jd_title"], "chars": len(jd_text), "saved": jd_stem},
            "resume": {"chars": len(rs_text), "saved": rs_stem,
                       "preview": rs_text[:600]},
            "resume_title": res["resume_title"],
            "title_align": res["title_align"],
            "scores": res["scores"],
            "rows": rows,
            "suggest": sugg,
            "meta": meta,
            "texts": {"resume": rs_text, "jd": jd_text},
        })

    # ---- 业务：生成核实问题（可选环节） ----
    def _ask(self, payload):
        resume_text = (payload.get("resume_text") or "").strip()
        jd_text = (payload.get("jd_text") or "").strip()
        if not resume_text or not jd_text:
            return self._json({"ok": False, "error": "缺少简历或 JD 正文"}, 400)
        try:
            kws, _meta = v2.extract_keywords(jd_text, use_llm=True)
            res = core.analyze(jd_text, resume_text, keywords=kws)
            questions = v2.make_questions(res, jd_text, resume_text)
        except Exception as e:
            return self._json({"ok": False, "error": "生成问题失败：%s" % e}, 500)
        return self._json({"ok": True, "questions": questions})

    # ---- 业务：导出 Word ----
    def _docx(self, payload):
        resume_text = (payload.get("resume_text") or "").strip()
        jd_text = (payload.get("jd_text") or "").strip()
        accepted = payload.get("accepted") or []
        if not resume_text:
            return self._json({"ok": False, "error": "缺少简历正文"}, 400)

        maybe_extra = payload.get("extra_keywords") or []
        extra_kw = [str(x).strip() for x in maybe_extra if str(x).strip()][:20]
        maybe_qa = payload.get("qa") or []
        qa = [x for x in maybe_qa if isinstance(x, dict)
              and (x.get("answer") or "").strip()][:8]

        user = ("【简历原文】\n%s\n\n【目标 JD】\n%s\n\n【已确认采纳的建议】\n%s\n\n"
                "【用户自己补充的关键词】\n%s\n\n"
                "【用户对核实问题的回答（只有这里明确说「有/做过」的才可以写进简历）】\n%s"
                % (resume_text[:8000], jd_text[:5000],
                   "\n".join("- " + a for a in accepted)
                   or "（无。仍请按 JD 做结构与措辞优化，但不得新增任何事实）",
                   "、".join(extra_kw) or "（无）",
                   "\n".join("- %s → %s" % ((x.get("question") or "")[:60],
                                            (x.get("answer") or "")[:200])
                             for x in qa) or "（无）"))
        try:
            spec = llm.chat_json(prompts.REWRITE_PROMPT, user)
        except RuntimeError as e:
            return self._json({"ok": False, "error": str(e)}, 400)

        # 姓名兜底：模型没取到就用前端传来的文件名，再不行取正文第一行短句
        name = (spec.get("name") or "").strip()
        if not name:
            name = (payload.get("name_hint") or "").strip()
        if not name:
            for line in resume_text.splitlines():
                s = line.strip()
                if s and len(s) <= 6:
                    name = s
                    break
        spec["name"] = name or "简历"

        fn = "简历_改写_%s.docx" % datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(OUTPUTS, fn)
        try:
            docgen.build(spec, out)
        except Exception as e:
            return self._json({"ok": False, "error": "生成 Word 失败：%s" % e}, 500)

        # 改前 / 改后覆盖对比：同一套关键词，可比
        before = after = None
        try:
            kws, _meta = v2.extract_keywords(jd_text, use_llm=True)
            b = core.analyze(jd_text, resume_text, keywords=kws)["scores"]
            n = core.analyze(jd_text, flatten_spec(spec), keywords=kws)["scores"]
            before = {"精确": b["精确"]["必需词"], "宽松": b["宽松"]["必需词"]}
            after = {"精确": n["精确"]["必需词"], "宽松": n["宽松"]["必需词"]}
        except Exception:
            pass

        return self._json({"ok": True, "file": fn,
                           "url": "/download/" + quote(fn),
                           "spec": spec, "before": before, "after": after})


# ---------------------------------------------------------------------------
def main():
    for d in (STATIC, UPLOADS, OUTPUTS):
        os.makedirs(d, exist_ok=True)

    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://%s:%d/" % (HOST, PORT)
    vm = llm.vision_cfg()[2]

    print("=" * 64)
    print("  可被搜索性诊断器 · 本地版")
    print("=" * 64)
    print("  地址      : %s" % url)
    print("  模型      : %s" % llm.config_summary())
    print("  图片识别  : %s" % (("已配置（%s）" % vm) if vm
                                else "未配置 → 只能传 txt/pdf/docx"))
    print("  数据位置  : %s" % HERE)
    print("  联网情况  : 只有调用模型 API 时联网；其余全部本机")
    print("=" * 64)
    print("  按 Ctrl+C 停止")
    print("")

    threading.Timer(1.2, lambda: webbrowser.open(url)).start() if not os.environ.get("APP_NO_BROWSER") else None
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
