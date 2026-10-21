from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pypdfium2 as pdfium


async def _ocr_image(path: Path, language: str) -> str:
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile
    except ImportError as exc:  # pragma: no cover - optional rebuild dependency
        raise SystemExit(
            "Windows OCR bindings are missing. Install scripts/rag/requirements-ocr-windows.txt before rebuilding OCR sidecars."
        ) from exc

    storage_file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await storage_file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_language(Language(language))
    if engine is None:
        raise RuntimeError(f"Windows OCR language pack is unavailable: {language}")
    result = await engine.recognize_async(bitmap)
    lines: list[str] = []
    for line in result.lines:
        words = list(line.words)
        if language.lower().startswith("ar"):
            # Windows OCR exposes Arabic words in physical left-to-right
            # order. Reversing by x-coordinate restores natural RTL order.
            words.sort(key=lambda word: word.bounding_rect.x, reverse=True)
        else:
            words.sort(key=lambda word: word.bounding_rect.x)
        value = " ".join(word.text.strip() for word in words if word.text.strip())
        if value:
            lines.append(value)
    return "\n".join(lines)


async def build_sidecar(pdf_path: Path, output_path: Path, *, language: str, scale: float) -> None:
    document = pdfium.PdfDocument(pdf_path)
    render_dir = output_path.parent / f".{output_path.stem}-pages"
    render_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    try:
        for page_index in range(len(document)):
            page_number = page_index + 1
            image_path = render_dir / f"page-{page_number:03d}.png"
            page = document[page_index]
            page.render(scale=scale).to_pil().save(image_path)
            text = await _ocr_image(image_path, language)
            rows.append(
                {
                    "page": page_number,
                    "text": text,
                    "language": language,
                    "engine": "Windows.Media.Ocr",
                    "source_pdf": pdf_path.as_posix(),
                }
            )
            print(f"OCR page {page_number}/{len(document)}: {len(text)} chars", flush=True)
    finally:
        document.close()
        for image_path in render_dir.glob("*.png"):
            image_path.unlink(missing_ok=True)
        render_dir.rmdir()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a page-preserving Windows Arabic OCR sidecar for a PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--language", default="ar-SA")
    parser.add_argument("--scale", type=float, default=2.5, help="PDF render scale; 2.5 is roughly 180 dpi.")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This helper uses the installed Windows OCR language packs and must run on Windows.")
    asyncio.run(build_sidecar(args.pdf, args.output, language=args.language, scale=args.scale))


if __name__ == "__main__":
    main()
