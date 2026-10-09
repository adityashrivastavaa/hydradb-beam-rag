"""Inline the deck's fonts and images into one offline file: deck/index.html.

  python deck/build.py

Edit deck.template.html, then rebuild. Assets live in deck/assets/.
"""
import base64
from pathlib import Path

HERE = Path(__file__).parent
ASSETS = HERE / "assets"


def b64(name: str) -> str:
    return base64.b64encode((ASSETS / name).read_bytes()).decode()


def main():
    html = (HERE / "deck.template.html").read_text()
    for key, value in {
        "GEIST_400": b64("geist-sans-400.woff2"),
        "GEIST_500": b64("geist-sans-500.woff2"),
        "LOCKUP": "data:image/png;base64," + b64("hydradb-lockup.png"),
        "VECTOR_VS_GRAPH": "data:image/png;base64," + b64("vector-vs-graph.png"),
        "ACCURACY": "data:image/png;base64," + b64("accuracy-vs-context.png"),
    }.items():
        html = html.replace("{{" + key + "}}", value)
    assert "{{" not in html, "unreplaced placeholder"
    out = HERE / "index.html"
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
