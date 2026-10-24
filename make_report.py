# -*- coding: utf-8 -*-
"""分點籌碼・股票日報 — 固定排版產生器(寫死、測過,不要每次即席手寫)。
用法:
    python make_report.py digest.json out.pdf [--note "手動補跑 · 颱風假"] [--narrative narrative.json]

輸入:
  digest.json   = 日報 digest(結構見 chip.py compute_digest / 日報排程說明)
  narrative.json(選填)= 模型補的文字覆蓋,可含:
        {"oneLine":..., "marketMood":..., "obs":{"2002":...}, "closedNote":{"ai":[...],"me":[...]}}
      缺的欄位一律用內建模板,保證每段都有字、版面完整。

設計重點(修掉舊版兩大 bug):
  * 中文一律用 reportlab 內建 MSung-Light(各環境都有)→ 不會亂碼。
  * 單一 story 流式排版、不用 PageBreak;每張個股卡/持股列各自 KeepTogether 且夠小 → 不爆版、不丟內容、不產生空白頁。
  * 表格 colWidths 加總=版面寬 → 欄位不會被切掉。
非投資建議、未考證、養盤感用。
"""
import sys, json
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# ---------- 字型(優先內嵌 Noto 繁中 TTF;沒有才退回 MSung-Light 並強制繁體 CMap) ----------
import os, glob
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily


def _find(patterns):
    cands = []
    roots = ["/usr/share/fonts", "/usr/local/share/fonts",
             os.path.expanduser("~/.fonts"), "/Library/Fonts",
             "C:/Windows/Fonts", os.path.dirname(os.path.abspath(__file__))]
    for r in roots:
        for pat in patterns:
            cands += glob.glob(os.path.join(r, "**", pat), recursive=True)
    return cands


def _register_cjk():
    """回傳 (regular_name, bold_name, embedded?)。
       優先內嵌 TrueType CJK(繁簡皆含,手機一定顯示正常);找不到才退回 MSung-Light。
       注意:Noto CJK 是 CFF/OTF 輪廓,reportlab 無法內嵌 → 只找真正的 TrueType(glyf)。"""
    # 只挑 reportlab 能內嵌的 TrueType CJK(非 Noto/OTF)
    reg = _find(["wqy-zenhei.ttc", "wqy-microhei.ttc", "uming.ttc", "ukai.ttc",
                 "msjh.ttc", "mingliu.ttc", "msjh.ttf", "TaipeiSansTCBeta-Regular.ttf",
                 "DroidSansFallbackFull.ttf", "DroidSansFallback.ttf"])
    bold = _find(["wqy-zenhei.ttc", "msjhbd.ttc"])
    if reg:
        try:
            pdfmetrics.registerFont(TTFont("cjk", reg[0], subfontIndex=0))
            bname = "cjk"
            if bold:
                try:
                    pdfmetrics.registerFont(TTFont("cjkb", bold[0], subfontIndex=0)); bname = "cjkb"
                except Exception:
                    bname = "cjk"
            registerFontFamily("cjk", normal="cjk", bold=bname, italic="cjk", boldItalic=bname)
            return "cjk", bname, True
        except Exception:
            pass
    # 退回:MSung-Light。先修掉 reportlab 這版把繁體字配到簡體 GB CMap 的資料 bug → 改用繁體 UniCNS。
    try:
        import reportlab.pdfbase.cidfonts as _cf
        due = getattr(_cf, "defaultUnicodeEncodings", None)
        if isinstance(due, dict):
            due["MSung-Light"] = ("cht", "UniCNS-UCS2-H")
    except Exception:
        pass
    pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
    try:
        registerFontFamily("MSung-Light", normal="MSung-Light", bold="MSung-Light",
                           italic="MSung-Light", boldItalic="MSung-Light")
    except Exception:
        pass
    return "MSung-Light", "MSung-Light", False


FONT, FONT_B, FONT_EMBEDDED = _register_cjk()

