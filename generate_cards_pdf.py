from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARDS_DIR = os.path.join(BASE_DIR, "frontend", "public", "decks", "rider-waite")
OUTPUT = os.path.join(BASE_DIR, "cards.pdf")

# Any TTF with Cyrillic coverage works; override with CARDS_PDF_FONT.
FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
BOLD_BY_REGULAR = {
    "C:/Windows/Fonts/arial.ttf": "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial.ttf": "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
}


def resolve_regular_font():
    env_font = os.environ.get("CARDS_PDF_FONT")
    if env_font:
        if not os.path.exists(env_font):
            raise SystemExit(f"CARDS_PDF_FONT points to a missing file: {env_font}")
        return env_font
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise SystemExit(
        "No TTF font found. Set CARDS_PDF_FONT to a font with Cyrillic coverage "
        "(e.g. CARDS_PDF_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf).\n"
        "Checked: " + ", ".join(FONT_CANDIDATES)
    )


def resolve_bold_font(regular):
    env_bold = os.environ.get("CARDS_PDF_FONT_BOLD")
    if env_bold:
        if not os.path.exists(env_bold):
            raise SystemExit(f"CARDS_PDF_FONT_BOLD points to a missing file: {env_bold}")
        return env_bold
    root, ext = os.path.splitext(regular)
    candidates = [BOLD_BY_REGULAR.get(regular), root + "bd" + ext, root + "-Bold" + ext, root + " Bold" + ext]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    # Not fatal: fall back to the regular face so the PDF still renders.
    return regular


FONT_REGULAR = resolve_regular_font()
FONT_BOLD = resolve_bold_font(FONT_REGULAR)
pdfmetrics.registerFont(TTFont('Arial', FONT_REGULAR))
pdfmetrics.registerFont(TTFont('ArialBold', FONT_BOLD))

