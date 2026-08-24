"""
Social Media Content Analyzer - Backend
----------------------------------------
Flask API that:
  1. Accepts an uploaded PDF or image file.
  2. Extracts text from it:
       - PDF  -> pdfplumber (preserves per-line / layout structure)
       - Image -> Tesseract OCR (pytesseract)
  3. Runs the extracted text through a lightweight, rule-based
     "engagement analyzer" and returns actionable suggestions.

No paid/external AI service is used - the analyzer is a transparent,
deterministic heuristic engine, so it works fully offline and on any
free tier.
"""

import io
import os
import re
import traceback

from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

import pdfplumber
import pytesseract
from PIL import Image

app = Flask(__name__)

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
ALLOWED_PDF_EXT = {"pdf"}
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "gif"}
MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15 MB

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


# ---------------------------------------------------------------------
# CORS (handled manually - avoids an extra dependency)
# ---------------------------------------------------------------------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def get_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def extract_text_from_pdf(file_stream) -> dict:
    """
    Extract text from a PDF while keeping a reasonable amount of
    layout/formatting information (line breaks, per-page separation).
    Falls back to OCR-per-page image rendering only if a page has no
    extractable text (i.e. it's a scanned/image-only PDF).
    """
    pages_text = []
    used_ocr_fallback = False

    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            if not text.strip():
                # Scanned page with no embedded text -> OCR the rendered image
                used_ocr_fallback = True
                try:
                    pil_image = page.to_image(resolution=200).original
                    text = pytesseract.image_to_string(pil_image)
                except Exception:
                    text = ""
            pages_text.append(text.strip())

    full_text = "\n\n".join(p for p in pages_text if p)
    return {
        "text": full_text,
        "pages": len(pages_text),
        "used_ocr_fallback": used_ocr_fallback,
    }


def extract_text_from_image(file_stream) -> dict:
    image = Image.open(file_stream)
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    text = pytesseract.image_to_string(image)
    return {"text": text.strip(), "pages": 1, "used_ocr_fallback": True}


# ---------------------------------------------------------------------
# Engagement analyzer (rule-based, transparent, no external API needed)
# ---------------------------------------------------------------------
HOOK_WORDS = [
    "you", "your", "free", "new", "secret", "how", "why", "what",
    "stop", "imagine", "warning", "breaking", "finally", "never",
]
CTA_PATTERNS = [
    r"\bcomment\b", r"\bshare\b", r"\blike\b", r"\bfollow\b",
    r"\btag\b", r"\bclick\b", r"\bsign up\b", r"\bswipe\b",
    r"\bdm\b", r"\bsave this\b", r"\blearn more\b", r"\bjoin\b",
    r"\bsubscribe\b", r"\blink in bio\b",
]


