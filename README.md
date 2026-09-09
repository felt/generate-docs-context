# generate-docs-context

A composite GitHub Action that collects a documentation repository's published
pages, strips GitBook markup, concatenates them into a single `corpus.md`, and
uploads it to S3.

The corpus is written for a language model to read and cite, so every H1 and H2
carries the URL it is published at:

```markdown
# Billing — https://help.felt.com/administration/billing

## Billing plans — https://help.felt.com/administration/billing#billing-plans
```

A model answering from the corpus can then quote a link to the exact section it
used, without being told how the docs site builds its URLs.

Which pages are published comes from `SUMMARY.md`, GitBook's table of contents —
not from walking the tree, which sweeps in files that have no page behind them
and mints URLs for them that 404.

Pages GitBook hides are left out too. A hidden page still renders at its URL but
is `noindex` and absent from the nav, search and sitemap, so it is not somewhere
to send a reader. Hiding cascades to everything nested under it in `SUMMARY.md`.

Use `exclude` for pages that are published and visible but still not worth
answering from — legal text is the case it exists for.

## Usage

In a docs repository, add a workflow such as `.github/workflows/build-corpus.yml`:

```yaml
name: Build Corpus
on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read
  id-token: write

jobs:
  build-corpus:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: felt/generate-docs-context@v1
        with:
          base-url: "https://..."
          s3-key: "public/.../corpus.md"
          bucket: "..."
          role-arn: "arn:aws:..."
```

## Inputs

Input | Required | Description
--- | --- | ---
`base-url` | yes | Base URL the docs are published under.
`s3-key` | yes | Destination object key (path within the bucket).
`bucket` | yes | Destination S3 bucket.
`role-arn` | yes | IAM role assumed via GitHub OIDC.
`exclude` | no | Comma- or newline-separated path prefixes to leave out, e.g. `terms-and-policy/`.
`docs-path` | no | Subdirectory to walk, relative to the repo root.

## Prerequisites

- **OIDC trust policy**: the `GithubActionsRole` trust policy must permit the
  `sub` for each calling repo (`repo:felt/<name>:*`).

## Local development

```sh
cd scripts
uv run build-corpus --docs-root /path/to/docs --base-url https://developer.felt.com -o /tmp/corpus.md
uv run check-anchors /tmp/corpus.md
```

`check-anchors` fetches every page the corpus cites and verifies its heading
anchors exist. GitBook does not document how it slugifies a heading, so
`anchor/1` reproduces it by observation — periods survive, `&` spells out,
apostrophes vanish, a renamed heading keeps its pinned anchor. Run this after
touching that function, and when a build starts producing links that miss.