MAJOR = [
    "Шут", "Маг", "Верховная Жрица", "Императрица", "Император",
    "Иерофант", "Влюблённые", "Колесница", "Сила", "Отшельник",
    "Колесо Фортуны", "Справедливость", "Повешенный", "Смерть",
    "Умеренность", "Дьявол", "Башня", "Звезда", "Луна", "Солнце",
    "Суд", "Мир",
]
RANKS = ["Туз", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Паж", "Рыцарь", "Королева", "Король"]
SUITS = ["cups", "pents", "swords", "wands"]
SUIT_RU = {"cups": "Кубки", "pents": "Пентакли", "swords": "Мечи", "wands": "Жезлы"}
SECTION_NAMES = {
    "major": u"\u0421\u0442\u0430\u0440\u0448\u0438\u0439 \u0410\u0440\u043a\u0430\u043d",
    "cups": u"\u041a\u0443\u0431\u043a\u0438",
    "pents": u"\u041f\u0435\u043d\u0442\u0430\u043a\u043b\u0438",
    "swords": u"\u041c\u0435\u0447\u0438",
    "wands": u"\u0416\u0435\u0437\u043b\u044b",
}

pw, ph = A4
COLS = 3
ROWS = 3
MARGIN_X = 12 * mm
MARGIN_TOP = 30 * mm
MARGIN_BOTTOM = 12 * mm
GAP_X = 6 * mm
GAP_Y = 5 * mm

AVAILABLE_W = pw - 2 * MARGIN_X - (COLS - 1) * GAP_X
AVAILABLE_H = ph - MARGIN_TOP - MARGIN_BOTTOM - (ROWS - 1) * GAP_Y
CARD_W = AVAILABLE_W / COLS
CARD_H = AVAILABLE_H / ROWS
LABEL_H = 16 * mm
IMG_PAD = 3 * mm


def card_name(cid):
    if 1 <= cid <= 22:
        return MAJOR[cid - 1]
    m = cid - 23
    return f"{RANKS[m % 14]} {SUIT_RU[SUITS[m // 14]]}"


def card_file(cid):
    if 1 <= cid <= 22:
        return f"maj{cid-1:02d}.jpg"
    m = cid - 23
    return f"{SUITS[m // 14]}{m % 14 + 1:02d}.jpg"


def card_section(cid):
    if 1 <= cid <= 22:
        return "major"
    return SUITS[(cid - 23) // 14]


def draw_card(c, x, y, cid):
    fname = card_file(cid)
    fpath = os.path.join(CARDS_DIR, fname)
    name = card_name(cid)

    c.setFillColor(colors.HexColor("#1a1a2e"))
    c.rect(x, y, CARD_W, CARD_H, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#ffd700"))
    c.setLineWidth(0.5)
    c.rect(x, y, CARD_W, CARD_H, fill=0, stroke=1)

    img_x = x + IMG_PAD
    img_y = y + LABEL_H
    img_w = CARD_W - 2 * IMG_PAD
    img_h = CARD_H - LABEL_H - 3 * mm

    if os.path.exists(fpath):
        try:
            c.saveState()
            p = c.beginPath()
            p.rect(img_x, img_y, img_w, img_h)
            c.clipPath(p, stroke=0)
            c.drawImage(fpath, img_x, img_y, img_w, img_h, preserveAspectRatio=True, anchor='c')
            c.restoreState()
        except Exception:
            c.setFillColor(colors.red)
            c.setFont("Arial", 8)
            c.drawCentredString(x + CARD_W / 2, y + CARD_H / 2, "Error")
    else:
        c.setFillColor(colors.HexColor("#666666"))
        c.setFont("Arial", 7)
        c.drawCentredString(x + CARD_W / 2, y + CARD_H / 2, fname)

    label_y = y + 2 * mm
    c.setFillColor(colors.HexColor("#ffd700"))
    c.setFont("ArialBold", 8)
    c.drawCentredString(x + CARD_W / 2, label_y + 8 * mm, f"#{cid}")

    c.setFillColor(colors.HexColor("#e0e0e0"))
    c.setFont("Arial", 7)
    lines = name.split()
    if len(lines) > 1:
        c.drawCentredString(x + CARD_W / 2, label_y + 4 * mm, " ".join(lines[:-1]))
        c.drawCentredString(x + CARD_W / 2, label_y, lines[-1])
    else:
        c.drawCentredString(x + CARD_W / 2, label_y + 2 * mm, name)


def new_page(c):
    c.showPage()
    c.setFillColor(colors.HexColor("#1a1a2e"))
    c.rect(0, 0, pw, ph, fill=1, stroke=0)


def draw_section_title(c, title, page_y):
    c.setFillColor(colors.HexColor("#aaaaaa"))
    c.setFont("ArialBold", 11)
    c.drawString(MARGIN_X, page_y + 5 * mm, title)
    return page_y - 10 * mm


sections = [
    ("major", list(range(1, 23))),
    ("cups", list(range(23, 37))),
    ("pents", list(range(37, 51))),
    ("swords", list(range(51, 65))),
    ("wands", list(range(65, 79))),
]

c = canvas.Canvas(OUTPUT, pagesize=A4)
c.setFillColor(colors.HexColor("#1a1a2e"))
c.rect(0, 0, pw, ph, fill=1, stroke=0)
c.setFillColor(colors.HexColor("#ffd700"))
c.setFont("ArialBold", 18)
c.drawCentredString(pw / 2, ph - 10 * mm, u"\u041a\u043e\u043b\u043e\u0434\u0430 \u0422\u0430\u0440\u043e \u2014 Morlana")
first_page = True

for section_key, card_ids in sections:
    if not first_page:
        new_page(c)
    first_page = False

    page_y = ph - MARGIN_TOP
    page_y = draw_section_title(c, SECTION_NAMES[section_key], page_y)

    card_idx = 0
    for cid in card_ids:
        row = card_idx // COLS
        col = card_idx % COLS

        if row >= ROWS:
            new_page(c)
            page_y = ph - MARGIN_TOP
            page_y = draw_section_title(c, SECTION_NAMES[section_key] + u" (\u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435)", page_y)
            card_idx = 0
            row = 0
            col = 0

        x = MARGIN_X + col * (CARD_W + GAP_X)
        y = page_y - (row + 1) * CARD_H - row * GAP_Y
        draw_card(c, x, y, cid)

        card_idx += 1

c.save()
print(f"PDF saved: {OUTPUT}")
