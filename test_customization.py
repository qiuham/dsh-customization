import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from dsh_customization import package_root


ROOT = Path(__file__).resolve().parent
ROWS = json.loads((ROOT / "framework-manifest.json").read_text())


def run(action, package, home):
    return subprocess.run(["python3", str(ROOT / "dsh_customization.py"), action,
                           "--dsh-package", str(package), "--dsh-home", str(home),
                           "--skip-plugins"], capture_output=True, text=True)


class Reproduction(unittest.TestCase):
    def test_baseline_apply_rollback_on_separate_copy(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            pkg = root / "dsh"
            home = root / "home"
            (pkg / "package.json").parent.mkdir(parents=True)
            (pkg / "package.json").write_text('{"version":"0.1.5-rc.2"}\n')
            for row in ROWS:
                file = pkg / "node_modules" / "@deepseek-ai" / row["path"]
                file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(package_root() / "node_modules" / "@deepseek-ai" / row["path"], file)
                if hashlib.sha256(file.read_bytes()).hexdigest() == row["modified"]:
                    result = subprocess.run(["patch", "--silent", "--batch", "--reverse",
                                             str(file), str(ROOT / "patches" / row["patch"])],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), row["original"])
            home.mkdir()
            original_settings = b"other:\n  keep: yes\npermission:\n  defaultPreset: read-only\n"
            (home / "settings.yaml").write_bytes(original_settings)

            baseline = run("--status", pkg, home)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertEqual(baseline.stdout.count(": original"), 8)
            print("BASELINE:", "framework=original:8 backup=absent exit=0")

            applied = run("--apply", pkg, home)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            modified = run("--status", pkg, home)
            self.assertEqual(modified.returncode, 0, modified.stderr)
            self.assertEqual(modified.stdout.count(": modified"), 8)
            self.assertIn("permission.defaultPreset: danger-full-access", modified.stdout)
            self.assertIn(b"keep: yes", (home / "settings.yaml").read_bytes())
            self.assertIn(b"specifier: github:Minglink/dsh-infinite-gen-4#0a46fde", (home / "profiles/web/pnpm-lock.yaml").read_bytes())
            self.assertIn(b"hands-on coding agent", (home / "profiles/default/cordis.patch.yml").read_bytes())
            self.assertIn(b"hands-on coding agent", (home / "profiles/headless/cordis.patch.yml").read_bytes())
            self.assertIn(str(home / "plugins/instruction-hygiene.mjs"), (home / "profiles/web/cordis.patch.yml").read_text())
            self.assertTrue((home / "plugins/instruction-hygiene.mjs").exists())
            self.assertIn("backup: present", modified.stdout)
            self.assertIn("user.profiles/default/cordis.patch.yml: configured", modified.stdout)
            self.assertIn("user.plugins/instruction-hygiene.mjs: configured", modified.stdout)
            print("MODIFIED:", "framework=modified:8 backup=present permission=danger-full-access exit=0")

            pkg_copy = root / "dsh-copy"
            home_copy = root / "home-copy"
            shutil.copytree(pkg, pkg_copy)
            shutil.copytree(home, home_copy)
            manifest = home_copy / ".dsh-customization-backup" / "manifest.json"
            records = json.loads(manifest.read_text())
            for entry in records:
                entry["path"] = entry["path"].replace(str(pkg), str(pkg_copy)).replace(str(home), str(home_copy))
            manifest.write_text(json.dumps(records))

            restored = run("--rollback", pkg_copy, home_copy)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            rolled = run("--status", pkg_copy, home_copy)
            self.assertEqual(rolled.returncode, 0, rolled.stderr)
            self.assertEqual(rolled.stdout.count(": original"), 8)
            self.assertEqual((home_copy / "settings.yaml").read_bytes(), original_settings)
            self.assertFalse((home_copy / "profiles/web/pnpm-lock.yaml").exists())
            self.assertFalse((home_copy / "profiles/default/cordis.patch.yml").exists())
            self.assertFalse((home_copy / "profiles/headless/cordis.patch.yml").exists())
            self.assertFalse((home_copy / "plugins/instruction-hygiene.mjs").exists())
            self.assertIn("backup: absent", rolled.stdout)
            still_modified = run("--status", pkg, home)
            self.assertEqual(still_modified.stdout.count(": modified"), 8)
            print("ROLLBACK:", "copy=original:8 live=modified:8 restored_settings=exact exit=0")

    def test_unknown_package_file_fails_before_modification(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            pkg = root / "dsh"
            home = root / "home"
            pkg.mkdir()
            home.mkdir()
            (pkg / "package.json").write_text('{"version":"0.1.5-rc.2"}\n')
            path = pkg / "node_modules" / "@deepseek-ai" / ROWS[0]["path"]
            path.parent.mkdir(parents=True)
            path.write_bytes(b"unexpected\n")
            failed = run("--apply", pkg, home)
            self.assertEqual(failed.returncode, 1)
            self.assertIn("unrecognized package file", failed.stderr)
            self.assertEqual(path.read_bytes(), b"unexpected\n")
            self.assertFalse((home / ".dsh-customization-backup").exists())

    def test_prompt_hygiene_removes_only_exact_duplicate(self):
        script = r'''import { removeExactDuplicateReinforcement as clean } from "./templates/plugins/instruction-hygiene.mjs";
const primary = { name: "infinite-gen-4:global-system-prompt", text: "same" };
const duplicate = { name: "infinite-gen-4:dual-layer-reinforce", text: "same" };
const distinct = { name: "infinite-gen-4:dual-layer-reinforce", text: "different" };
if (clean({ sections: [primary, duplicate] }).sections.length !== 1) process.exit(1);
if (clean({ sections: [primary, distinct] }).sections.length !== 2) process.exit(2);
console.log("exact_duplicate=removed distinct_reinforcement=retained");'''
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "exact_duplicate=removed distinct_reinforcement=retained")


if __name__ == "__main__":
    unittest.main(verbosity=2)
