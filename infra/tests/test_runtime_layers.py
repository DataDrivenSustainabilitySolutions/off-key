"""Image layering must preserve the complete installed runtime and executable modes."""

import importlib.util
import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from support import ROOT

spec = importlib.util.spec_from_file_location(
    "split_runtime_layers", ROOT.parent / "backend/scripts/split_runtime_layers.py"
)
layers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layers)


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            path.readlink() if path.is_symlink() else path.read_bytes(),
            stat.S_IMODE(path.lstat().st_mode),
        )
        for path in root.rglob("*")
        if path.is_symlink() or path.is_file()
    }


def environment(root, source):
    site = root / "lib/python3.14/site-packages"
    metadata = site / "example-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text("Name: example\nVersion: 1.0\n")
    (metadata / "direct_url.json").write_text(
        json.dumps({"url": "file:///code/libs/example", "dir_info": {}})
    )
    package = site / "example"
    package.mkdir()
    (package / "__init__.py").write_text(source)
    (package / "data.json").write_text('{"runtime": true}')
    (package / "alias.json").symlink_to("data.json")
    bytecode = package / "__pycache__"
    bytecode.mkdir()
    (bytecode / "__init__.cpython-314.pyc").write_bytes(source.encode())
    executable = root / "bin/example"
    executable.parent.mkdir()
    executable.write_text("#!/app/bin/python\n")
    executable.chmod(0o755)
    (site / "dependency.py").write_text("THIRD_PARTY = True\n")
    (root / "pyvenv.cfg").write_text("home = /usr/local/bin\n")
    # Bytecode need not be in RECORD; a previously pruned package test may be.
    (metadata / "RECORD").write_text(
        "\n".join(
            f"{name},,"
            for name in (
                "example/__init__.py",
                "example/data.json",
                "example/alias.json",
                "example/tests/removed.py",
                "../../../bin/example",
                "example-1.0.dist-info/METADATA",
                "example-1.0.dist-info/direct_url.json",
                "example-1.0.dist-info/RECORD",
            )
        )
    )


class RuntimeLayerTests(unittest.TestCase):
    def test_combined_layers_preserve_all_files_links_and_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependencies, application = root / "dependencies", root / "application"
            environment(dependencies, "APPLICATION = True\n")
            original = snapshot(dependencies)
            layers.split(dependencies, Path("/code"), application)
            self.assertFalse(set(snapshot(dependencies)) & set(snapshot(application)))
            self.assertEqual(original, snapshot(dependencies) | snapshot(application))
            shutil.copytree(
                application, dependencies, dirs_exist_ok=True, symlinks=True
            )
            self.assertEqual(original, snapshot(dependencies))
            self.assertIn("bin/example", snapshot(application))

    def test_application_edit_leaves_the_dependency_layer_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = []
            for index in (1, 2):
                dependencies = root / f"dependencies-{index}"
                environment(dependencies, f"VERSION = {index}\n")
                layers.split(dependencies, Path("/code"), root / f"application-{index}")
                results.append(snapshot(dependencies))
            self.assertEqual(*results)

    def test_missing_workspace_metadata_is_a_build_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "No installed workspace"):
                layers.split(root, Path("/code"), root / "application")


if __name__ == "__main__":
    unittest.main()
