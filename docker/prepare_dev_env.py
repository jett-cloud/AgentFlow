from __future__ import annotations

import argparse
import os
import re
import secrets
from pathlib import Path


PLACEHOLDER_PATTERN = re.compile(r"CHANGE_ME_[A-Z0-9_]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create docker/.env with unique local secrets.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name(".env"),
        help="Destination file (default: docker/.env)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    template = Path(__file__).with_name(".env.example")
    output = args.output.resolve()

    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {output}")

    content = template.read_text(encoding="utf-8")
    placeholders = sorted(set(PLACEHOLDER_PATTERN.findall(content)))
    if not placeholders:
        raise SystemExit(f"No CHANGE_ME placeholders found in {template}")

    replacements = {placeholder: secrets.token_urlsafe(32) for placeholder in placeholders}
    generated = PLACEHOLDER_PATTERN.sub(lambda match: replacements[match.group(0)], content)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generated, encoding="utf-8", newline="\n")
    if os.name != "nt":
        output.chmod(0o600)

    print(f"Created {output} with {len(replacements)} generated local secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
