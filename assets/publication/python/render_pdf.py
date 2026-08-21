import argparse
import json
from pathlib import Path

from weasyprint import HTML


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("assembly", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("regular", type=Path)
    parser.add_argument("bold", type=Path)
    parser.add_argument("css", type=Path)
    args = parser.parse_args()
    assembly = json.loads(args.assembly.read_text(encoding="utf-8"))
    css = args.css.read_text(encoding="utf-8")
    css = css.replace("FONT_REGULAR", args.regular.as_uri()).replace("FONT_BOLD", args.bold.as_uri())
    chapters = "".join(chapter["xhtml"] for chapter in assembly["chapters"])
    document = (
        '<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        '<title>{title}</title><meta name="author" content="{author}"><style>{css}</style>'
        '</head><body>{chapters}</body></html>'
    ).format(language=assembly["language"], title=assembly["title_html"], author=assembly["author_html"], css=css, chapters=chapters)
    identifier = bytes.fromhex(assembly["hash"])[:16]
    PDF = HTML(string=document).write_pdf(
        pdf_identifier=identifier,
        full_fonts=True,
        optimize_images=False,
        presentational_hints=False,
        uncompressed_pdf=False,
    )
    args.output.write_bytes(PDF)


if __name__ == "__main__":
    main()
