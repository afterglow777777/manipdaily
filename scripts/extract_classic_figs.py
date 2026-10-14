#!/usr/bin/env python3
"""为经典文献抽取代表性图 v2：定位 'Figure 1' 标题，截图其相邻的图区。
策略（每篇重抽，覆盖旧图）：
  1) 在前 5 页搜 'Figure 1' / 'Fig. 1' 等标题；
  2) 收集标题上方的位图/矢量图块，求并集后截图（含少量边距）；
  3) 上方没有图块则看下方；仍无则裁标题上方的整条横带。
双栏论文会截到整条横带，可接受。输出 images/<id>.jpg。"""
import json
import os
import time
import urllib.request

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
IMG_DIR = os.path.join(ROOT, "images")
CLASSICS = os.path.join(ROOT, "data", "classics.json")

CAPTIONS = ["Figure 1", "Fig. 1", "Figure1", "Fig 1"]


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "manipdaily/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def graphic_rects(page, above_of=None, below_of=None):
    """收集页面上位图/矢量图块的 bbox；可用 above_of/below_of 过滤。"""
    rects = []
    for img in page.get_images(full=True):
        try:
            rects += page.get_image_rects(img[0])
        except Exception:
            pass
    try:
        for d in page.get_drawings():
            r = d.get("rect")
            if r and r.width > 20 and r.height > 10:
                rects.append(r)
    except Exception:
        pass
    out = []
    for r in rects:
        if above_of is not None and r.y1 > above_of.y0 + 5:
            continue
        if below_of is not None and r.y0 < below_of.y1 - 5:
            continue
        if r.width >= 100 and r.height >= 50:
            out.append(r)
    return out


def caption_rect(page):
    for cap in CAPTIONS:
        found = page.search_for(cap)
        if found:
            return sorted(found, key=lambda r: r.y0)[0]
    return None


def shot_for(doc):
    for pno in range(min(5, len(doc))):
        page = doc[pno]
        cap = caption_rect(page)
        if cap is None:
            continue
        pw = page.rect.width
        ups = graphic_rects(page, above_of=cap)
        if ups:
            u = ups[0]
            for r in ups[1:]:
                u |= r
            clip = pymupdf.Rect(max(28, u.x0 - 6), max(0, u.y0 - 6),
                                min(pw - 28, u.x1 + 6), min(cap.y0 - 2, u.y1 + 6))
            if clip.width > 150 and clip.height > 80:
                return page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip)
        downs = graphic_rects(page, below_of=cap)
        downs = [r for r in downs if r.y0 < cap.y1 + 380]
        if downs:
            d = downs[0]
            for r in downs[1:]:
                d |= r
            clip = pymupdf.Rect(max(28, d.x0 - 6), max(0, d.y0 - 6),
                                min(pw - 28, d.x1 + 6), min(page.rect.height - 28, d.y1 + 6))
            if clip.width > 150 and clip.height > 80:
                return page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip)
        h = min(400, cap.y0)
        if h >= 120:
            clip = pymupdf.Rect(28, max(0, cap.y0 - h), pw - 28, cap.y0 - 2)
            return page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip)
    return None


def main() -> None:
    with open(CLASSICS, encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(IMG_DIR, exist_ok=True)
    done = skipped = 0
    for p in data["papers"]:
        if "arxiv.org/abs/" not in p["url"]:
            continue
        ax_id = p["url"].rstrip("/").split("/abs/")[-1]
        out = os.path.join(IMG_DIR, f"{p['id']}.jpg")
        if os.path.exists(out):
            os.remove(out)
        try:
            pdf = fetch(f"https://arxiv.org/pdf/{ax_id}")
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            pix = shot_for(doc)
            doc.close()
            if pix is None:
                p.pop("figure", None)
                print(f"[skip] {p['id']}")
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
