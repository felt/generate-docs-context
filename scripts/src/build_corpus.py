"""
Walk a documentation repository and emit corpus.md — every published page concatenated, with each
H1 and H2 carrying the URL it is published at so a model reading the corpus can cite it verbatim.
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

# When a heading is renamed GitBook pins its original anchor with explicit markup so existing links
# keep working. Where that is present it overrides the slug, and the markup itself is not content.
HEADING_ANCHOR = re.compile(r'\s*<a href="#([^"]*)" id="[^"]*"></a>')

# Collapsible FAQ entries. GitBook publishes the summary as a heading, so render it as one rather
# than leaving <details> markup in the corpus.
DETAILS_BLOCK = re.compile(r"<details>.*?</details>", re.DOTALL)
DETAILS_WRAP = re.compile(r"\n*</?details>\n*")
DETAILS_SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)

# A comment on the first column of a fenced block is not a heading, however much it looks like one.
CODE_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)

TABLE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL)
TABLE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
TABLE_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.DOTALL)
CELL_LINK = re.compile(r'<a href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
LIST_ITEM = re.compile(r"</li>\s*<li[^>]*>")
LINE_BREAK = re.compile(r"<br\s*/?>")
CODE_TAG = re.compile(r"</?code>")
ANY_TAG = re.compile(r"<[^>]+>")

SUMMARY_ENTRY = re.compile(r"^\s*\*\s*\[[^\]]+\]\(([^)#]+\.md)\)", re.MULTILINE)
HEADING = re.compile(r"^(#{1,2}) +(\S.*?)[ \t]*$", re.MULTILINE)
PLACEHOLDER = re.compile(r"\x00(\d+)\x00")

MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
AMPERSAND = re.compile(r"(?:&amp;|&)")

# GitBook truncates heading anchors at 100 characters, mid-word if it lands there.
ANCHOR_MAX = 100


def anchor(text: str) -> str:
    """Slugify heading text the way GitBook anchors it.

    Derived by diffing against every published page's anchors, so the surprises are load-bearing:
    periods survive (`seats-vs.-permissions`), `&` spells out, apostrophes vanish rather than
    separating, a link contributes only its text, and a slug that would start with a digit is
    prefixed to keep it a valid identifier (`id-1.-getting-data-into-felt`).
    """
    slug = MD_LINK.sub(r"\1", text).lower().replace("'", "").replace("’", "")
    slug = AMPERSAND.sub(" and ", slug)
    slug = re.sub(r"[^a-z0-9.]+", "-", slug).strip("-")
    if slug[:1].isdigit():
        slug = f"id-{slug}"
    return slug[:ANCHOR_MAX]


def cell_text(cell: str) -> str:
    text = CELL_LINK.sub(
        lambda m: f"[{ANY_TAG.sub('', m.group(2)).strip()}]({m.group(1)})", cell
    )
    text = LIST_ITEM.sub("; ", text)
    text = LINE_BREAK.sub(" ", text)
    text = CODE_TAG.sub("`", text)
    text = ANY_TAG.sub("", text)
    return re.sub(r"\s+", " ", text).replace("|", r"\|").strip()


def table_to_markdown(match: re.Match[str]) -> str:
    rows = [
        [cell_text(c) for c in TABLE_CELL.findall(row)]
        for row in TABLE_ROW.findall(match.group(0))
    ]
    rows = [r for r in rows if r]
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header, *body = rows
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n" + "\n".join(lines) + "\n"


class CorpusBuilder:
    """
    Collects every published documentation page, strips GitBook markup, annotates its headings with
    the URLs they are published at, and joins the results into a single markdown corpus.
    """

    def __init__(
        self,
        docs_root: Path,
        output: Path,
        base_url: str,
        exclude: tuple[str, ...] = (),
    ):
        self.docs_root = docs_root
        self.output = output
        self.base_url = base_url.rstrip("/")
        self.exclude = exclude

    def published(self) -> list[Path]:
        """Pages listed in SUMMARY.md, GitBook's table of contents, in nav order.

        SUMMARY.md is the only statement of what is actually published. Walking the repo instead
        sweeps in files that have no page behind them — a style guide, a `.claude` skill — and mints
        plausible URLs for them that 404.

        `exclude` then drops pages that are published but not worth answering from. Legal text is
        the case it exists for: a model paraphrasing a contract is worse than one saying the docs
        do not cover it, and the page is still a click away on the site.
        """
        summary = self.docs_root / "SUMMARY.md"
        if not summary.is_file():
            sys.exit(
                f"no SUMMARY.md in {self.docs_root}; cannot tell which pages are published"
            )

        pages = []
        for rel in SUMMARY_ENTRY.findall(summary.read_text(encoding="utf-8")):
            if any(rel.startswith(prefix) for prefix in self.exclude):
                continue
            path = (self.docs_root / rel).resolve()
            if not path.is_file():
                print(
                    f"warning: SUMMARY.md lists {rel}, which does not exist",
                    file=sys.stderr,
                )
                continue
            if path not in pages:
                pages.append(path)
        return pages

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
        text = TABLE.sub(table_to_markdown, text)
        text = re.sub(r"\n[ \t]+\n", "\n\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def annotate(self, text: str, url: str) -> str:
        """Append to each H1 and H2 the URL it is published at.

        The page's own title heading gets the page URL, so it doubles as the article's boundary
        marker; every other heading gets its anchor. H3 and below are left alone — they are mostly
        list-ish subdivisions, and the URLs are not free.

        Headings nested inside a <details> block are skipped: GitBook renders those collapsed and
        gives them no anchor, so a link to one would land at the top of the page. Fenced code is
        skipped too, so that a `# comment` in a shell or Python sample is not mistaken for one.
        """
        collapsed: list[str] = []

        def stash(match: re.Match[str]) -> str:
            collapsed.append(match.group(0))
            return f"\x00{len(collapsed) - 1}\x00"

        text = CODE_FENCE.sub(stash, DETAILS_BLOCK.sub(stash, text))
        seen_title = False

        def annotate_heading(match: re.Match[str]) -> str:
            nonlocal seen_title
            hashes, heading = match.group(1), match.group(2)
            pinned = HEADING_ANCHOR.search(heading)
            heading = HEADING_ANCHOR.sub("", heading).strip()
            if hashes == "#" and not seen_title:
                seen_title = True
                return f"{hashes} {heading} — {url}"
            return f"{hashes} {heading} — {url}#{pinned.group(1) if pinned else anchor(heading)}"

        text = HEADING.sub(annotate_heading, text)
        return PLACEHOLDER.sub(lambda m: collapsed[int(m.group(1))], text)

    def collapse_details(self, text: str) -> str:
        """Flatten GitBook collapsibles, promoting each summary to the heading it renders as."""
        text = DETAILS_SUMMARY.sub(r"### \1", text)
        return DETAILS_WRAP.sub("\n\n", text)

    def pages(self) -> list[str]:
        parts: list[str] = []
        for path in self.published():
            body = self.clean(path.read_text(encoding="utf-8"))
            if not body:
                continue
            parts.append(
                self.collapse_details(self.annotate(body, self.file_to_url(path)))
            )
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
        "--exclude",
        default="",
        help="comma- or newline-separated path prefixes to leave out, e.g. terms-and-policy/",
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

    exclude = tuple(
        p.strip() for p in args.exclude.replace("\n", ",").split(",") if p.strip()
    )

    output = args.output or docs_root / "corpus.md"
    CorpusBuilder(docs_root, output, args.base_url, exclude).build()


if __name__ == "__main__":
    main()
