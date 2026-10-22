# inputs/ —— 命令行模式用的输入目录

网页版不需要这个目录（直接在页面上传文件即可）。
只有用命令行时需要：

```bash
# 把 JD 放这里，文件名以 jd_ 开头
inputs/jd_01_某公司_某岗位.txt
inputs/jd_02_某公司_某岗位.txt

# 简历也放这里
inputs/resume.txt
```

然后：

```bash
python sk/main.py --resume inputs/resume.txt
```

会跑完 `inputs/jd_*.txt` 下所有 JD，报告写到 `out/`。

---

## 支持的格式

| 格式 | 是否需要额外依赖 |
|---|---|
| `.txt` `.md` | 不需要 |
| `.docx` | 不需要（直接解析 OOXML） |
| `.pdf` | 需要 `pdfplumber`（`启动.bat` 会自动装） |

---

## 注意

`inputs/` 下除本文件和 `.gitkeep` 外，全部被 `.gitignore` 忽略 ——
**你自己的 JD 和简历不会被推到 GitHub。**