# ---------- 顏色 ----------
NAVY   = colors.HexColor("#1f3a5f")
NAVY2  = colors.HexColor("#2c4a6e")
GREEN  = colors.HexColor("#1f7a44")
GREENB = colors.HexColor("#e9f5ee")
RED    = colors.HexColor("#c0392b")
REDB   = colors.HexColor("#fbeceb")
GREY   = colors.HexColor("#666666")
LINE   = colors.HexColor("#d8dee6")
ZEBRA  = colors.HexColor("#f4f6f9")

# ---------- 版面 ----------
PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ---------- 樣式 ----------
def _st(name, size, color=colors.black, leading=None, align=TA_LEFT, space_after=2):
    return ParagraphStyle(name, fontName=FONT, fontSize=size, textColor=color,
                          leading=leading or size + 4, alignment=align,
                          spaceAfter=space_after, spaceBefore=0)

S_TITLE   = _st("title", 22, colors.white, align=TA_CENTER, space_after=2)
S_SUB     = _st("sub", 10.5, colors.HexColor("#c9d6e5"), align=TA_CENTER, space_after=1)
S_SEC     = _st("sec", 13, colors.white, space_after=0)
S_BODY    = _st("body", 10, colors.black, leading=15, space_after=3)
S_MUTE    = _st("mute", 9, GREY, leading=13, space_after=3)
S_CARD_H  = _st("cardh", 11, NAVY, leading=15, space_after=1)
S_CARD    = _st("card", 9.2, colors.HexColor("#222222"), leading=13.5, space_after=1)
S_CARD_O  = _st("cardo", 9.2, colors.HexColor("#1f5fa8"), leading=13.5, space_after=1)
S_GOOD    = _st("good", 10.5, GREEN, space_after=2)
S_BAD     = _st("bad", 10.5, RED, space_after=2)
S_TAGLINE = _st("tag", 8, GREY, align=TA_CENTER)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------- 數字小工具 ----------
def num(x, nd=0, plus=False, dash="—"):
    if x is None:
        return dash
    try:
        v = float(x)
    except Exception:
        return esc(x)
    s = f"{v:+,.{nd}f}" if plus else f"{v:,.{nd}f}"
    if nd == 0:
        s = s.replace(".0", "")
    return s


def colored(val, text=None, nd=2, plus=True):
    """紅跌綠漲(台股色)。回傳 <font> 片段字串。"""
    if val is None:
        return (text or "—")
    try:
        v = float(val)
    except Exception:
        return esc(text if text is not None else val)
    t = text if text is not None else num(v, nd, plus=plus)
    c = "#c0392b" if v > 0 else ("#1f7a44" if v < 0 else "#555555")
    return f'<font color="{c}">{esc(t)}</font>'


# ---------- 區段標題列(深藍 bar) ----------
def section_bar(text):
    tb = Table([[Paragraph(esc(text), S_SEC)]], colWidths=[CONTENT_W])
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tb


def mini_bar(text, good=True):
    col = GREEN if good else RED
    bg = GREENB if good else REDB
    tb = Table([[Paragraph(esc(text), _st("mb", 10.5, col))]], colWidths=[CONTENT_W])
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tb


