"""
Walk a documentation repository and emit corpus.md — one big concatenated doc with `# Source:` headers per page.
"""

import argparse
import os
import re
import sys
from pathlib import Path

FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
FIGURE = re.compile(r"<figure[^>]*>.*?</figure>", re.DOTALL)
NAV_CARDS = re.compile(r'<table\s+data-view="cards"[^>]*>.*?</table>', re.DOTALL)
HINT_OPEN = re.compile(r'\{%\s*hint\s+style="[^"]+"\s*%\}')
HINT_CLOSE = re.compile(r"\{%\s*endhint\s*%\}")
COLUMNS_WRAP = re.compile(r"\{%\s*(?:end)?columns?\s*%\}")
EMBED = re.compile(r'\{%\s*embed\s+url="[^"]+"\s*%\}')
GITBOOK_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\.gitbook/assets/[^)]+\)")
DIV_WRAP = re.compile(r"<div[^>]*>|</div>")


class CorpusBuilder:
    """
    Collects every documentation page, strips GitBook markup, and joins the results into a single markdown corpus.
    """

    skip_files = {"SUMMARY.md"}
    skip_dirs = {".claude", ".gitbook", ".git", ".github", "scripts"}

    def __init__(
        self,
        docs_root: Path,
        output: Path,
        base_url: str,
    ):
        self.docs_root = docs_root
        self.output = output
        self.base_url = base_url.rstrip("/")

    def file_to_url(self, path: Path) -> str:
        rel = path.relative_to(self.docs_root).as_posix().removesuffix(".md")
        if rel == "README":
            return self.base_url + "/"
        if rel.endswith("/README"):
            rel = rel[: -len("/README")]
        return f"{self.base_url}/{rel}"

    def clean(self, text: str) -> str:
        text = FRONTMATTER.sub("", text)
        text = NAV_CARDS.sub("", text)
        text = FIGURE.sub("", text)
        text = HINT_OPEN.sub("", text)
        text = HINT_CLOSE.sub("", text)
        text = COLUMNS_WRAP.sub("", text)
        text = EMBED.sub("", text)
        text = GITBOOK_IMG.sub("", text)
        text = DIV_WRAP.sub("", text)
        text = re.sub(r"\n[ \t]+\n", "\n\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def pages(self) -> list[str]:
        parts: list[str] = []
        for path in sorted(self.docs_root.rglob("*.md")):
            rel_parts = path.relative_to(self.docs_root).parts
            if any(d in rel_parts for d in self.skip_dirs):
                continue
            if path.name in self.skip_files:
                continue
            body = self.clean(path.read_text(encoding="utf-8"))
            if not body:
                continue
            parts.append(f"# Source: {self.file_to_url(path)}\n\n{body}")
        return parts

    def build(self) -> str:
        parts = self.pages()
        output = "\n\n---\n\n".join(parts)
        self.output.write_text(output, encoding="utf-8")
        print(f"Wrote {self.output}: {len(parts)} pages, {len(output):,} chars")
        return output


def main():
    parser = argparse.ArgumentParser(
        description="Bundle documentation pages into a single markdown corpus"
    )
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=Path(os.environ.get("GITHUB_WORKSPACE", ".")),
        help="root of the docs repository to walk (default: $GITHUB_WORKSPACE or cwd)",
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="base URL the docs are published under, e.g. https://developer.felt.com",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="path to write the corpus to (default: <docs-root>/corpus.md)",
    )
    args = parser.parse_args()

    docs_root = args.docs_root.resolve()
    if not docs_root.is_dir():
        sys.exit(f"docs root not found: {docs_root}")

    output = args.output or docs_root / "corpus.md"
    CorpusBuilder(docs_root, output, args.base_url).build()


if __name__ == "__main__":
    main()
