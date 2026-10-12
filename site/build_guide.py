"""Copies the app's user guide (static/guide.html) into the public site, as site/guide/.

In the app, /guide needs a signed-in user; on the site it is public. Run it again after the guide
changes:

    .venv\\Scripts\\python.exe site\\build_guide.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
OUT = ROOT / "site" / "guide"

REPLACEMENTS = [
    ('<link rel="stylesheet" href="/static/app.css">', '<link rel="stylesheet" href="app.css">'),
    # The in-app assistant needs a signed-in user: not on the public site.
    ('<script src="/static/assistant.js" defer></script>\n', ""),
    ('href="/static/favicon.svg"', 'href="../favicon.svg"'),
    ("/static/guide/", ""),
    ('<a class="brand" href="/"', '<a class="brand" href="../index.html"'),
    ('<a class="back" href="/">← Retour à l\'application</a>', '<a class="back" href="../index.html">← Retour au site</a>'),
]


def main() -> None:
    html = (STATIC / "guide.html").read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        if old not in html:
            raise SystemExit(f"Guide changed, update build_guide.py: not found {old!r}")
        html = html.replace(old, new)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    shutil.copy2(STATIC / "app.css", OUT / "app.css")
    for image in (STATIC / "guide").glob("*.png"):
        shutil.copy2(image, OUT / image.name)
    print(f"Guide copied to {OUT}")


if __name__ == "__main__":
    main()
