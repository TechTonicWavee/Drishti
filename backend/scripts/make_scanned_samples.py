#!/usr/bin/env python
"""Generate synthetic 'scanned' inspection reports for testing the vision path.

Renders short inspection notes as images and then degrades them the way a real
office scanner does: a slight rotation off-square, sensor noise, a little blur,
and uneven paper tone. Clean renders would make the preprocessing step look
unnecessary and would not resemble anything the plant actually produces.

Each note contains specific identifiers — vessel tags, dates, measurements —
so that a test can tell a genuine extraction from a plausible-sounding
hallucination.

Run:  .venv/bin/python scripts/make_scanned_samples.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "sample_docs" / "scanned"

# macOS system fonts, with a fallback to PIL's bitmap default.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

REPORTS: list[tuple[str, list[str]]] = [
    (
        "vessel_v204_inspection.png",
        [
            "MRPL  —  EQUIPMENT INSPECTION NOTE        (SAMPLE / FICTIONAL)",
            "",
            "Equipment tag : V-204   Pressure Vessel, Overheads Separator",
            "Unit          : Crude Distillation Unit 2",
            "Date          : 14 March 2026",
            "Inspector     : R. Menon  (Badge 4471)",
            "",
            "FINDINGS",
            "",
            "1. Minor external corrosion noted at the north flange face.",
            "   Estimated depth 0.6 mm. No through-wall loss.",
            "",
            "2. Insulation cladding damaged on the south side, approx.",
            "   300 mm section. Water ingress likely.",
            "",
            "3. Support saddle bolts show surface rust. Torque checked",
            "   and found acceptable.",
            "",
            "4. Wall thickness at CML-07 measured 11.4 mm against a",
            "   minimum required 9.5 mm.",
            "",
            "RECOMMENDATION",
            "Re-inspect within 90 days. Repair cladding before monsoon.",
        ],
    ),
    (
        "pump_p101b_inspection.png",
        [
            "MRPL  —  ROTATING EQUIPMENT NOTE          (SAMPLE / FICTIONAL)",
            "",
            "Equipment tag : P-101B   Centrifugal Pump, Crude Charge",
            "Unit          : Crude Distillation Unit 1",
            "Date          : 02 April 2026",
            "Inspector     : S. Kulkarni  (Badge 2298)",
            "",
            "FINDINGS",
            "",
            "1. Mechanical seal leak observed at the outboard end.",
            "   Approximately 4 drops per minute.",
            "",
            "2. Bearing housing vibration measured 7.8 mm/s RMS,",
            "   above the 4.5 mm/s alarm threshold.",
            "",
            "3. Coupling guard fastener missing on the drive side.",
            "",
            "4. Baseplate grout cracked at two corners.",
            "",
            "RECOMMENDATION",
            "Switch to P-101A. Schedule seal replacement within 7 days.",
        ],
    ),
    (
        "exchanger_e305_inspection.png",
        [
            "MRPL  —  HEAT EXCHANGER INSPECTION        (SAMPLE / FICTIONAL)",
            "",
            "Equipment tag : E-305   Shell and Tube Exchanger",
            "Unit          : Fluid Catalytic Cracking Unit",
            "Date          : 21 April 2026",
            "Inspector     : A. Fernandes  (Badge 5013)",
            "",
            "FINDINGS",
            "",
            "1. Tube-side fouling heavy. Pressure drop 1.9 bar against",
            "   a design 0.8 bar.",
            "",
            "2. Three tubes plugged previously; plugs intact.",
            "",
            "3. Shell-side gasket weeping at the channel head joint.",
            "",
            "4. Outlet temperature 12 degrees C above design, consistent",
            "   with reduced heat transfer.",
            "",
            "RECOMMENDATION",
            "Chemical clean at next opportunity. Replace channel gasket.",
        ],
    ),
]


def _font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _render(lines: list[str], seed: int) -> Image.Image:
    rng = random.Random(seed)
    width, height = 1240, 1000
    image = Image.new("L", (width, height), color=252)
    draw = ImageDraw.Draw(image)
    font = _font(21)

    y = 70
    for line in lines:
        # Nudge each line a pixel or two: real scans are never perfectly
        # aligned, and OCR-ish models should cope with it.
        draw.text((90 + rng.randint(-1, 1), y), line, fill=38, font=font)
        y += 33

    return image


def _degrade(image: Image.Image, seed: int) -> Image.Image:
    rng = random.Random(seed)
    array = np.array(image, dtype=np.float32)

    # Uneven paper tone: a soft gradient, as though the page did not lie flat.
    h, w = array.shape
    gradient = np.linspace(0, rng.uniform(6, 14), w, dtype=np.float32)
    array -= gradient[None, :]

    # Sensor noise.
    array += np.random.default_rng(seed).normal(0, rng.uniform(4, 8), array.shape)
    array = np.clip(array, 0, 255).astype(np.uint8)

    degraded = Image.fromarray(array, mode="L")
    # Slight optical softness.
    degraded = degraded.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 0.8)))
    # The skew the deskew step has to undo.
    angle = rng.choice([-2.6, -1.8, 1.7, 2.4])
    degraded = degraded.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=246)
    return degraded


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (name, lines) in enumerate(REPORTS):
        image = _degrade(_render(lines, seed=index), seed=index)
        path = OUT_DIR / name
        image.save(path, "PNG")
        print(f"  {name:<38} {image.size[0]}x{image.size[1]}  {path.stat().st_size // 1024} KB")
    print(f"\nWrote {len(REPORTS)} synthetic scans to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
