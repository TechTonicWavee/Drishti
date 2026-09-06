"""Scan preprocessing.

Real inspection paperwork arrives photographed on a phone or pushed through an
office scanner: a couple of degrees off-square, speckled with sensor noise, and
lit unevenly. A vision model reads such a page noticeably worse than a clean
one, and the fix is cheap, so it happens before anything reaches the model.

The pipeline, in order:

    1. grayscale      — colour carries nothing on a printed page
    2. denoise        — before thresholding, so speckle does not become text
    3. deskew         — rotate the page square
    4. CLAHE          — even out the lighting gradient without blowing out ink
    5. downscale      — bound the longest edge

Order matters. Deskewing depends on thresholding the page to find the text
block, and thresholding speckle produces a cloud of false "text" that drags the
estimated angle around. Denoising first is what makes the angle estimate
trustworthy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np

# Beyond this the model gains nothing and the base64 payload grows for no
# reason.
MAX_EDGE: Final = 1600

# Below this many ink pixels the page is effectively blank and an angle
# estimated from it would be noise.
MIN_INK_PIXELS: Final = 200

# Bounds the search. A scanner or a phone photo is off by a few degrees, not
# tens; searching wider mostly finds spurious maxima on pages with figures.
MAX_PLAUSIBLE_SKEW: Final = 8.0


class ImagePrepError(RuntimeError):
    """The file could not be read as an image."""


def deskew(gray: np.ndarray, angle: float) -> np.ndarray:
    """Rotate by -angle about the centre, padding with page white."""
    if abs(angle) < 0.05:
        return gray
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def estimate_skew(gray: np.ndarray) -> float:
    """Degrees the page is rotated by, positive meaning counter-clockwise.

    Uses a projection-profile search rather than minAreaRect over the ink
    pixels. minAreaRect was tried first and proved fragile: on one of the
    sample scans it collapsed to exactly 0 degrees because the bounding
    rectangle of the text cloud happened to be described by its other edge,
    silently reporting a visibly skewed page as straight.

    The profile method instead asks the question that actually matters — at
    which rotation do the text lines line up with image rows? When a page is
    square, each row of pixels is either dense with ink or empty, so the
    row-sum profile swings hard between the two. Skewed, the lines smear
    across rows and the profile flattens. Maximising the variance of that
    profile therefore finds the angle that makes the text horizontal.
    """
    threshold = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    if int(np.count_nonzero(threshold)) < MIN_INK_PIXELS:
        return 0.0

    # Estimate on a small copy: the angle does not need full resolution, and
    # this keeps the search to a few milliseconds.
    height, width = threshold.shape
    scale = min(1.0, 800 / max(height, width))
    if scale < 1.0:
        threshold = cv2.resize(
            threshold, (int(width * scale), int(height * scale)),
            interpolation=cv2.INTER_AREA,
        )

    best_angle, best_score = 0.0, -1.0
    for candidate in np.arange(-MAX_PLAUSIBLE_SKEW, MAX_PLAUSIBLE_SKEW + 0.25, 0.25):
        rotated = deskew(threshold, float(candidate))
        profile = rotated.sum(axis=1, dtype=np.float64)
        score = float(np.var(profile))
        if score > best_score:
            best_angle, best_score = float(candidate), score

    return best_angle


def preprocess(gray: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Run the full pipeline, returning the image and what was done to it."""
    original_shape = gray.shape[:2]

    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7,
                                        searchWindowSize=21)
    angle = estimate_skew(denoised)
    straightened = deskew(denoised, angle)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    evened = clahe.apply(straightened)

    height, width = evened.shape[:2]
    scale = min(1.0, MAX_EDGE / max(height, width))
    if scale < 1.0:
        evened = cv2.resize(
            evened, (int(width * scale), int(height * scale)),
            interpolation=cv2.INTER_AREA,
        )

    return evened, {
        "deskew_degrees": round(angle, 2),
        "original_size": f"{original_shape[1]}x{original_shape[0]}",
        "processed_size": f"{evened.shape[1]}x{evened.shape[0]}",
        "downscaled": scale < 1.0,
    }


def to_png_bytes(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ImagePrepError("Could not encode the processed image as PNG.")
    return buffer.tobytes()


def load_grayscale(path: str | Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ImagePrepError(f"Could not read an image from {path}")
    return image


def pdf_pages_to_grayscale(
    path: str | Path, max_pages: int
) -> tuple[list[np.ndarray], int]:
    """Render PDF pages to grayscale arrays, with the document's page count.

    Rendered at 200 dpi: enough for small print to survive, without producing
    images so large that the downscale step throws the detail away again.

    The total is returned alongside so a caller can say when it only read part
    of a document. Reading the first five pages of an eighty-page report and
    reporting on them as though they were the whole thing is worse than
    refusing — the answer looks complete and is not.
    """
    import pymupdf

    pages: list[np.ndarray] = []
    with pymupdf.open(str(path)) as document:
        total = document.page_count
        for index, page in enumerate(document):
            if index >= max_pages:
                break
            pixmap = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
            buffer = np.frombuffer(pixmap.samples, dtype=np.uint8)
            pages.append(buffer.reshape(pixmap.height, pixmap.width))
    if not pages:
        raise ImagePrepError(f"No pages could be rendered from {path}")
    return pages, total
