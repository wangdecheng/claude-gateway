#!/usr/bin/env python3
"""OCR image to text using macOS Vision framework or tesseract.

Usage:
    python3 bin/ocr_image.py <image_path> [--method auto|vision|tesseract] [--lang chi_sim+eng]

Methods:
    vision    - macOS built-in Vision framework (default on macOS, no deps)
    tesseract - Tesseract OCR engine (requires `brew install tesseract`)
    auto      - Try vision first, fall back to tesseract

Returns extracted text on stdout, errors on stderr.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ── JXA script for macOS Vision framework ──────────────────────────
_VISION_JXA = r"""
function run(argv) {
    ObjC.import('Vision');
    ObjC.import('AppKit');
    ObjC.import('Foundation');
    ObjC.import('Quartz');

    var filePath = argv[0];
    var languages = argv.length > 1 ? argv[1].split(',') : ['zh-Hans', 'zh-Hant', 'en', 'ja', 'ko'];

    var nsFilePath = $.NSString.stringWithString(filePath);
    var imgData = $.NSData.dataWithContentsOfFile(nsFilePath);
    if (imgData.isNil()) {
        console.log(JSON.stringify({error: 'Failed to load image: ' + filePath}));
        return;
    }

    var img = $.NSImage.alloc.initWithData(imgData);
    if (img.isNil()) {
        console.log(JSON.stringify({error: 'Failed to create NSImage from data'}));
        return;
    }

    var representations = img.representations;
    if (representations.count === 0) {
        console.log(JSON.stringify({error: 'No image representations'}));
        return;
    }
    var imgRep = representations.objectAtIndex(0);
    var cgImage = imgRep.CGImage;

    if (!cgImage) {
        console.log(JSON.stringify({error: 'Failed to get CGImage from image'}));
        return;
    }

    var recognizedTexts = [];
    var request = $.VNRecognizeTextRequest.alloc.initWithCompletionHandler(
        function(request, error) {
            if (error.js) {
                recognizedTexts.push('__ERROR__:' + error.localizedDescription.js);
                return;
            }
            var results = request.results;
            if (results && results.count > 0) {
                for (var i = 0; i < results.count; i++) {
                    var observation = results.objectAtIndex(i);
                    var topCandidate = observation.topCandidates(1).objectAtIndex(0);
                    recognizedTexts.push(topCandidate.string.js);
                }
            }
        }
    );

    request.recognitionLevel = $.VNRequestTextRecognitionLevelAccurate;
    request.recognitionLanguages = $(languages);
    request.usesLanguageCorrection = true;

    var handler = $.VNImageRequestHandler.alloc.initWithCGImageOptions(cgImage, $.NSDictionary.dictionary);
    var requests = $.NSArray.arrayWithObject(request);
    var errorRef = $();
    var success = handler.performRequestsError(requests, errorRef);

    if (!success) {
        var errMsg = 'OCR recognition failed';
        if (errorRef.$) {
            errMsg = errorRef.$.localizedDescription.js;
        }
        console.log(JSON.stringify({error: errMsg}));
        return;
    }

    if (recognizedTexts.length === 0) {
        console.log(JSON.stringify({text: ''}));
    } else if (recognizedTexts[0].indexOf('__ERROR__:') === 0) {
        console.log(JSON.stringify({error: recognizedTexts[0].substring(9)}));
    } else {
        console.log(JSON.stringify({text: recognizedTexts.join('\n')}));
    }
}
"""

# Vision language name → Apple locale codes for recognitionLanguages
_VISION_LANG_MAP = {
    "chi_sim": "zh-Hans",
    "chi_tra": "zh-Hant",
    "eng": "en",
    "jpn": "ja",
    "kor": "ko",
    "fra": "fr",
    "deu": "de",
    "spa": "es",
    "por": "pt",
    "ita": "it",
    "rus": "ru",
    "ara": "ar",
}


def _tesseract_langs_to_vision(tesseract_langs: str) -> str:
    """Convert tesseract language codes to Vision locale codes (comma-separated)."""
    codes = [l.strip() for l in tesseract_langs.split("+")]
    mapped = [_VISION_LANG_MAP.get(c, c) for c in codes]
    return ",".join(mapped)


def ocr_vision(image_path: str, languages: str = "zh-Hans,zh-Hant,en,ja,ko") -> str:
    """Run macOS Vision OCR on an image. Returns extracted text."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jxa", prefix="ocr_", delete=False
    ) as f:
        f.write(_VISION_JXA)
        jxa_path = f.name

    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", jxa_path, image_path, languages],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # JXA console.log() writes to stderr
        output = result.stderr.strip() or result.stdout.strip()

        if result.returncode != 0:
            raise RuntimeError(f"osascript failed ({result.returncode}): {output}")

        data = json.loads(output)
        if "error" in data:
            raise RuntimeError(data["error"])
        return data.get("text", "")
    finally:
        os.unlink(jxa_path)


def ocr_tesseract(image_path: str, languages: str = "chi_sim+eng") -> str:
    """Run tesseract OCR on an image. Returns extracted text."""
    result = subprocess.run(
        ["tesseract", image_path, "stdout", "-l", languages, "--psm", "3"],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"tesseract failed: {err}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def ocr_auto(image_path: str, languages: str = "chi_sim+eng") -> str:
    """Try Vision first, fall back to tesseract."""
    if sys.platform == "darwin":
        try:
            vision_langs = _tesseract_langs_to_vision(languages)
            return ocr_vision(image_path, vision_langs)
        except Exception as e:
            print(f"Vision OCR failed ({e}), falling back to tesseract...", file=sys.stderr)
    return ocr_tesseract(image_path, languages)


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from an image using OCR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 bin/ocr_image.py screenshot.png
  python3 bin/ocr_image.py photo.jpg --lang eng
  python3 bin/ocr_image.py receipt.png --method tesseract --lang chi_sim+eng
  python3 bin/ocr_image.py scan.png --method vision""",
    )
    parser.add_argument("image", help="Path to the image file")
    parser.add_argument(
        "--method",
        choices=["auto", "vision", "tesseract"],
        default="auto",
        help="OCR engine (default: auto — vision on macOS, tesseract fallback)",
    )
    parser.add_argument(
        "--lang",
        default="chi_sim+eng",
        help="Languages for tesseract (e.g. chi_sim+eng, jpn, kor). "
        "Auto-mapped to Vision locale codes when using vision method.",
    )
    args = parser.parse_args()

    image_path = args.image
    if not os.path.isfile(image_path):
        print(f"Error: file not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.method == "vision":
            vision_langs = _tesseract_langs_to_vision(args.lang)
            text = ocr_vision(image_path, vision_langs)
        elif args.method == "tesseract":
            text = ocr_tesseract(image_path, args.lang)
        else:  # auto
            text = ocr_auto(image_path, args.lang)

        print(text)
    except Exception as e:
        print(f"OCR error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
