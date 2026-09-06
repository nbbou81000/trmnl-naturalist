#!/usr/bin/env python3
"""
render.py — compose une planche naturaliste en écran e-ink.

Mode de rendu inverse de celui des dessins de brevet. Les planches naturalistes
sont tonales : aquarelle, lithographie coloriée, gravure ombrée. Une simple
quantification en 4 niveaux les écrase en aplats et fait disparaître les
nervures. On applique donc autocontraste, léger renfort, puis tramage
Floyd-Steinberg — exactement ce qu'il fallait bannir pour le trait pur.
"""
import io
import urllib.request

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps, ImageStat

FB = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
UA = {
    "User-Agent": "TrmnlNaturalistPlates/1.0 "
    "(https://github.com/nbbou81000/trmnl-naturalist; nb.bouteiller@gmail.com) python-urllib"
}

TARGETS = {
    "og": {"w": 800, "h": 480, "scale": 1.0},
    "x": {"w": 1872, "h": 1404, "scale": 2.3},
}
TEXT_X = 40
ART_X = 300


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return Image.open(io.BytesIO(r.read()))


def trim(im):
    """Retire les marges uniformes du scan, claires ou sombres."""
    g = im.convert("L")
    bg = ImageStat.Stat(g).mean[0]
    ref = ImageOps.invert(g) if bg > 128 else g
    bb = ref.point(lambda v: 255 if v > 28 else 0).getbbox()
    return im.crop(bb) if bb else im


# Réglage par défaut, surchargé ouvrage par ouvrage dans works.json.
# Il n'existe pas de prétraitement unique : un scan à fond noir et une gravure
# pâle demandent des traitements opposés, et chaque ouvrage est homogène en
# interne. Quinze réglages faits une fois valent mieux qu'un algorithme qui
# tente de tout deviner.
DEFAULT = {"bg": "light", "boost": 1.2, "crop": True, "dither": True}