# ---------- 封面頁首 / 頁尾 ----------
def header_block(latest, note):
    sub = f"最新交易日 {esc(latest)}"
    if note:
        sub += f"（{esc(note)}）"
    inner = [
        [Paragraph("分點籌碼 · 股票日報", S_TITLE)],
        [Paragraph(sub, S_SUB)],
        [Paragraph("非投資建議 · 未考證 · 養盤感用", S_SUB)],
    ]
    tb = Table(inner, colWidths=[CONTENT_W])
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (0, 0), 16),
        ("BOTTOMPADDING", (0, -1), (0, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return tb


class ReportDoc(BaseDocTemplate):
    def __init__(self, path, latest, **kw):
        super().__init__(path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN, bottomMargin=18 * mm, **kw)
        self.latest = latest
        frame = Frame(MARGIN, 18 * mm, CONTENT_W, PAGE_H - MARGIN - 18 * mm, id="main",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="t", frames=[frame], onPage=self._foot)])

    def _foot(self, canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(GREY)
        txt = f"分點籌碼 · 股票日報   {self.latest}   · 非投資建議 · 養盤感用 ·   第 {doc.page} 頁"
        canvas.drawCentredString(PAGE_W / 2, 10 * mm, txt)
        canvas.restoreState()


# ===================== 內容組裝 =====================
def build_story(d, note, nar):
    story = []
    g = d.get
    latest = g("latest", "")

    story.append(header_block(latest, note))
    story.append(Spacer(1, 10))

    # ---- 一、池內廣度 ----
    story.append(section_bar("一、池內廣度"))
    story.append(Spacer(1, 4))
    vc = g("verdictCounts") or {}
    bull = vc.get("偏多觀察", 0)
    poolN = g("poolN", "—"); avg = g("avgScore")
    flips = len(g("flips") or [])
    story.append(Paragraph(
        f"最新交易日 {esc(latest)}｜池內 {poolN} 檔、平均健檢 {num(avg,1)}。", S_BODY))
    if vc:
        dist = "、".join(f"{esc(k)} {v}" for k, v in vc.items())
        story.append(Paragraph(f"判定分布:{dist}。", S_BODY))
    story.append(Paragraph(
        f"翻掉家數 {flips} 檔;吸貨 ambush {g('ambushN','—')}、投信連買 {g('trustStreakN','—')} 檔。", S_BODY))
    one = (nar.get("oneLine") if nar else None) or default_oneline(d)
    story.append(Paragraph("一句話:" + esc(one), S_MUTE))
    if g("ndays", 99) and int(g("ndays", 99) or 99) <= 3:
        story.append(Paragraph("(分點天數少,變化僅供參考)", S_MUTE))
    story.append(Spacer(1, 8))

    # ---- 二、大盤 / 類股 ----
    story.append(section_bar("二、大盤 / 類股"))
    story.append(Spacer(1, 4))
    m = g("market")
    if m:
        taiex = num(m.get("taiex"), 2)
        chg = colored(m.get("chg"), text=num(m.get("chg"), 2, plus=True))
        chgp = colored(m.get("chgPct"), text=num(m.get("chgPct"), 2, plus=True) + "%")
        story.append(Paragraph(
            f"加權 {taiex}({chg} / {chgp})｜量 {num(m.get('turnover'),1)} 億。", S_BODY))
        story.append(Paragraph(
            f"三大法人(億):外資 {colored(m.get('foreign'),nd=1)}、"
            f"投信 {colored(m.get('trust'),nd=1)}、自營 {colored(m.get('dealer'),nd=1)}。", S_BODY))
        mood = (nar.get("marketMood") if nar else None) or default_market_mood(m)
        story.append(Paragraph("氛圍:" + esc(mood), S_MUTE))
    else:
        story.append(Paragraph("大盤今日缺。", S_MUTE))
    story.append(Spacer(1, 4))

    sectors = g("sectors")
    if sectors:
        rows = [["類股", "檔數", "強勢", "吸貨", "平均健檢"]]
        for s in sectors[:6]:
            rows.append([esc(s.get("ind", "")), str(s.get("n", "")), str(s.get("strong", "")),
                         str(s.get("ambush", "")), num(s.get("avgScore"), 1)])
        colw = [CONTENT_W - 4 * 55, 55, 55, 55, 55]
        tb = Table(rows, colWidths=colw, repeatRows=1)
        style = [
            ("FONTNAME", (0, 0), (-1, -1), FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY2),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (0, -1), 8),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ]
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        tb.setStyle(TableStyle(style))
        story.append(tb)
        story.append(Paragraph("(類股取平均健檢前幾名)", S_MUTE))
    else:
        story.append(Paragraph("產業分類尚未併入。", S_MUTE))
    story.append(Spacer(1, 8))

    # ---- 三、主力真假動作掃描 ----
    story.append(section_bar("三、主力真假動作掃描(好壞都列)"))
    story.append(Spacer(1, 4))
    moves = g("moves") or {}
    story.append(Paragraph("▲ 好的嫌疑(主力疑似做多)", S_GOOD))
    story.append(move_block("拉高進貨", moves.get("拉高進貨"), True))
    story.append(move_block("殺低進貨", moves.get("殺低進貨"), True))
    story.append(Spacer(1, 3))
    story.append(Paragraph("▼ 壞的嫌疑(主力疑似出貨)", S_BAD))
    story.append(move_block("拉高出貨", moves.get("拉高出貨"), False))
    story.append(move_block("殺低出貨", moves.get("殺低出貨"), False))
    story.append(Paragraph("提醒:皆為嫌疑非鐵證,僅供觀察方向、非買賣依據。", S_MUTE))
    story.append(Spacer(1, 8))

    # ---- 四、股票日報(健檢前 10) ----
    story.append(section_bar("四、股票日報(健檢前 10)"))
    story.append(Spacer(1, 5))
    top = g("top") or []
    obsmap = (nar.get("obs") if nar else None) or {}
    for c in top[:10]:
        story.append(stock_card(c, obsmap))
        story.append(Spacer(1, 6))
    if not top:
        story.append(Paragraph("今日無個股資料。", S_MUTE))
    story.append(Spacer(1, 4))

    # ---- 五、反面教材 ----
    flips_list = g("flips") or []
    story.append(section_bar("五、反面教材(翻掉的)"))
    story.append(Spacer(1, 4))
    if flips_list:
        codes = "、".join(esc(str(x)) for x in flips_list[:30])
        story.append(Paragraph(f"今日翻掉 {len(flips_list)} 檔:{codes}", S_BODY))
        story.append(Paragraph("提醒:翻掉=由偏多轉弱或跌破關鍵,留作日後比對,看當初訊號哪裡失真。", S_MUTE))
    else:
        story.append(Paragraph("今日無明顯翻掉名單。", S_MUTE))
    story.append(Spacer(1, 8))

    # ---- 六、模擬投資組合 ----
    story.append(section_bar("六、模擬投資組合(兩組分開)"))
    story.append(Spacer(1, 5))
    port = g("portfolios") or {}
    story.append(Paragraph("(A)我的組合", S_CARD_H))
    story += portfolio_block(port.get("me"), nar.get("closedNote", {}).get("me") if nar else None)
    story.append(Spacer(1, 6))
    story.append(Paragraph("(B)AI 組合", S_CARD_H))
    story += portfolio_block(port.get("ai"), nar.get("closedNote", {}).get("ai") if nar else None)
    story.append(Spacer(1, 8))

    # ---- 七、結尾 ----
    story.append(section_bar("七、結尾"))
    story.append(Spacer(1, 4))
    tail = f"數字已存 digest/digest_{esc(latest)}.json 供考證。"
    if note:
        tail += f" 本報為{esc(note)},採最新交易日 {esc(latest)} 資料。"
    story.append(Paragraph(tail, S_BODY))
    story.append(Paragraph("全篇:非投資建議、未考證、養盤感用。", S_MUTE))
    return story


