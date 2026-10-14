#!/usr/bin/env python3
"""为经典文献抽取代表性图：下载 arXiv PDF，取前 4 页中最大的嵌入图，存 images/<id>.jpg。
只处理 url 为 arxiv.org 的条目；结果写回 data/classics.json 的 figure 字段。"""
import io
import json
import os
import time
import urllib.request

import pymupdf  # PyMuPDF

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
IMG_DIR = os.path.join(ROOT, "images")
CLASSICS = os.path.join(ROOT, "data", "classics.json")

MIN_W, MIN_H = 300, 200


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "manipdaily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def best_figure(pdf_bytes: bytes):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    best = None
    for pno in range(min(4, len(doc))):
        for img in doc[pno].get_images(full=True):
            xref = img[0]
            try:
                pix = pymupdf.Pixmap(doc, xref)
            except Exception:
                continue
            if pix.width < MIN_W or pix.height < MIN_H:
                continue
            area = pix.width * pix.height
            if best is None or area > best[0]:
                best = (area, pix)
        if best and best[0] > 800 * 500:   # 已经够大，提前收工
            break
    return best[1] if best else None


def caption_fallback(doc):
    """无嵌入位图时的兜底：找 'Figure 1' 标题，裁剪其上方的图区渲染成位图。"""
    for pno in range(min(4, len(doc))):
        page = doc[pno]
        rects = page.search_for("Figure 1") or page.search_for("Fig. 1")
        if not rects:
            continue
        cap = rects[0]
        h = min(400, cap.y0)
        if h < 120:
            continue
        clip = pymupdf.Rect(28, max(0, cap.y0 - h), page.rect.width - 28, cap.y0 - 2)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip)
        return pix
    return None


def main() -> None:
    with open(CLASSICS, encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(IMG_DIR, exist_ok=True)
    done = skipped = 0
    for p in data["papers"]:
        if "arxiv.org/abs/" not in p["url"]:
            skipped += 1
            continue
        ax_id = p["url"].rstrip("/").split("/abs/")[-1]
        out = os.path.join(IMG_DIR, f"{p['id']}.jpg")
        if os.path.exists(out):
            p["figure"] = f"images/{p['id']}.jpg"
            done += 1
            continue
        try:
            pdf = fetch(f"https://arxiv.org/pdf/{ax_id}")
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            pix = best_figure(pdf) or caption_fallback(doc)
            doc.close()
            if pix is None:
                print(f"[skip] {p['id']}: no figure found")
                skipped += 1
                continue
            if pix.colorspace and pix.colorspace.n > 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            pix.save(out, jpg_quality=82)
            p["figure"] = f"images/{p['id']}.jpg"
            done += 1
            print(f"[ok] {p['id']} <- {ax_id}")
        except Exception as exc:
            print(f"[warn] {p['id']}: {exc}")
            skipped += 1
        time.sleep(2)
    with open(CLASSICS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"done: {done} figures, {skipped} skipped")


if __name__ == "__main__":
    main()