def clean_scan(im, prof=None):
    """
    Neutralise le papier avant tout traitement.

    Sur un scan d'ouvrage ancien, le grain du papier couvre toute la page :
    le tramage le transforme en bruit gris uniforme, et les profils d'encre
    détectent de l'encre partout, ce qui rendait le recadrage inopérant.
    On étire donc les niveaux entre le fond réel (mesuré sur les bords) et
    les noirs les plus profonds, puis on force le fond en blanc pur.
    """
    prof = {**DEFAULT, **(prof or {})}
    g = im.convert("L")

    # Fond sombre : la mesure du papier sur les bords n'a aucun sens, elle
    # inverse la logique et détruit la planche. On se contente d'un autocontraste.
    if prof["bg"] == "dark":
        return ImageOps.autocontrast(g, cutoff=1)

    w, h = g.size
    bw, bh = max(1, w // 25), max(1, h // 25)
    border = (
        list(g.crop((0, 0, w, bh)).get_flattened_data())
        + list(g.crop((0, h - bh, w, h)).get_flattened_data())
        + list(g.crop((0, 0, bw, h)).get_flattened_data())
        + list(g.crop((w - bw, 0, w, h)).get_flattened_data())
    )
    border.sort()
    paper = border[int(len(border) * 0.55)]          # niveau médian du papier
    hist = g.histogram()
    total = sum(hist)
    acc = 0
    black = 0
    for v, n in enumerate(hist):                      # 2e centile : les vrais noirs
        acc += n
        if acc > total * 0.02:
            black = v
            break
    lo, hi = black, max(black + 25, int(paper * 0.94))
    scale = 255.0 / (hi - lo)
    return g.point(lambda v: 255 if v >= hi else max(0, int((v - lo) * scale)))


def inner_crop(im, prof=None, margin=0.012):
    """
    Isole la gravure de sa page.

    trim() ne retire que les marges uniformes du scan ; il laisse le filet
    imprimé, la légende et le blanc de la page, si bien que l'illustration
    n'occupait que la moitié de la surface. On analyse ici les profils d'encre
    par ligne et par colonne, et on recadre sur la zone réellement dessinée.
    """
    g = clean_scan(im, prof)
    w, h = g.size
    mask = g.point(lambda v: 255 if v < 200 else 0)

    cols = [sum(mask.crop((x, 0, x + 1, h)).get_flattened_data()) / 255 for x in range(0, w, max(1, w // 400))]
    rows = [sum(mask.crop((0, y, w, y + 1)).get_flattened_data()) / 255 for y in range(0, h, max(1, h // 400))]
    if not cols or not rows:
        return im

    def span(prof, size, thresh_ratio=0.06):
        peak = max(prof) or 1
        t = peak * thresh_ratio
        idx = [i for i, v in enumerate(prof) if v > t]
        if not idx:
            return 0, size
        step = size / len(prof)
        return int(idx[0] * step), int((idx[-1] + 1) * step)

    x0, x1 = span(cols, w)
    y0, y1 = span(rows, h)
    mx, my = int(w * margin), int(h * margin)
    x0, y0 = max(0, x0 - mx), max(0, y0 - my)
    x1, y1 = min(w, x1 + mx), min(h, y1 + my)
    if x1 - x0 < w * 0.15 or y1 - y0 < h * 0.15:
        return im
    return im.crop((x0, y0, x1, y1))


def is_photograph(im):
    """
    Photos de reliures et de couvertures : couleurs saturées et peu de détail
    fin, à l'inverse d'une gravure. Elles se glissent dans les catégories
    d'ouvrages sans que leur nom de fichier le signale.
    """
    if im.mode not in ("RGB", "RGBA"):
        return False
    small = im.convert("RGB").resize((80, 80))
    sat = 0
    for r, g, b in small.get_flattened_data():
        mx, mn = max(r, g, b), min(r, g, b)
        if mx and (mx - mn) / mx > 0.35:
            sat += 1
    return sat / 6400.0 > 0.30


def usable(im):
    """
    Écarte les pages sans illustration et les scans ratés.
    Renvoie None si la planche ne vaut pas la peine d'être rendue.
    """
    g = ImageOps.autocontrast(im.convert("L"), cutoff=1)
    w, h = g.size
    if w < 300 or h < 300:
        return None
    ratio = w / h
    if ratio < 0.32 or ratio > 3.2:
        return None

    small = g.resize((120, 120))
    ink = sum(1 for p in small.get_flattened_data() if p < 140) / 14400.0
    if ink < 0.03 or ink > 0.60:
        return None

    # Une page de texte a des bandes régulières : peu d'écart entre les lignes.
    band = max(1, h // 40)
    rows = [ImageStat.Stat(g.crop((0, y, w, y + band))).mean[0] for y in range(0, h - band, band)]
    swing = max(rows) - min(rows) if rows else 0
    if swing < 20 and ink < 0.14:
        return None

    return round(swing / 255.0 + min(ink, 0.35), 3)


def tonal(im, box_w, box_h, prof=None):
    """Fond neutralisé, mise à l'échelle, puis tramage des demi-teintes."""
    prof = {**DEFAULT, **(prof or {})}
    g = clean_scan(im, prof)
    r = min(box_w / g.width, box_h / g.height)
    g = g.resize((max(1, int(g.width * r)), max(1, int(g.height * r))), Image.LANCZOS)
    g = ImageEnhance.Contrast(g).enhance(prof["boost"])
    if not prof["dither"]:
        return g.point(lambda v: 255 if v > 150 else 0)
    return g.convert("1", dither=Image.FLOYDSTEINBERG)


def fit_text(draw, text, font_path, max_size, min_size, box_w, max_lines=3):
    """Réduit puis répartit sur plusieurs lignes. Aucune coupe brutale."""
    words = text.split()
    for size in range(max_size, min_size - 1, -2):
        font = ImageFont.truetype(font_path, size)
        if draw.textlength(text, font=font) <= box_w:
            return font, [text]
        for n in range(1, len(words)):
            lines = [" ".join(words[:n]), " ".join(words[n:])]
            if all(draw.textlength(l, font=font) <= box_w for l in lines):
                return font, lines
    font = ImageFont.truetype(font_path, min_size)
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= box_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return font, lines


def prepare(im, prof=None):
    """Chaîne complète : détourage, recadrage intérieur si l'ouvrage le permet."""
    prof = {**DEFAULT, **(prof or {})}
    im = trim(im)
    return inner_crop(im, prof) if prof["crop"] else im


def compose(plate, art, out, target="x", prof=None):
    t = TARGETS[target]
    W, H, k = t["w"], t["h"], t["scale"]
    canvas = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(canvas)

    art_x = int(ART_X * k)
    art_w = W - art_x - int(30 * k)
    a = tonal(art, art_w, H - int(60 * k), prof)
    canvas.paste(a, (art_x + (art_w - a.width) // 2, (H - a.height) // 2))

    x0 = int(TEXT_X * k)
    text_w = art_x - x0 - int(24 * k)

    title_font, lines = fit_text(d, plate["title"], FB, int(28 * k), int(15 * k), text_w)
    y = int(58 * k)
    for line in lines:
        d.text((x0, y), line, font=title_font, fill=0)
        y += title_font.size + int(4 * k)

    rule = y + int(12 * k)
    d.line([(x0, rule), (x0 + int(190 * k), rule)], fill=0, width=max(2, int(2 * k)))

    y = rule + int(20 * k)
    small = ImageFont.truetype(FR, int(19 * k))
    for line in [plate.get("author", ""), plate.get("work", ""), plate.get("date", "")]:
        if not line:
            continue
        f2, ls = fit_text(d, line, FR, int(19 * k), int(14 * k), text_w, max_lines=2)
        for l in ls:
            d.text((x0, y), l, font=f2, fill=0)
            y += f2.size + int(3 * k)

    d.text((x0, H - int(56 * k)), plate.get("subject", "").title(), font=small, fill=0)
    d.text((x0, H - int(32 * k)), "Wikimedia Commons · public domain", font=small, fill=0)

    canvas.save(out, optimize=True)
    return out