def count_syllables(word: str) -> int:
    word = word.lower()
    vowels = "aeiouy"
    count = 0
    prev_was_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_was_vowel:
            count += 1
        prev_was_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def analyze_engagement(text: str) -> dict:
    suggestions = []
    scores = {}

    words = re.findall(r"[A-Za-z']+", text)
    word_count = len(words)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    sentence_count = max(len(sentences), 1)

    hashtags = re.findall(r"#\w+", text)
    mentions = re.findall(r"@\w+", text)
    urls = re.findall(r"https?://\S+|www\.\S+", text)
    emojis = re.findall(
        r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]",
        text,
    )
    question_marks = text.count("?")
    exclamations = text.count("!")

    # --- Length -------------------------------------------------------
    if word_count == 0:
        suggestions.append({
            "category": "Content",
            "severity": "high",
            "message": "No readable text was found. Add a caption - "
                       "posts with text context get significantly more engagement than blank media.",
        })
    elif word_count < 8:
        suggestions.append({
            "category": "Length",
            "severity": "medium",
            "message": f"Caption is very short ({word_count} words). "
                       "Consider adding 1-2 sentences of context or a question to invite comments.",
        })
    elif word_count > 220:
        suggestions.append({
            "category": "Length",
            "severity": "medium",
            "message": f"Caption is long ({word_count} words). "
                       "Long-form works on some platforms, but consider a strong hook in the first "
                       "line so it reads well even when truncated.",
        })
    else:
        suggestions.append({
            "category": "Length",
            "severity": "good",
            "message": f"Caption length ({word_count} words) is in a solid range for social platforms.",
        })

    # --- Readability (simplified Flesch Reading Ease) ------------------
    if word_count > 0:
        syllable_count = sum(count_syllables(w) for w in words)
        flesch = (
            206.835
            - 1.015 * (word_count / sentence_count)
            - 84.6 * (syllable_count / word_count)
        )
        scores["readability_score"] = round(flesch, 1)
        if flesch < 40:
            suggestions.append({
                "category": "Readability",
                "severity": "medium",
                "message": "Text reads as fairly dense/complex. Try shorter sentences and "
                           "simpler words to improve scroll-stopping readability.",
            })
        else:
            suggestions.append({
                "category": "Readability",
                "severity": "good",
                "message": "Text is easy to read at a glance - good for fast-scrolling feeds.",
            })

    # --- Hook (first line) ---------------------------------------------
    first_line = sentences[0].strip().lower() if sentences else ""
    has_hook_word = any(hw in first_line for hw in HOOK_WORDS)
    if first_line and not has_hook_word:
        suggestions.append({
            "category": "Hook",
            "severity": "low",
            "message": "The opening line could be punchier. Starting with a question, a bold "
                       "claim, or a direct 'you' statement tends to stop the scroll.",
        })
    elif first_line:
        suggestions.append({
            "category": "Hook",
            "severity": "good",
            "message": "Opening line already uses attention-grabbing language.",
        })

    # --- Call to action ---------------------------------------------------
    has_cta = any(re.search(p, text, re.IGNORECASE) for p in CTA_PATTERNS)
    if not has_cta:
        suggestions.append({
            "category": "Call to Action",
            "severity": "high",
            "message": "No clear call to action detected. Ask readers to comment, share, "
                       "save, or tag a friend to boost engagement signals.",
        })
    else:
        suggestions.append({
            "category": "Call to Action",
            "severity": "good",
            "message": "Includes a call to action - nice, this nudges algorithmic engagement.",
        })

    # --- Hashtags -----------------------------------------------------
    if len(hashtags) == 0:
        suggestions.append({
            "category": "Hashtags",
            "severity": "medium",
            "message": "No hashtags found. Adding 3-8 relevant hashtags can meaningfully "
                       "improve discoverability.",
        })
    elif len(hashtags) > 15:
        suggestions.append({
            "category": "Hashtags",
            "severity": "low",
            "message": f"{len(hashtags)} hashtags is a lot and can look spammy. "
                       "Consider trimming to your best 5-10.",
        })
    else:
        suggestions.append({
            "category": "Hashtags",
            "severity": "good",
            "message": f"Good hashtag usage ({len(hashtags)} found).",
        })

    # --- Questions (invites comments) ----------------------------------
    if question_marks == 0:
        suggestions.append({
            "category": "Engagement Hook",
            "severity": "low",
            "message": "No questions in the text. Asking your audience a direct question "
                       "is one of the simplest ways to drive comments.",
        })

    # --- Emojis ---------------------------------------------------------
    if len(emojis) == 0:
        suggestions.append({
            "category": "Visual Appeal",
            "severity": "low",
            "message": "No emojis detected. A couple of relevant emojis can improve "
                       "scannability and tone without looking unprofessional.",
        })

    # --- Links ------------------------------------------------------------
    if urls:
        suggestions.append({
            "category": "Links",
            "severity": "low",
            "message": "Contains a raw link. Many platforms de-prioritize posts with outbound "
                       "links - consider 'link in bio' instead if this is for Instagram/TikTok.",
        })

    stats = {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "hashtag_count": len(hashtags),
        "mention_count": len(mentions),
        "url_count": len(urls),
        "emoji_count": len(emojis),
        "question_marks": question_marks,
        "exclamation_marks": exclamations,
        **scores,
    }

    return {"stats": stats, "suggestions": suggestions}


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    if "file" not in request.files:
        return jsonify({"error": "No file part in the request."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    filename = secure_filename(file.filename)
    ext = get_extension(filename)

    if ext not in ALLOWED_PDF_EXT | ALLOWED_IMAGE_EXT:
        return jsonify({
            "error": f"Unsupported file type '.{ext}'. "
                     f"Allowed: PDF or image ({', '.join(sorted(ALLOWED_IMAGE_EXT))})."
        }), 400

    try:
        file_bytes = file.read()
        stream = io.BytesIO(file_bytes)

        if ext in ALLOWED_PDF_EXT:
            extraction = extract_text_from_pdf(stream)
            file_type = "pdf"
        else:
            extraction = extract_text_from_image(stream)
            file_type = "image"

        analysis = analyze_engagement(extraction["text"])

        return jsonify({
            "filename": filename,
            "file_type": file_type,
            "pages": extraction["pages"],
            "used_ocr": extraction["used_ocr_fallback"],
            "extracted_text": extraction["text"],
            "stats": analysis["stats"],
            "suggestions": analysis["suggestions"],
        })

    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": f"Failed to process file: {exc}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
