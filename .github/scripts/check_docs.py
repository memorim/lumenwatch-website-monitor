"""Check tracked Markdown paths/assets; --external also checks public HTTP links."""

import argparse
import concurrent.futures
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


def links(text):
    text = re.sub(r"^\s*(`{3,}|~{3,}).*?^\s*\1\s*$", "", text, flags=re.M | re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    refs = dict(re.findall(r"^\s*\[([^]]+)\]:\s*(\S+)", text, re.M))
    found = re.findall(r"!?\[[^]\n]*\]\(\s*(<[^>]+>|[^)\n]+)\)", text)
    found += [refs.get(key, "") for key in re.findall(r"!?\[[^]\n]*\]\[([^]]+)\]", text)]
    found += re.findall(r"<(https?://[^>]+)>", text)
    found += re.findall(r"<(?:img|a)\b[^>]*\b(?:src|href)=[\"']([^\"']+)", text, re.I)
    return [
        value[1:-1] if value.startswith("<") else re.split(r'\s+["\']', value)[0].strip()
        for value in found
        if value
    ]


def check_document(file, root):
    errors, external = [], set()
    for href in links(file.read_text(encoding="utf-8-sig")):
        url = urlsplit(href)
        if re.match(r"^[A-Za-z]:[\\/]", href) or url.scheme == "file":
            errors.append(f"{file.relative_to(root)}: local machine link: {href}")
        elif url.scheme in {"http", "https"}:
            if not url.hostname:
                errors.append(f"{file.relative_to(root)}: invalid URL: {href}")
            elif url.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
                # Intentional quickstart links are permitted only in code fences/plain text.
                errors.append(f"{file.relative_to(root)}: local hyperlink: {href}")
            else:
                external.add(href.split("#")[0])
        elif not url.scheme and url.path:
            path = unquote(url.path)
            target = (root / path.lstrip("/")) if path.startswith("/") else file.parent / path
            target = target.resolve()
            if not target.is_relative_to(root) or not target.exists():
                errors.append(f"{file.relative_to(root)}: missing path: {href}")
            elif any(
                part not in {p.name for p in parent.iterdir()}
                for parent, part in [(target.parent, target.name)]
            ):
                errors.append(f"{file.relative_to(root)}: path case mismatch: {href}")
    return errors, external


def check_url(url):
    try:
        with urlopen(
            Request(url, headers={"User-Agent": "Portfolio-docs-check/1.0"}), timeout=15
        ) as response:
            return url, "ok", response.status
    except HTTPError as error:
        # Authentication/rate limits/anti-bot replies do not prove a broken link.
        return url, "broken" if error.code in {404, 410} else "unverified", error.code
    except (URLError, TimeoutError, OSError):
        return url, "unverified", "network"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.md"]
        )
        .decode("utf-8")
        .split("\0")
    )
    errors, external = [], set()
    files = sorted({root / name for name in tracked if name})
    for file in files:
        found, urls = check_document(file, root)
        errors.extend(found)
        external.update(urls)
    if args.external:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            for url, state, code in pool.map(check_url, sorted(external)):
                print(f"HTTP {state} {code}: {url}")
                if state == "broken":
                    errors.append(f"Broken HTTP link: {url}")
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Markdown files: {len(files)}; public URLs: {len(external)}; errors: {len(errors)}")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
