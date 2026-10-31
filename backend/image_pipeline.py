from dataclasses import dataclass
from typing import Optional
import cv2
import numpy as np


@dataclass
class ScanResult:
    image: np.ndarray
    page_detected: bool
    method: str
    warnings: list


OUT_W = 1240
OUT_H = 1754


def order_points(points):
    p = np.asarray(points, dtype=np.float32).reshape(4, 2)
    s = p.sum(axis=1)
    d = np.diff(p, axis=1).reshape(-1)

    return np.array([
        p[np.argmin(s)],  # top-left
        p[np.argmin(d)],  # top-right
        p[np.argmax(s)],  # bottom-right
        p[np.argmax(d)]   # bottom-left
    ], dtype=np.float32)


def warp_page(image, corners):
    rect = order_points(corners)

    target = np.array([
        [0, 0],
        [OUT_W - 1, 0],
        [OUT_W - 1, OUT_H - 1],
        [0, OUT_H - 1]
    ], dtype=np.float32)

    matrix = cv2.getPerspectiveTransform(rect, target)

    return cv2.warpPerspective(
        image,
        matrix,
        (OUT_W, OUT_H),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )


def find_marker_centres(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Black marker squares are isolated using thresholding.
    _, mask = cv2.threshold(
        gray, 75, 255, cv2.THRESH_BINARY_INV
    )

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    h, w = gray.shape
    candidates = []

    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)

        if area < (w * h * 0.00008):
            continue

        ratio = cw / max(ch, 1)

        if not 0.65 <= ratio <= 1.35:
            continue

        if cw < w * 0.008 or ch < h * 0.008:
            continue

        fill = area / max(cw * ch, 1)

        if fill < 0.55:
            continue

        candidates.append((area, (x + cw / 2, y + ch / 2)))

    if len(candidates) < 4:
        return None

    # The four largest square-like dark regions are considered.
    candidates.sort(key=lambda item: item[0], reverse=True)
    points = [item[1] for item in candidates[:12]]

    points = np.asarray(points, dtype=np.float32)

    # Pick the extreme points from the candidate set.
    tl = points[np.argmin(points[:, 0] + points[:, 1])]
    tr = points[np.argmax(points[:, 0] - points[:, 1])]
    br = points[np.argmax(points[:, 0] + points[:, 1])]
    bl = points[np.argmin(points[:, 0] - points[:, 1])]

    quad = np.array([tl, tr, br, bl], dtype=np.float32)

    if len(np.unique(quad, axis=0)) != 4:
        return None

    return quad


def find_page_contour(image):
    h, w = image.shape[:2]
    scale = min(1.0, 1400 / max(h, w))

    small = cv2.resize(
        image, None, fx=scale, fy=scale,
        interpolation=cv2.INTER_AREA
    )

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 35, 110)

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (7, 7)
    )
    edges = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, kernel
    )

    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    contours = sorted(
        contours, key=cv2.contourArea, reverse=True
    )

    for contour in contours[:15]:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(
            contour, 0.02 * perimeter, True
        )

        if len(approx) == 4:
            area = cv2.contourArea(approx)
            if area > small.shape[0] * small.shape[1] * 0.18:
                return approx.reshape(4, 2).astype(
                    np.float32
                ) / scale

    return None


def enhance_image(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(
        clipLimit=1.5, tileGridSize=(8, 8)
    )
    l = clahe.apply(l)

    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(
        enhanced, cv2.COLOR_LAB2BGR
    )

    return enhanced


def prepare_mobile_photo(image_bytes: bytes) -> ScanResult:
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("Image file could not be decoded.")

    h, w = image.shape[:2]

    if max(h, w) > 4000:
        scale = 4000 / max(h, w)
        image = cv2.resize(
            image, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_AREA
        )

    warnings = []

    corners = find_marker_centres(image)
    method = "corner_markers"

    if corners is None:
        corners = find_page_contour(image)
        method = "page_contour"

    if corners is not None:
        result = warp_page(image, corners)
        detected = True
    else:
        # Do not stretch the photo. Fit it inside an A4 canvas.
        ih, iw = image.shape[:2]
        scale = min(OUT_W / iw, OUT_H / ih)

        nw = max(1, int(iw * scale))
        nh = max(1, int(ih * scale))

        resized = cv2.resize(
            image, (nw, nh),
            interpolation=cv2.INTER_AREA
        )

        result = np.full(
            (OUT_H, OUT_W, 3), 255, dtype=np.uint8
        )

        x = (OUT_W - nw) // 2
        y = (OUT_H - nh) // 2
        result[y:y + nh, x:x + nw] = resized

        detected = False
        method = "no_page_boundary"
        warnings.append(
            "Page boundary was not detected. Check alignment manually."
        )

    result = enhance_image(result)

    gray = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    blur_score = float(cv2.Laplacian(
        gray, cv2.CV_64F
    ).var())

    if brightness < 75:
        warnings.append("Photo is too dark.")

    if blur_score < 45:
        warnings.append("Photo may be blurred.")

    return ScanResult(
        image=result,
        page_detected=detected,
        method=method,
        warnings=warnings
  )
