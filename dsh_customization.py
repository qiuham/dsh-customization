#!/usr/bin/env python3
"""Install or undo the verified DSH 0.1.5-rc.2 customization.

Only exact, known package builds are patched. User settings are never copied
into this repository; backups stay under DSH_HOME.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "framework-manifest.json").read_text())
BACKUP_NAME = ".dsh-customization-backup"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package_root():
    binary = shutil.which("dsh")
    if not binary:
        raise RuntimeError("dsh is not on PATH")
    return Path(binary).resolve().parent.parent


def targets(pkg):
    base = pkg / "node_modules" / "@deepseek-ai"
    return [(base / row["path"], row) for row in MANIFEST]


def check_version(pkg):
    version = json.loads((pkg / "package.json").read_text())["version"]
    if version != "0.1.5-rc.2":
        raise RuntimeError(f"expected DSH 0.1.5-rc.2, got {version}")


def permission_settings(data):
    text = data.decode("utf-8")
    match = re.search(r"(?m)^permission:\s*$", text)
    if not match:
        return (text.rstrip("\n") + "\npermission:\n  defaultPreset: danger-full-access\n").encode()
    end = re.search(r"(?m)^\S", text[match.end():])
    stop = match.end() + end.start() if end else len(text)
    block = text[match.end():stop]
    if re.search(r"(?m)^  defaultPreset:\s*", block):
        block = re.sub(r"(?m)^(  defaultPreset:)\s*[^\n]*", r"\1 danger-full-access", block)
    else:
        block = "\n  defaultPreset: danger-full-access" + block
    return (text[:match.end()] + block + text[stop:]).encode()


def rendered_template(name, replacements=None):
    text = (ROOT / "templates" / name).read_text()
    for source, target in (replacements or {}).items():
        text = text.replace(source, target)
    return text.encode()


def user_files(home):
    web = home / "profiles" / "web"
    plugin = home / "plugins" / "instruction-hygiene.mjs"
    return {
        home / "settings.yaml": permission_settings,
        home / "AGENTS.md": lambda _: (ROOT / "templates" / "AGENTS.md").read_bytes(),
        home / "profiles" / "default" / "cordis.patch.yml": lambda _: rendered_template("profile-default.patch.yml"),
        home / "profiles" / "headless" / "cordis.patch.yml": lambda _: rendered_template("profile-headless.patch.yml"),
        plugin: lambda _: rendered_template("plugins/instruction-hygiene.mjs"),
        web / "cordis.patch.yml": lambda _: rendered_template(
            "cordis.patch.yml",
            {"__INSTRUCTION_HYGIENE_PLUGIN__": str(plugin)},
        ),
        web / "package.json": lambda _: (ROOT / "templates" / "package.json").read_bytes(),
        web / "pnpm-lock.yaml": lambda _: (ROOT / "templates" / "pnpm-lock.yaml").read_bytes(),
    }


def read_optional(path):
    return path.read_bytes() if path.exists() else None


def apply(pkg, home, install_plugins):
    check_version(pkg)
    backup = home / BACKUP_NAME
    if backup.exists():
        raise RuntimeError(f"backup already exists: {backup}; run --status or --rollback")
    edits = []
    with tempfile.TemporaryDirectory() as temporary:
        for index, (path, row) in enumerate(targets(pkg)):
            before = path.read_bytes()
            actual = digest(before)
            if actual not in (row["original"], row["modified"]):
                raise RuntimeError(f"unrecognized package file: {path}: {actual}")
            if actual == row["modified"]:
                continue
            stage = Path(temporary) / f"target-{index}"
            stage.write_bytes(before)
            result = subprocess.run(
                ["patch", "--silent", "--batch", "--forward", str(stage), str(ROOT / "patches" / row["patch"])],
                capture_output=True, text=True,
            )
            if result.returncode or digest(stage.read_bytes()) != row["modified"]:
                raise RuntimeError(f"patch failed: {path}: {result.stdout}{result.stderr}")
            edits.append((path, before, stage.read_bytes()))
        for path, transform in user_files(home).items():
            before = read_optional(path)
            after = transform(before or b"")
            if before != after:
                edits.append((path, before, after))
        if not edits:
            print("already customized; no changes")
            return
        backup.mkdir(mode=0o700)
        records = []
        try:
            for index, (path, before, after) in enumerate(edits):
                path.parent.mkdir(parents=True, exist_ok=True)
                if before is not None:
                    (backup / str(index)).write_bytes(before)
                records.append({"path": str(path), "backup": str(index) if before is not None else None,
                                "original": digest(before) if before is not None else None,
                                "modified": digest(after)})
            (backup / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
            for path, before, after in edits:
                staged = path.with_name(path.name + ".dsh-customization-new")
                staged.write_bytes(after)
                if before is not None:
                    staged.chmod(path.stat().st_mode & 0o777)
                os.replace(staged, path)
            if install_plugins:
                subprocess.run(["pnpm", "--dir", str(home / "profiles" / "web"), "install", "--frozen-lockfile"], check=True)
            print(f"applied {len(edits)} files; backup={backup}")
        except BaseException:
            rollback(home, strict=False)
            raise


def rollback(home, strict=True):
    backup = home / BACKUP_NAME
    records = json.loads((backup / "manifest.json").read_text())
    if strict:
        for entry in records:
            path = Path(entry["path"])
            if read_optional(path) is None or digest(path.read_bytes()) != entry["modified"]:
                raise RuntimeError(f"modified since installation; refusing rollback: {path}")
    for entry in reversed(records):
        path = Path(entry["path"])
        original = entry["backup"]
        if original is None:
            path.unlink(missing_ok=True)
        else:
            staged = path.with_name(path.name + ".dsh-customization-restore")
            staged.write_bytes((backup / original).read_bytes())
            if path.exists():
                staged.chmod(path.stat().st_mode & 0o777)
            os.replace(staged, path)
    shutil.rmtree(backup)
    print(f"restored {len(records)} files; backup removed")


def status(pkg, home):
    check_version(pkg)
    for path, row in targets(pkg):
        actual = digest(path.read_bytes())
        state = "original" if actual == row["original"] else "modified" if actual == row["modified"] else "unknown"
        print(f"{row['path']}: {state}")
    print(f"backup: {'present' if (home / BACKUP_NAME).exists() else 'absent'}")
    settings = read_optional(home / "settings.yaml") or b""
    print(f"permission.defaultPreset: {'danger-full-access' if b'defaultPreset: danger-full-access' in settings else 'other'}")
    for path, transform in user_files(home).items():
        current = read_optional(path)
        expected = transform(current or b"")
        state = "configured" if current == expected else "drifted"
        print(f"user.{path.relative_to(home)}: {state}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--rollback", action="store_true")
    parser.add_argument("--dsh-package", type=Path, default=None)
    parser.add_argument("--dsh-home", type=Path, default=Path(os.getenv("DSH_HOME", "~/.dsh")).expanduser())
    parser.add_argument("--skip-plugins", action="store_true", help="skip pnpm install (for offline fixtures)")
    args = parser.parse_args()
    pkg = args.dsh_package or package_root()
    if args.apply:
        apply(pkg, args.dsh_home, not args.skip_plugins)
    elif args.rollback:
        rollback(args.dsh_home)
    else:
        status(pkg, args.dsh_home)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
