#!/usr/bin/env python3
"""Render PDF pages to PNG images (for the visual check and for reading scanned pages).

Usage:
    python3 render_pages.py --out <review-output> --id Cohen2023 --pages 1 5
    python3 render_pages.py --out <review-output> --id Cohen2023 --pages all
    python3 render_pages.py --out <review-output> --visual-sample      # every article's sample pages

The PDF path is read from 01_text/manifest.json. Images go to 02_pdf_check/pages/<ID>_p<N>.png.
Prints JSON: {"images": [{"id": ..., "page": N, "path": ...}, ...]}
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    print(json.dumps({"error": "pdfplumber is not installed. Run setup_env.py --install"}))
    sys.exit(1)


def render(rec, pages, out_dir, dpi):
    done = []
    with pdfplumber.open(rec["path"]) as pdf:
        n = len(pdf.pages)
        if pages == "all":
            pages = list(range(1, n + 1))
        for p in pages:
            if not 1 <= p <= n:
                continue
            target = out_dir / f'{rec["id"]}_p{p}.png'
            if not target.exists():
                pdf.pages[p - 1].to_image(resolution=dpi).save(str(target), format="PNG")
            done.append({"id": rec["id"], "page": p, "path": str(target)})
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--id")
    ap.add_argument("--pages", nargs="*")
    ap.add_argument("--visual-sample", action="store_true")
    ap.add_argument("--dpi", type=int, default=110)
    args = ap.parse_args()

    out = Path(args.out).resolve()
    manifest = json.loads((out / "01_text" / "manifest.json").read_text(encoding="utf-8"))
    img_dir = out / "02_pdf_check" / "pages"
    img_dir.mkdir(parents=True, exist_ok=True)

    images = []
    if args.visual_sample:
        for rec in manifest:
            if rec.get("status") == "fail":
                continue
            try:
                images += render(rec, rec.get("visual_check_pages") or [1], img_dir, args.dpi)
            except Exception as e:
                images.append({"id": rec["id"], "error": str(e)[:200]})
    else:
        rec = next((r for r in manifest if r["id"] == args.id), None)
        if rec is None:
            print(json.dumps({"error": f"unknown id {args.id}"}))
            return 1
        pages = "all" if (not args.pages or args.pages == ["all"]) else [int(p) for p in args.pages]
        images = render(rec, pages, img_dir, args.dpi)
    print(json.dumps({"images": images}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
