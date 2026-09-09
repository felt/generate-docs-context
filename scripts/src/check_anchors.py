"""
Check every heading URL in a built corpus against the anchors the published pages actually serve.

`build_corpus.anchor/1` reproduces GitBook's slugification, which is not documented anywhere — it
was derived by diffing against live pages. This is what keeps that rule honest when GitBook changes
it or a page grows a heading that slugs differently than expected.
"""

import argparse
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HEADING_URL = re.compile(r"^#{1,2} .* — (https://\S+)$", re.MULTILINE)
LIVE_ANCHOR = re.compile(r'href="#([^"]+)"')

# GitBook serves 403 to an unadorned urllib user agent.
USER_AGENT = "Mozilla/5.0 (felt generate-docs-context anchor check)"


def live_anchors(page: str) -> tuple[str, set[str] | None]:
    request = urllib.request.Request(page, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return page, set(
                LIVE_ANCHOR.findall(response.read().decode("utf-8", "replace"))
            )
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"could not fetch {page}: {error}", file=sys.stderr)
        return page, None


def main():
    parser = argparse.ArgumentParser(
        description="Verify a corpus's heading anchors resolve"
    )
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args()

    emitted: dict[str, set[str]] = {}
    for url in HEADING_URL.findall(args.corpus.read_text(encoding="utf-8")):
        page, _, fragment = url.partition("#")
        emitted.setdefault(page, set())
        if fragment:
            emitted[page].add(fragment)

    with ThreadPoolExecutor(8) as pool:
        live = dict(pool.map(live_anchors, sorted(emitted)))

    wrong = unreachable = 0
    for page, anchors in sorted(emitted.items()):
        if live[page] is None:
            unreachable += 1
            continue
        for missing in sorted(anchors - live[page]):
            wrong += 1
            print(f"{page}#{missing} does not exist on the page")

    checked = sum(len(a) for a in emitted.values())
    print(
        f"{len(emitted)} pages, {checked} anchors: {checked - wrong} resolve, {wrong} do not, {unreachable} pages unreachable"
    )
    sys.exit(1 if wrong or unreachable else 0)


if __name__ == "__main__":
    main()
