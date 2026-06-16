# generate-docs-context

A composite GitHub Action that walks a documentation repository, strips GitBook
markup, concatenates every page into a single `corpus.md` (with `# Source:` URL
headers per page), and uploads it to S3.

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

## Prerequisites

- **OIDC trust policy**: the `GithubActionsRole` trust policy must permit the
  `sub` for each calling repo (`repo:felt/<name>:*`).

## Local development

```sh
cd scripts
uv run build-corpus --docs-root /path/to/docs --base-url https://developer.felt.com -o /tmp/corpus.md
```
