#!/bin/sh
# Render DOCUMENT.md -> DOCUMENT.pdf. Needs pandoc and node + playwright (chromium).
# Usage: sh scripts/build_pdf.sh        (run from the repo root)
set -e
TMP="$(mktemp -d)"
pandoc DOCUMENT.md -f gfm -t html5 --standalone --embed-resources --resource-path=. \
  --metadata title="Routine Architect" --css scripts/pdf.css -o "$TMP/doc.html"
# pandoc adds a title block for --standalone; the document already has its own H1
sed -i '/<header id="title-block-header">/,/<\/header>/d' "$TMP/doc.html"
node -e '
const { chromium } = require("playwright");
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  await p.goto("file://" + process.argv[1]);
  await p.pdf({ path: "DOCUMENT.pdf", format: "A4", printBackground: true, displayHeaderFooter: true,
    headerTemplate: "<span></span>",
    footerTemplate: "<div style=\"font-size:8px;width:100%;text-align:center;color:#78716c\">Routine Architect &middot; <span class=pageNumber></span> / <span class=totalPages></span> &middot; not medical advice</div>",
    margin: { top: "18mm", bottom: "20mm", left: "16mm", right: "16mm" } });
  await b.close();
})();' "$TMP/doc.html"
rm -rf "$TMP"; echo "wrote DOCUMENT.pdf"
