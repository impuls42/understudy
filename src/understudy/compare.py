"""Image comparison primitives.

Three strategies:
  template  — cv2.matchTemplate; find a sub-image anywhere in a larger one.
               Best for "is this UI element present?".
  phash     — perceptual hash; robust to rendering jitter and minor differences.
               Best for "is this still the same frame?" (crash/hang detection).
  pixelmatch— pixel-by-pixel diff count.
               Best for regression detection against pixel-perfect references.
  frozen    — hash a sequence of frames; true if N consecutive frames are identical.
               Used by the watchdog to detect a crash or hang.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image


def load_image(path_or_img: Path | str | Image.Image | np.ndarray) -> np.ndarray:
    """Normalise input to a uint8 RGBA numpy array (HxWx4)."""
    if isinstance(path_or_img, np.ndarray):
        img = path_or_img
    elif isinstance(path_or_img, Image.Image):
        img = np.array(path_or_img.convert("RGBA"))
    else:
        img = np.array(Image.open(str(path_or_img)).convert("RGBA"))
    return img


def _to_bgr(arr: np.ndarray) -> np.ndarray:
    """Convert RGBA uint8 to BGR for OpenCV."""
    rgb = arr[:, :, :3]
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def template(
    scene: Path | str | Image.Image | np.ndarray,
    ref: Path | str | Image.Image | np.ndarray,
    threshold: float = 0.85,
) -> tuple[bool, float, tuple[int, int]]:
    """Check if *ref* (template) appears anywhere in *scene*.

    Returns (matched, score, (x, y)) where (x, y) is the top-left corner of
    the best match in *scene* coordinates.  *score* is in [0, 1].
    """
    scene_bgr = _to_bgr(load_image(scene))
    ref_bgr = _to_bgr(load_image(ref))
    result = cv2.matchTemplate(scene_bgr, ref_bgr, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return max_val >= threshold, float(max_val), max_loc


def phash(
    a: Path | str | Image.Image | np.ndarray,
    b: Path | str | Image.Image | np.ndarray,
    max_distance: int = 10,
) -> tuple[bool, int]:
    """Compare two images by perceptual hash.

    Returns (similar, hamming_distance).  Smaller distance = more similar.
    A distance of 0 means identical hashes; ≤10 is typically a near-match.
    """
    def _ph(x):
        if isinstance(x, (str, Path)):
            return imagehash.phash(Image.open(str(x)))
        img = x if isinstance(x, Image.Image) else Image.fromarray(load_image(x)[:, :, :3])
        return imagehash.phash(img)

    dist = int(_ph(a) - _ph(b))
    return dist <= max_distance, dist


def pixelmatch(
    a: Path | str | Image.Image | np.ndarray,
    b: Path | str | Image.Image | np.ndarray,
    max_diff_ratio: float = 0.01,
) -> tuple[bool, float]:
    """Count differing pixels between two same-size images.

    Returns (similar, diff_ratio) where diff_ratio is in [0, 1].
    """
    arr_a = load_image(a)[:, :, :3].astype(np.int16)
    arr_b = load_image(b)[:, :, :3].astype(np.int16)
    if arr_a.shape != arr_b.shape:
        raise ValueError(
            f"pixelmatch requires same-size images: {arr_a.shape} vs {arr_b.shape}"
        )
    diff = np.abs(arr_a - arr_b).max(axis=2) > 10  # >10 per channel = "different"
    ratio = float(diff.mean())
    return ratio <= max_diff_ratio, ratio


def is_frozen(
    frames: list[Path | str | Image.Image | np.ndarray],
    identical_threshold: int = 5,
    max_hamming: int = 3,
) -> bool:
    """Return True if the last *identical_threshold* frames are perceptually identical.

    Used as a crash/hang watchdog: if N consecutive captures return the same
    hash, the game has likely frozen.
    """
    if len(frames) < identical_threshold:
        return False
    recent = frames[-identical_threshold:]
    hashes = []
    for f in recent:
        img = f if isinstance(f, Image.Image) else Image.fromarray(load_image(f)[:, :, :3])
        hashes.append(imagehash.phash(img))
    # All hashes within max_hamming of the first → frozen
    return all(int(h - hashes[0]) <= max_hamming for h in hashes[1:])
