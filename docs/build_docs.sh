#!/usr/bin/env bash
# Regenerate the Word copies of the transition documents from their Markdown
# masters. Edit the .md files, not the .docx: Word-only edits are lost on the
# next rebuild.
#
#   bash docs/build_docs.sh
#
# Needs pandoc (2.x or 3.x) and python3. Styles (fonts, headings, colours) come
# from docs/reference.docx; table borders and callout boxes are added by
# docs/style_docx.py.
set -euo pipefail
cd "$(dirname "$0")"

for doc in SOP_Build_and_Use Project_Handover; do
    pandoc "$doc.md" \
        --from markdown \
        --to docx \
        --reference-doc reference.docx \
        --resource-path . \
        --output "$doc.docx"
    python3 style_docx.py "$doc.docx"
    echo "Built docs/$doc.docx"
done
