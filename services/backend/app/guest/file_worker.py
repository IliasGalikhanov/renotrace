"""Resource-isolated parsing/OCR subprocess. Only temporary scratch files are used."""

import json
import sys

from .extraction import MAX_BYTES, Tesseract, extract_page, inspect


def main() -> None:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    media_type, count = inspect(data)
    if sys.argv[1] == "inspect":
        print(json.dumps({"media_type": media_type, "pages": count}))
    else:
        number = int(sys.argv[2])
        if not 1 <= number <= count:
            raise ValueError("Invalid page")
        print(extract_page(data, media_type, number, Tesseract()).model_dump_json())


if __name__ == "__main__":
    main()