def move_block(label, codes, good):
    codes = codes or []
    if not codes:
        body = f'<font color="#888888">{label}:今日無明顯</font>'
    else:
        joined = "、".join(esc(str(x)) for x in codes)
        col = "#1f7a44" if good else "#c0392b"
        body = f'<font color="{col}">{label}</font>　{esc(joined)}'
    p = Paragraph(body, S_CARD)
    bg = GREENB if good else REDB
    tb = Table([[p]], colWidths=[CONTENT_W])
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tb


def stock_card(c, obsmap):
    g = c.get
    code = str(g("code", ""))
    act = g("act")
    # 情境標籤
    if act:
        tag = act
    elif (g("pos") or 0) and float(g("pos") or 0) > 80:
        tag = "高檔留意"
    elif g("last") is not None and g("cost") is not None and float(g("last")) < float(g("cost")):
        tag = "吸貨未發動"
    else:
        tag = g("verdict", "")
    head = f'<b>{esc(code)}</b>　<font color="#1f5fa8">{esc(tag)}</font>'

    chg = colored(g("chg"), text=num(g("chg"), 1, plus=True) + "%")
    line1 = (f"健檢 {g('score','—')} · {esc(g('verdict',''))} · "
             f"收 {num(g('last'),2)}({chg} · 位階 {num(g('pos'),0)})")

    vn = g("vn"); parts2 = []
    if vn:
        parts2.append(f"量性質:{esc(vn)}")
    if act:
        parts2.append(f"主力:{esc(act)}")
    line2 = "　｜　".join(parts2) if parts2 else None

    line3 = (f"籌碼:地緣囤 {num(g('lead'),0)}(連{g('maxStreak','?')})· "
             f"投信 {num(g('trustCum'),0)}(連{g('trustStreak','?')})· "
             f"外資 {num(g('foreign'),0)} · 融資 {num(g('finPct'),1,plus=True)}% · 集中度 {esc(g('conc','—'))}")

    stand = g("stand") or ""
    line4 = (f"位置:站上 {g('above','?')}/4 均線 · 量比 {num(g('vol'),1)}x · "
             f"壓 {num(g('R'),2)} / 撐 {num(g('S'),2)} · 成本 {num(g('cost'),2)}"
             + (f" · {esc(stand)}" if stand else ""))

    obs = obsmap.get(code) or obsmap.get(str(code)) or default_obs(c)

    flow = [Paragraph(head, S_CARD_H),
            Paragraph(line1, S_CARD)]
    if line2:
        flow.append(Paragraph(line2, S_CARD))
    flow.append(Paragraph(line3, S_CARD))
    flow.append(Paragraph(line4, S_CARD))
    flow.append(Paragraph("觀察:" + esc(obs), S_CARD_O))

    inner = Table([[f] for f in flow], colWidths=[CONTENT_W - 10])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEBEFORE", (0, 0), (0, -1), 3, NAVY),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfe")),
        ("TOPPADDING", (0, 0), (0, 0), 5), ("BOTTOMPADDING", (0, -1), (0, -1), 5),
    ]))
    return KeepTogether(inner)


