# -*- coding: utf-8 -*-
"""结构化简历 → DOCX（手写 OOXML，不依赖 python-docx / 不需要装 Word）。

输入 spec 结构：
{
  "name": "张三",
  "title": "求职意向：某某岗位 / 某某方向",
  "contact": ["电话：+86 ...", "邮箱：...", "2026 年 10 月毕业 | 可随时到岗"],
  "sections": [
      {"title": "核心优势", "items": ["...", "..."]},
      {"title": "项目经历", "items": ["..."]}
  ]
}
"""
import os
import zipfile

EA = "微软雅黑"
LAT = "Calibri"
PRIMARY = "1F4E5F"
RULE = "A8C8D4"
INK = "262626"
GREY = "6E6E6E"

CONTENT_W = 9866
LINE = 276

NS = (
    'xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
)

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults>
<w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Calibri" w:eastAsia="微软雅黑" w:hAnsi="Calibri" w:cs="Calibri"/>
<w:color w:val="262626"/><w:sz w:val="21"/><w:szCs w:val="21"/>
<w:lang w:val="en-US" w:eastAsia="zh-CN"/>
</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr>
<w:widowControl w:val="0"/><w:snapToGrid w:val="0"/>
<w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="both"/>
</w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
</w:styles>"""

SETTINGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:zoom w:percent="100"/><w:defaultTabStop w:val="420"/>
<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>
<w:themeFontLang w:val="en-US" w:eastAsia="zh-CN"/>
</w:settings>"""

SECT = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1037" w:left="1134" '
        'w:header="720" w:footer="720" w:gutter="0"/>'
        '<w:cols w:space="720"/><w:docGrid w:linePitch="312"/></w:sectPr>')


def esc(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rpr(sz=21, bold=False, color=INK, ea=EA, lat=LAT):
    s = ('<w:rFonts w:ascii="%s" w:eastAsia="%s" w:hAnsi="%s" w:cs="%s" w:hint="eastAsia"/>'
         % (lat, ea, lat, lat))
    if bold:
        s += "<w:b/><w:bCs/>"
    s += '<w:color w:val="%s"/>' % color
    s += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (sz, sz)
    return "<w:rPr>%s</w:rPr>" % s


def run(text, **kw):
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (_rpr(**kw), esc(text))


def para(body="", before=0, after=0, line=LINE, jc="both", ind=None, pBdr=None,
         keep_next=False, exact=True, tabs=None):
    x = "<w:p><w:pPr>"
    if keep_next:
        x += "<w:keepNext/>"
    if pBdr:
        x += pBdr
    if tabs:
        x += tabs
    x += ('<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="%s"/>'
          % (before, after, line, "exact" if exact else "auto"))
    if ind:
        x += ind
    x += '<w:jc w:val="%s"/>' % jc
    x += "</w:pPr>" + body + "</w:p>"
    return x


BULLET_TABS = '<w:tabs><w:tab w:val="left" w:pos="300"/></w:tabs>'
BULLET_IND = '<w:ind w:left="300" w:hanging="300"/>'


def bullet(text, label="", after=14):
    """label 渲染成加粗引导短语，text 是正文。"""
    body = run("\u2022" + "\t", bold=True, color=PRIMARY)
    if label:
        body += run(label + "：", bold=True, color="1A1A1A")
    body += run(text, color=INK)
    return para(body, after=after, jc="both", ind=BULLET_IND,
                tabs=BULLET_TABS, exact=True)


def section_title(text):
    pBdr = ('<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="3" w:color="%s"/></w:pBdr>'
            % RULE)
    return para(run(text, sz=23, bold=True, color=PRIMARY),
                before=150, after=60, line=262, jc="left",
                pBdr=pBdr, keep_next=True)


def build(spec, out_path):
    body = []
    # 抬头
    body.append(para(run(spec.get("name") or "简历", sz=40, bold=True, color=PRIMARY),
                     after=60, line=250, jc="left"))
    if spec.get("title"):
        body.append(para(run(spec["title"], sz=21, bold=True, color="3B3B3B"),
                         after=50, line=250, jc="left"))
    for c in (spec.get("contact") or []):
        if c:
            body.append(para(run(c, sz=19, color=GREY), after=26, line=240, jc="left"))
    body.append(para("", after=0, line=20, exact=True, jc="left",
                     pBdr=('<w:pBdr><w:bottom w:val="single" w:sz="12" w:space="1" '
                           'w:color="%s"/></w:pBdr>' % PRIMARY)))

    for sec in (spec.get("sections") or []):
        st = (sec.get("title") or "").strip()
        items = sec.get("items") or []
        if not st or not items:
            continue
        body.append(section_title(st))
        for it in items:
            if isinstance(it, dict):
                lab = (it.get("label") or "").strip()
                txt = (it.get("text") or "").strip()
            else:
                lab, txt = "", str(it or "").strip()
            if not txt and not lab:
                continue
            body.append(bullet(txt, label=lab))

    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
                '<w:document ' + NS + ' mc:Ignorable="w14">' '<w:body>'
                + "".join(body) + SECT + "</w:body></w:document>")

    core_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties '
                'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:title>%s</dc:title><dc:creator>%s</dc:creator>'
                '</cp:coreProperties>' % (esc(spec.get("name") or "简历"),
                                          esc(spec.get("name") or "")))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    files = [
        ("[Content_Types].xml", CONTENT_TYPES),
        ("_rels/.rels", ROOT_RELS),
        ("word/document.xml", document),
        ("word/styles.xml", STYLES),
        ("word/settings.xml", SETTINGS),
        ("word/_rels/document.xml.rels", DOC_RELS),
        ("docProps/core.xml", core_xml),
    ]
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            z.writestr(name, data.encode("utf-8"))
    os.replace(tmp, out_path)
    return out_path
