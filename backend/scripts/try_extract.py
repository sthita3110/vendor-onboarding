"""Read one document with OpenAI and print what came back.

Run from backend/:
  python -m scripts.try_extract data/samples/H1/gst_certificate.pdf
  python -m scripts.try_extract path/to/file.pdf --slot bank_proof --model gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from app.config import get_settings
from app.llm.client import OpenAIReader
from app.llm.extract import MIME_BY_EXT, UploadedFile, read_document


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--slot", default="gst_certificate", help="upload slot the file was placed in")
    ap.add_argument("--model", help="override OPENAI_MODEL")
    args = ap.parse_args()

    settings = get_settings()
    if args.model:
        settings = replace(settings, openai_model=args.model)
    reader = OpenAIReader(settings)
    upload = UploadedFile(args.slot, args.path.name, args.path.read_bytes(), MIME_BY_EXT[args.path.suffix.lower()])
    ex = read_document(reader, upload)

    print(json.dumps(ex.meta, indent=2))
    print(ex.document.model_dump_json(indent=2, exclude_none=True))


if __name__ == "__main__":
    main()
