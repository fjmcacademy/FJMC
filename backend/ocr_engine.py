import os
import cv2
import numpy as np
import requests


OCR_API_URL = os.getenv("OCR_API_URL", "").strip()
OCR_API_TOKEN = os.getenv("OCR_API_TOKEN", "").strip()


def crop_name_region(image):
    """
    Name line on the supplied template:
    approximately x=18..108 mm, y=30..39 mm.
    """
    h, w = image.shape[:2]

    x1 = int(w * 18 / 210)
    x2 = int(w * 108 / 210)
    y1 = int(h * 30 / 297)
    y2 = int(h * 39 / 297)

    return image[y1:y2, x1:x2]


def prepare_name_image(image):
    gray = cv2.cvtColor(
        image, cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        None,
        fx=3,
        fy=3,
        interpolation=cv2.INTER_CUBIC
    )

    gray = cv2.bilateralFilter(
        gray, 5, 40, 40
    )

    gray = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    ).apply(gray)

    return gray


def recognize_name(image):
    crop = crop_name_region(image)
    prepared = prepare_name_image(crop)

    if not OCR_API_URL:
        return {
            "name": "",
            "source": "not_configured",
            "confidence": None,
            "review_required": True,
            "message": "Configure OCR_API_URL for handwriting recognition."
        }

    ok, encoded = cv2.imencode(
        ".png", prepared
    )

    if not ok:
        return {
            "name": "",
            "source": "encoding_error",
            "confidence": None,
            "review_required": True
        }

    headers = {}

    if OCR_API_TOKEN:
        headers["Authorization"] = (
            f"Bearer {OCR_API_TOKEN}"
        )

    try:
        response = requests.post(
            OCR_API_URL,
            headers=headers,
            files={
                "file": (
                    "name.png",
                    encoded.tobytes(),
                    "image/png"
                )
            },
            timeout=35
        )

        response.raise_for_status()
        data = response.json()

        name = (
            data.get("text") or
            data.get("generated_text") or
            data.get("prediction") or
            ""
        )

        if isinstance(name, list):
            if name and isinstance(name[0], dict):
                name = (
                    name[0].get("generated_text") or
                    name[0].get("text") or ""
                )
            else:
                name = ""

        name = " ".join(str(name).strip().split())

        # Do not invent confidence if provider does not return it.
        confidence = data.get("confidence")

        return {
            "name": name,
            "source": "external_ocr",
            "confidence": confidence,
            "review_required": (
                not name or
                confidence is None or
                float(confidence) < 0.80
            )
        }

    except Exception as exc:
        return {
            "name": "",
            "source": "ocr_error",
            "confidence": None,
            "review_required": True,
            "message": str(exc)[:250]
        }
