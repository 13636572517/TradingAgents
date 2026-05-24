#!/usr/bin/env python3
"""Generate app icons from a source PNG image.

Usage:
    python scripts/gen_icons.py <source_image.png>

Outputs:
    web/public/icons/apple-touch-icon.png  (180x180)
    web/public/icons/icon-180.png          (180x180)
    web/public/icons/icon-192.png          (192x192)
    web/public/icons/icon-512.png          (512x512)
    web/public/favicon.png                 (32x32, for browser tab)

After running, web/index.html already references /favicon.png and /icons/*.png.
"""
import sys
from pathlib import Path


def make_icons(src_path: str) -> None:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required. Install it: pip install Pillow")
        sys.exit(1)

    src = Path(src_path)
    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)

    root = Path(__file__).parent.parent
    icons_dir = root / "web" / "public" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(src).convert("RGBA")

    # Center-crop to square (removes letterbox / watermark edges)
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top  = (h - side) // 2
    img  = img.crop((left, top, left + side, top + side))

    sizes = {
        "apple-touch-icon.png": 180,
        "icon-180.png":         180,
        "icon-192.png":         192,
        "icon-512.png":         512,
    }

    for filename, px in sizes.items():
        out = icons_dir / filename
        img.resize((px, px), Image.LANCZOS).save(str(out), "PNG", optimize=True)
        print(f"  ✓ {out.relative_to(root)}")

    favicon = root / "web" / "public" / "favicon.png"
    img.resize((32, 32), Image.LANCZOS).save(str(favicon), "PNG", optimize=True)
    print(f"  ✓ {favicon.relative_to(root)}")

    print("\n✅ Icons generated. Rebuild the frontend to apply changes (cd web && npm run build).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    make_icons(sys.argv[1])