def portfolio_block(p, closed_notes):
    out = []
    if not p:
        out.append(Paragraph("目前無持股。", S_MUTE))
        return out
    positions = p.get("positions") or []
    if positions:
        rows = [["代號", "股數", "成本", "現價", "未實現%"]]
        for q in positions:
            rows.append([esc(q.get("stock", "")), num(q.get("shares"), 0),
                         num(q.get("cost"), 2), num(q.get("px"), 2),
                         num(q.get("pnlPct"), 1, plus=True) + "%"])
        colw = [CONTENT_W - 4 * 70, 70, 70, 70, 70]
        tb = Table(rows, colWidths=colw, repeatRows=1)
        st = [("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 9),
              ("BACKGROUND", (0, 0), (-1, 0), NAVY2), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
              ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("ALIGN", (0, 0), (0, -1), "LEFT"),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
              ("LEFTPADDING", (0, 0), (0, -1), 8),
              ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE)]
        for i in range(2, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        tb.setStyle(TableStyle(st))
        out.append(tb)
    else:
        out.append(Paragraph("目前無持股。", S_MUTE))

    summ = (f"未實現總損益 {num(p.get('openPnl'),0,plus=True)}"
            f"({num(p.get('openPnlPct'),1,plus=True)}%)· "
            f"已實現 {num(p.get('realizedPnl'),0,plus=True)} · "
            f"交易數 {p.get('nTrades','—')} · 勝率 {num(p.get('winRate'),0)}%")
    out.append(Paragraph(summ, S_BODY))

    closed = p.get("closedToday") or []
    if closed:
        out.append(Paragraph("今日結單分析:", S_CARD_H))
        for i, t in enumerate(closed):
            line = (f"{esc(t.get('stock',''))} · {num(t.get('shares'),0)} 股 · "
                    f"{num(t.get('openPx'),2)}→{num(t.get('closePx'),2)} · "
                    f"損益 {num(t.get('pnlPct'),1,plus=True)}% · 持 {t.get('holdDays','?')} 日 · "
                    f"出場 {esc(t.get('reason',''))}")
            out.append(Paragraph(line, S_CARD))
            note = None
            if closed_notes and i < len(closed_notes):
                note = closed_notes[i]
            note = note or default_closed_note(t)
            out.append(Paragraph("白話:" + esc(note), S_CARD_O))
    return out


# ===================== 內建文字模板(narrative 缺時用) =====================
def default_oneline(d):
    vc = d.get("verdictCounts") or {}
    bull = vc.get("偏多觀察", 0)
    flips = len(d.get("flips") or [])
    avg = d.get("avgScore")
    tone = "偏多" if (avg or 0) >= 60 else ("中性偏弱" if (avg or 0) >= 45 else "偏弱")
    mood = "偏積極" if bull > flips else "偏保守、留意上方承接"
    return f"偏多觀察 {bull} 家 vs 翻掉 {flips} 家、平均健檢 {num(avg,1)}({tone}),整體氛圍{mood}?"


def default_market_mood(m):
    f = m.get("foreign") or 0
    cp = m.get("chgPct") or 0
    side = "偏空" if cp < 0 else "偏多"
    fr = "外資大賣" if f <= -300 else ("外資賣超" if f < 0 else "外資買超")
    return f"{fr}、大盤{'' if cp<0 else '上漲'}{num(abs(cp),2)}%,短線風險{side}、留意賣壓是否延續?"


def default_obs(c):
    act = c.get("act"); ts = c.get("trustStreak") or 0
    cost = c.get("cost"); last = c.get("last"); R = c.get("R")
    bits = []
    if act == "拉高進貨?":
        bits.append("價漲且主力同向進貨")
    elif act == "殺低進貨?":
        bits.append("殺低但主力疑似逢低承接")
    if ts and ts >= 3:
        bits.append(f"投信連{ts}是否續買")
    if cost and last is not None:
        if float(last) >= float(cost):
            bits.append(f"能否守住成本 {num(cost,2)} 之上")
        else:
            bits.append(f"尚在成本 {num(cost,2)} 之下,待站回")
    if R:
        bits.append(f"上看壓力 {num(R,2)}")
    return ("、".join(bits) + "?") if bits else "觀察量能與籌碼是否延續?"


def default_closed_note(t):
    r = t.get("pnlPct")
    feat = t.get("openFeat") or {}
    sc = feat.get("score"); pos = feat.get("pos")
    base = f"進場健檢 {sc if sc is not None else '—'}、位階 {pos if pos is not None else '—'};"
    try:
        v = float(r)
    except Exception:
        v = 0
    if v > 3:
        base += "結果獲利出場,訊號有效。"
    elif v < -3:
        base += "結果虧損,檢討是否追高或訊號失真。"
    else:
        base += "進出接近平盤,時間成本為主要風險。"
    return base


# ===================== main =====================
def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("用法: python make_report.py digest.json out.pdf [--note ...] [--narrative narrative.json]")
        sys.exit(1)
    digest_path, out_path = args[0], args[1]
    note = ""
    nar = {}
    if "--note" in args:
        note = args[args.index("--note") + 1]
    if "--narrative" in args:
        try:
            with open(args[args.index("--narrative") + 1], encoding="utf-8") as f:
                nar = json.load(f)
        except Exception:
            nar = {}
    with open(digest_path, encoding="utf-8") as f:
        d = json.load(f)

    doc = ReportDoc(out_path, d.get("latest", ""))
    story = build_story(d, note, nar)
    doc.build(story)
    print(f"OK 產出 {out_path}")


if __name__ == "__main__":
    main()
