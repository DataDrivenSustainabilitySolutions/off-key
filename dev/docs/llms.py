"""Publish the documentation for language models, after `zensical build`.

Copies every page's Markdown source next to the built site (getting-started.md
beside getting-started/index.html), then writes llms.txt, an index in the
llmstxt.org format that follows the zensical.toml navigation, and
llms-full.txt, every page in that order in one file.
"""

import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def pages(nav, section=None):
    """Yield (section, title, path) for each page of the navigation."""
    for entry in nav:
        for title, target in entry.items():
            if isinstance(target, list):
                yield from pages(target, title)
            else:
                yield section, title, target


def summary(markdown):
    """First sentence of the first prose paragraph."""
    for block in re.split(r"\n\s*\n", markdown):
        block = block.strip()
        if block and not block.startswith(("#", "!!!", "|", "```", "-", ">")):
            text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", " ".join(block.split()))
            return re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return ""


def main(site_dir):
    project = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]
    docs, site = ROOT / project["docs_dir"], Path(site_dir)
    base = project["site_url"].rstrip("/")
    entries = list(pages(project["nav"]))

    index = [f"# {project['site_name'].capitalize()} documentation", ""]
    index += [f"> {project['site_description']}", ""]
    index.append(
        "Each link is the Markdown source of a documentation page. "
        f"[llms-full.txt]({base}/llms-full.txt) holds all of them in one file."
    )
    full = [f"# {project['site_name'].capitalize()} documentation", ""]
    current = object()
    for section, title, path in entries:
        text = (docs / path).read_text()
        target = site / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(docs / path, target)
        if section != current:
            index += ["", f"## {section or 'Overview'}", ""]
            current = section
        note = summary(text)
        index.append(f"- [{title}]({base}/{path})" + (f": {note}" if note else ""))
        full += [f"<!-- {base}/{path} -->", text.rstrip(), ""]

    (site / "llms.txt").write_text("\n".join(index) + "\n")
    (site / "llms-full.txt").write_text("\n".join(full))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "site")
