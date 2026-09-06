#!/usr/bin/env python3
"""
collect.py — constitue le corpus de planches naturalistes depuis Wikimedia Commons.

Approche par ouvrages curatés plutôt que par recherche plein texte. Chercher
"insect" dans les métadonnées BHL remonte surtout des rapports phytosanitaires
du ministère de l'Agriculture : cartes de répartition et pages de texte.
Parcourir la catégorie d'un ouvrage connu pour ses planches donne au contraire
un contenu déjà trié par les contributeurs de Commons.

Reprend là où il s'est arrêté (state.json) pour étaler la collecte.
"""
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKS = os.path.join(ROOT, "works.json")
CORPUS = os.path.join(ROOT, "corpus.json")
STATE = os.path.join(ROOT, "state.json")

# Commons renvoie un 429 immédiat à tout User-Agent générique.
# Il doit identifier le projet et fournir un moyen de contact.
UA = {
    "User-Agent": "TrmnlNaturalistPlates/1.0 "
    "(https://github.com/nbbou81000/trmnl-naturalist; nb.bouteiller@gmail.com) python-urllib"
}
API = "https://commons.wikimedia.org/w/api.php?"
DEPTH = int(os.environ.get("DEPTH", "2"))
PER_RUN = int(os.environ.get("PER_RUN", "4000"))
DELAY = float(os.environ.get("DELAY", "0.6"))
ONLY = [v.strip().lower() for v in os.environ.get("ONLY", "").split(",") if v.strip()]

# Pages de titre, portraits d'auteur, reliures : présents dans les catégories
# d'ouvrages et sans intérêt une fois à l'écran.
SKIP = (
    "title page", "titlepage", "frontispiece", "cover", "binding", "spine",
    "portrait", "bookplate", "index", "contents", "colophon", "map",
)


def api(params, tries=3):
    params.setdefault("format", "json")
    url = API + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def walk(category, depth):
    """Renvoie les titres de fichiers d'une catégorie et de ses sous-catégories."""
    files, seen, queue = [], set(), [(category, 0)]
    while queue:
        cat, d = queue.pop(0)
        if cat in seen:
            continue
        seen.add(cat)
        cont = {}
        while True:
            p = {"action": "query", "list": "categorymembers",
                 "cmtitle": "Category:" + cat, "cmlimit": "500"}
            p.update(cont)
            j = api(p)
            for m in j.get("query", {}).get("categorymembers", []):
                if m["ns"] == 6:
                    files.append(m["title"])
                elif m["ns"] == 14 and d < depth:
                    queue.append((m["title"].replace("Category:", ""), d + 1))
            cont = j.get("continue", {})
            time.sleep(DELAY)
            if not cont:
                break
    return files, len(seen)


def image_urls(titles, width=1400):
    """Résout les URL de vignettes par lots de 25, la limite de l'API."""
    out = {}
    for i in range(0, len(titles), 25):
        j = api({"action": "query", "titles": "|".join(titles[i:i + 25]),
                 "prop": "imageinfo", "iiprop": "url|size|extmetadata",
                 "iiurlwidth": str(width)})
        for p in j.get("query", {}).get("pages", {}).values():
            info = (p.get("imageinfo") or [{}])[0]
            if info.get("thumburl"):
                meta = info.get("extmetadata", {})
                out[p["title"]] = {
                    "url": info["thumburl"],
                    "date": (meta.get("DateTimeOriginal", {}).get("value", "") or "")[:60],
                }
        time.sleep(DELAY)
    return out


def clean_title(filename):
    """'File:Brehms Tierleben - Tafel 12 xyz.jpg' -> 'Brehms Tierleben - Tafel 12'."""
    t = filename.replace("File:", "").rsplit(".", 1)[0]
    t = t.replace("_", " ")
    for junk in (" LCCN", " BHL", " (page", " - page"):
        if junk in t:
            t = t.split(junk)[0]
    return " ".join(t.split()).strip(" -–,")


def main():
    works = json.load(open(WORKS))
    if ONLY:
        works = [w for w in works if w["category"].lower() in ONLY or w["label"].lower() in ONLY]
        if not works:
            raise SystemExit("Aucun ouvrage ne correspond à ONLY.")

    corpus = json.load(open(CORPUS)) if os.path.exists(CORPUS) else []
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    seen = {c["file"] for c in corpus}
    added = 0

    for w in works:
        if state.get(w["category"]) == "complete":
            continue
        if added >= PER_RUN:
            print(f"Plafond de {PER_RUN} planches atteint pour cette passe.")
            break

        print(f"\n{w['label']} ({w['subject']})")
        try:
            titles, ncat = walk(w["category"], DEPTH)
        except Exception as e:
            print(f"  échec : {e}")
            continue
        titles = [t for t in titles if not any(s in t.lower() for s in SKIP)]
        titles = [t for t in titles if t not in seen]
        print(f"  {ncat} catégories · {len(titles)} fichiers nouveaux")

        for i in range(0, len(titles), 25):
            if added >= PER_RUN:
                break
            batch = titles[i:i + 25]
            try:
                urls = image_urls(batch)
            except Exception as e:
                print(f"  lot ignoré : {e}")
                continue
            for t, info in urls.items():
                if t in seen:
                    continue
                seen.add(t)
                corpus.append({
                    "file": t,
                    "title": clean_title(t),
                    "work": w["label"],
                    "subject": w["subject"],
                    "author": w.get("author", ""),
                    "date": info["date"],
                    "url": info["url"],
                })
                added += 1

        state[w["category"]] = "complete" if added < PER_RUN else state.get(w["category"], 0)
        json.dump(corpus, open(CORPUS, "w"), indent=1, ensure_ascii=False)
        json.dump(state, open(STATE, "w"), indent=1, ensure_ascii=False)
        print(f"  corpus : {len(corpus)} planches")

    done = sum(1 for v in state.values() if v == "complete")
    print(f"\n{added} planches ajoutées · corpus {len(corpus)} · {done}/{len(works)} ouvrages épuisés")


if __name__ == "__main__":
    main()
