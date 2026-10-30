"""
FJMC Academy Smart OMR - mobile photo normalization helpers.

Dependencies already commonly used by the FJMC backend:
    pip install opencv-python-headless numpy

This module is deliberately separate from the existing OMR answer/roll-number
reader. It prepares a camera photo for the existing OMR pipeline and does not
change bubble coordinates, scoring, ranking, or result storage.

Integration:
    from image_pipeline import prepare_mobile_photo

    prepared = prepare_mobile_photo(upload_bytes)
    corrected_bytes = prepared["image_bytes"]
    warnings = prepared["warnings"]
    # Send corrected_bytes through the EXISTING OMR scan pipeline.

Do not treat warnings as proof that a sheet is unreadable. Show them to the
operator and allow manual confirmation/retake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math

import cv2
import numpy as np


@dataclass
class PipelineConfig:
    # Portrait A4-like output. Keep this consistent with the OMR template.
    output_width: int = 1240
    output_height: int = 1754
    max_input_side: int = 3200
    jpeg_quality: int = 94
    min_page_area_ratio: float = 0.18
    blur_warning_laplacian: float = 45.0
    dark_warning_mean: float = 75.0
    shadow_warning_std: float = 48.0


def _decode_image(image_bytes: bytes) -> np.ndarray:
    if not image_bytes:
        raise ValueError("Empty image upload")
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unsupported or damaged image. Upload JPG, PNG or a PDF page.")
    return image


def _resize_limit(image: np.ndarray, max_side: int) -> np.ndarray:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    return cv2.resize(
        image,
        (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def _order_points(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(-1)
    # top-left, top-right, bottom-right, bottom-left
    return np.array(
        [
            pts[np.argmin(sums)],
            pts[np.argmin(diffs)],
            pts[np.argmax(sums)],
            pts[np.argmax(diffs)],
        ],
        dtype=np.float32,
    )


def _find_page_quad(image: np.ndarray, min_area_ratio: float) -> np.ndarray | None:
    """Find a likely sheet boundary. Returns four source-image corner points."""
    h, w = image.shape[:2]
    image_area = float(h * w)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Edge-based detection works better than a fixed white threshold for
    # cream paper, shadows, and blue-tinted phone photos.
    denoised = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(denoised, 35, 110)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for contour in contours[:20]:
        area = cv2.contourArea(contour)
        if area < image_area * min_area_ratio:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return _order_points(approx.reshape(4, 2))

    # Fallback: use the minimum-area rectangle only when a large page-like
    # contour exists. This is less precise, so it is not used for tiny objects.
    for contour in contours[:5]:
        if cv2.contourArea(contour) >= image_area * 0.45:
            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect)
            return _order_points(box)
    return None


def _warp_page(image: np.ndarray, quad: np.ndarray, cfg: PipelineConfig) -> np.ndarray:
    tl, tr, br, bl = quad
    width_top = np.linalg.norm(tr - tl)
    width_bottom = np.linalg.norm(br - bl)
    height_left = np.linalg.norm(bl - tl)
    height_right = np.linalg.norm(br - tr)

    observed_w = max(width_top, width_bottom)
    observed_h = max(height_left, height_right)

    # The OMR template is portrait. If the detected sheet is sideways, map
    # its longer physical dimension to output height.
    if observed_w > observed_h:
        dst = np.array(
            [
                [0, 0],
                [cfg.output_height - 1, 0],
                [cfg.output_height - 1, cfg.output_width - 1],
                [0, cfg.output_width - 1],
            ],
            dtype=np.float32,
        )
        out_size = (cfg.output_height, cfg.output_width)
    else:
        dst = np.array(
            [
                [0, 0],
                [cfg.output_width - 1, 0],
                [cfg.output_width - 1, cfg.output_height - 1],
                [0, cfg.output_height - 1],
            ],
            dtype=np.float32,
        )
        out_size = (cfg.output_width, cfg.output_height)

    matrix = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    return cv2.warpPerspective(
        image,
        matrix,
        out_size,
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _correct_colour_and_lighting(image: np.ndarray) -> np.ndarray:
    """Gentle white balance + illumination flattening; preserve pen strokes."""
    # Gray-world white balance, capped to avoid extreme channel amplification.
    f = image.astype(np.float32)
    channel_means = f.reshape(-1, 3).mean(axis=0)
    target = float(channel_means.mean())
    gains = target / np.maximum(channel_means, 1.0)
    gains = np.clip(gains, 0.78, 1.28)
    balanced = np.clip(f * gains.reshape(1, 1, 3), 0, 255).astype(np.uint8)

    # Flatten broad shadows in luminance only. Avoid hard thresholding, which
    # can erase light pencil/blue-pen marks needed by the OMR reader.
    lab = cv2.cvtColor(balanced, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    background = cv2.GaussianBlur(l, (0, 0), sigmaX=35, sigmaY=35)
    background = np.maximum(background, 35)
    flat = l.astype(np.float32) * 150.0 / background.astype(np.float32)
    flat = np.clip(flat, 0, 255).astype(np.uint8)

    # Mild CLAHE, not aggressive binary conversion.
    clahe = cv2.createCLAHE(clipLimit=1.35, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(flat)
    merged = cv2.merge((enhanced_l, a, b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _quality_report(image: np.ndarray, cfg: PipelineConfig) -> dict[str, Any]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(np.mean(gray))
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # A rough shadow indicator: spread of large-area local brightness.
    small = cv2.resize(gray, (max(8, gray.shape[1] // 80), max(8, gray.shape[0] // 80)))
    shadow_spread = float(np.std(small))

    warnings: list[str] = []
    if mean_brightness < cfg.dark_warning_mean:
        warnings.append("Photo is dark. Use brighter, even lighting.")
    if blur_score < cfg.blur_warning_laplacian:
        warnings.append("Photo may be blurry. Check bubble edges before scanning.")
    if shadow_spread > cfg.shadow_warning_std:
        warnings.append("Uneven lighting or shadows detected. Review the preview.")

    return {
        "brightness": round(mean_brightness, 2),
        "blur_score": round(blur_score, 2),
        "shadow_spread": round(shadow_spread, 2),
        "warnings": warnings,
    }


def prepare_mobile_photo(
    image_bytes: bytes,
    config: PipelineConfig | None = None,
) -> dict[str, Any]:
    """
    Normalize a phone photo and return a JPEG byte string plus preview metadata.

    Returns:
        {
          "image_bytes": bytes,
          "page_detected": bool,
          "width": int,
          "height": int,
          "quality": {...},
          "warnings": [str, ...],
          "needs_review": bool
        }

    If a page boundary cannot be found, the image is NOT stretched to A4.
    It is resized proportionally and flagged for manual preview instead.
    """
    cfg = config or PipelineConfig()
    image = _resize_limit(_decode_image(image_bytes), cfg.max_input_side)
    quad = _find_page_quad(image, cfg.min_page_area_ratio)
    page_detected = quad is not None

    if page_detected:
        corrected = _warp_page(image, quad, cfg)
    else:
        # Preserve aspect ratio; never distort an unrecognized photo to fit
        # the OMR template. Existing marker-based OMR alignment may still run.
        corrected = image.copy()
        h, w = corrected.shape[:2]
        scale = min(cfg.output_width / w, cfg.output_height / h)
        nw, nh = int(w * scale), int(h * scale)
        corrected = cv2.resize(corrected, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.full((cfg.output_height, cfg.output_width, 3), 245, np.uint8)
        x = (cfg.output_width - nw) // 2
        y = (cfg.output_height - nh) // 2
        canvas[y:y + nh, x:x + nw] = corrected
        corrected = canvas

    corrected = _correct_colour_and_lighting(corrected)
    quality = _quality_report(corrected, cfg)

    warnings = list(quality["warnings"])
    if not page_detected:
        warnings.insert(
            0,
            "Page corners were not confidently detected. Check alignment in preview.",
        )

    ok, encoded = cv2.imencode(
        ".jpg",
        corrected,
        [int(cv2.IMWRITE_JPEG_QUALITY), int(cfg.jpeg_quality)],
    )
    if not ok:
        raise RuntimeError("Could not encode corrected preview image")

    height, width = corrected.shape[:2]
    return {
        "image_bytes": encoded.tobytes(),
        "page_detected": page_detected,
        "width": int(width),
        "height": int(height),
        "quality": quality,
        "warnings": warnings,
        "needs_review": bool(warnings),
    }
