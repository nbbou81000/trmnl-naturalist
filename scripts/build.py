#!/usr/bin/env python3
"""
build.py — produit le corpus d'images final.

Une seule résolution stockée (1872x1404, celle du TRMNL X) : la mise en page
étant proportionnelle, l'OG reçoit la même image réduite par le moteur de rendu.
"""
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import ImageStat  # noqa: E402
from render import DEFAULT, compose, fetch, is_photograph, prepare, tonal, usable  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_IMG = os.path.join(ROOT, "docs", "img")
MANIFEST = os.path.join(ROOT, "docs", "manifest.json")
COUNT = os.path.join(ROOT, "docs", "count.json")

PER_RUN = int(os.environ.get("PER_RUN", "500"))
CHECKPOINT = int(os.environ.get("CHECKPOINT", "100"))
TIME_BUDGET = int(os.environ.get("TIME_BUDGET", "8400"))
DELAY = float(os.environ.get("DELAY", "0.4"))
ONLY = [v.strip().lower() for v in os.environ.get("ONLY", "").split(",") if v.strip()]


def final_check(art, prof):
    """
    Juge la planche APRÈS traitement, pas avant.

    Certaines gravures sont si pâles à la source que le rendu ne laisse
    qu'une page presque blanche — le filtre d'entrée les laissait passer
    parce que l'original contenait bien de l'encre.
    """
    probe = tonal(art, 400, 400, prof).convert("L")
    mean = ImageStat.Stat(probe).mean[0]
    ink = (255 - mean) / 255.0
    return 0.035 <= ink <= 0.72


def save_manifest(items):
    json.dump({"count": len(items), "generated_at": int(time.time()), "items": items},
              open(MANIFEST, "w"), indent=1, ensure_ascii=False)
    json.dump({"count": len(items)}, open(COUNT, "w"))


def checkpoint(items):
    """Un job interrompu perd tout ce qui n'a pas été poussé."""
    save_manifest(items)
    try:
        subprocess.run(["git", "add", "docs"], check=True, capture_output=True)
        if subprocess.run(["git", "diff", "--staged", "--quiet"]).returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", f"images: {len(items)} planches (checkpoint)"],
                       check=True, capture_output=True)
        for _ in range(3):
            try:
                subprocess.run(["git", "push"], check=True, capture_output=True)
                print(f"  ✓ checkpoint poussé à {len(items)} planches")
                return
            except subprocess.CalledProcessError:
                subprocess.run(["git", "pull", "--rebase", "--autostash"],
                               check=True, capture_output=True)
        print("  (checkpoint non poussé après 3 tentatives)")
    except Exception as e:
        print(f"  (checkpoint ignoré : {e})")


def main(corpus_path, cap):
    corpus = json.load(open(corpus_path))
    works = {w["label"]: w.get("profile", DEFAULT) for w in json.load(open(os.path.join(ROOT, "works.json")))}
    os.makedirs(OUT_IMG, exist_ok=True)

    done = {}
    if os.path.exists(MANIFEST):
        done = {e["file"]: e for e in json.load(open(MANIFEST))["items"]}

    if ONLY:
        corpus = [p for p in corpus if p["work"].lower() in ONLY]
        if not corpus:
            raise SystemExit("Aucune planche pour ONLY.")
        print(f"Passe restreinte à : {', '.join(ONLY)} — {len(corpus)} candidates")

    # Tourniquet par ouvrage : sans lui, Curtis's Botanical Magazine et ses
    # 2658 planches écraseraient les ouvrages plus petits dans la rotation.
    random.seed(1789)
    buckets = {}
    for item in sorted(corpus, key=lambda p: p["file"]):
        buckets.setdefault(item["work"], []).append(item)
    for b in buckets.values():
        random.shuffle(b)
    order = sorted(buckets, key=lambda k: len(buckets[k]))
    pool = []
    while any(buckets[k] for k in order):
        for k in order:
            if buckets[k]:
                pool.append(buckets[k].pop())

    items = list(done.values())
    made = skipped = 0
    started = time.time()

    for p in pool:
        if len(items) >= cap or made >= PER_RUN or time.time() - started > TIME_BUDGET:
            break
        if p["file"] in done:
            continue

        prof = works.get(p["work"], DEFAULT)
        idx = len(items)
        rel = f"img/{idx}.png"
        try:
            raw = fetch(p["url"])
            if is_photograph(raw):
                skipped += 1
                continue
            art = prepare(raw, prof)
            if usable(art) is None or not final_check(art, prof):
                skipped += 1
                continue
            compose(p, art, os.path.join(ROOT, "docs", rel), target="x", prof=prof)
        except Exception as e:
            print(f"  {p['title'][:40]} ignorée : {type(e).__name__}")
            skipped += 1
            continue

        items.append({"i": idx, "file": p["file"], "title": p["title"], "work": p["work"],
                      "author": p.get("author", ""), "subject": p.get("subject", ""),
                      "date": p.get("date", ""), "image": rel})
        made += 1
        if len(items) % 25 == 0:
            print(f"  {len(items)} planches · {skipped} écartées")
        if made % CHECKPOINT == 0:
            checkpoint(items)
        time.sleep(DELAY)

    save_manifest(items)
    total = sum(os.path.getsize(os.path.join(ROOT, "docs", i["image"])) for i in items)
    print(f"\n{len(items)} planches · {skipped} écartées · {total / 1048576:.1f} Mo")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 12000)
