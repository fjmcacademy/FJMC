import cv2
import numpy as np

PAGE_W = 1240
PAGE_H = 1754

MM_X = PAGE_W / 210.0
MM_Y = PAGE_H / 297.0

# Template layout in millimetres.
ANSWER_COLUMNS_X = [26.5, 86.7, 147.0]
ANSWER_FIRST_Y = 82.6
ANSWER_ROWS_PER_COLUMN = 34
ANSWER_ROW_PITCH = 5.82

ROLL_FIRST_X = 42.0
ROLL_COLUMN_PITCH = 17.0
ROLL_FIRST_Y = 47.0
ROLL_ROW_PITCH = 2.65

OPTIONS = ["A", "B", "C", "D"]


def mm_point(x_mm, y_mm):
    return (
        int(round(x_mm * MM_X)),
        int(round(y_mm * MM_Y))
    )


def circle_darkness(gray, x, y, radius):
    """
    Compare the dark centre of a bubble with its outer ring.
    Returns a normalized fill score between approximately 0 and 1.
    """
    h, w = gray.shape

    x1 = max(0, x - radius * 2)
    x2 = min(w, x + radius * 2 + 1)
    y1 = max(0, y - radius * 2)
    y2 = min(h, y + radius * 2 + 1)

    roi = gray[y1:y2, x1:x2]

    if roi.size == 0:
        return 0.0

    yy, xx = np.ogrid[
        y1:y2, x1:x2
    ]

    distance = np.sqrt(
        (xx - x) ** 2 + (yy - y) ** 2
    )

    centre = roi[distance <= radius * 0.62]
    ring = roi[
        (distance >= radius * 1.15) &
        (distance <= radius * 1.75)
    ]

    if centre.size < 3 or ring.size < 3:
        return 0.0

    centre_dark = 255.0 - float(np.mean(centre))
    ring_dark = 255.0 - float(np.mean(ring))

    # Printed outline contributes to the ring score.
    # Subtracting it helps distinguish an empty circle.
    score = (centre_dark - ring_dark * 0.35) / 210.0

    return float(np.clip(score, 0.0, 1.0))


def read_bubble(gray, x_mm, y_mm):
    x, y = mm_point(x_mm, y_mm)

    radius = max(
        4,
        int(round(2.0 * MM_X))
    )

    return circle_darkness(gray, x, y, radius)


def detect_answer_column(gray, question_number):
    if not 1 <= question_number <= 100:
        raise ValueError("Question number must be 1 to 100.")

    column = (question_number - 1) // 34
    row = (question_number - 1) % 34

    x_base = ANSWER_COLUMNS_X[column]
    y = ANSWER_FIRST_Y + row * ANSWER_ROW_PITCH

    scores = {}

    for index, option in enumerate(OPTIONS):
        x = x_base + index * 7.1
        scores[option] = read_bubble(gray, x, y)

    ordered = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    best_option, best_score = ordered[0]
    second_score = ordered[1][1]

    # Conservative thresholds: uncertain marks go to review.
    if best_score < 0.15:
        status = "blank"
        answer = None
    elif second_score >= 0.15 and (
        best_score - second_score
    ) < 0.07:
        status = "multiple_or_unclear"
        answer = None
    else:
        status = "marked"
        answer = best_option

    return {
        "question": question_number,
        "answer": answer,
        "status": status,
        "confidence": round(best_score, 3),
        "scores": {
            key: round(value, 3)
            for key, value in scores.items()
        }
    }


def read_roll_number(gray):
    digits = []
    column_scores = []
    review = False

    for col in range(8):
        x = ROLL_FIRST_X + col * ROLL_COLUMN_PITCH
        scores = {}

        for digit in range(10):
            y = ROLL_FIRST_Y + digit * ROLL_ROW_PITCH
            scores[str(digit)] = read_bubble(
                gray, x, y
            )

        ordered = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        best_digit, best_score = ordered[0]
        second_score = ordered[1][1]

        if best_score < 0.15:
            digits.append("?")
            review = True
        elif second_score >= 0.15 and (
            best_score - second_score
        ) < 0.07:
            digits.append("?")
            review = True
        else:
            digits.append(best_digit)

        column_scores.append({
            "column": col + 1,
            "digit": digits[-1],
            "confidence": round(best_score, 3),
            "scores": {
                k: round(v, 3)
                for k, v in scores.items()
            }
        })

    roll = "".join(digits)

    return {
        "roll_number": roll,
        "review_required": review,
        "columns": column_scores
    }


def analyze_sheet(image):
    if image is None:
        raise ValueError("No image supplied.")

    if image.shape[1] != PAGE_W or image.shape[0] != PAGE_H:
        image = cv2.resize(
            image,
            (PAGE_W, PAGE_H),
            interpolation=cv2.INTER_AREA
        )

    gray = cv2.cvtColor(
        image, cv2.COLOR_BGR2GRAY
    )

    roll_data = read_roll_number(gray)

    answers = [
        detect_answer_column(gray, q)
        for q in range(1, 101)
    ]

    review_questions = [
        item["question"]
        for item in answers
        if item["status"] != "marked"
    ]

    return {
        "roll": roll_data,
        "answers": answers,
        "review_questions": review_questions,
        "review_required": (
            roll_data["review_required"] or
            bool(review_questions)
        )
    }


def calculate_score(
    detected_answers,
    answer_key,
    marks_per_question=2.0,
    negative_per_question=0.5
):
    correct = 0
    wrong = 0
    blank = 0
    unclear = 0
    score = 0.0

    for item in detected_answers:
        q = str(item["question"])
        detected = item["answer"]
        status = item["status"]

        if status != "marked":
            if status == "blank":
                blank += 1
            else:
                unclear += 1
            continue

        expected = answer_key.get(q)

        if not expected:
            continue

        if detected == str(expected).strip().upper():
            correct += 1
            score += float(marks_per_question)
        else:
            wrong += 1
            score -= float(negative_per_question)

    return {
        "correct": correct,
        "wrong": wrong,
        "blank": blank,
        "unclear": unclear,
        "score": round(score, 2),
        "maximum_marks": round(
            len(answer_key) * float(marks_per_question), 2
        )
  }
