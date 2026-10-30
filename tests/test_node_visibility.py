"""Renderer sizing and 3D fit math, checked without creating a GPU or calling APIs."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
THREE = ROOT / "nkb/viz/art/node_modules/three/package.json"


class NodeVisibilityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and THREE.is_file(), "Optional Three.js development dependencies are not installed")
    def test_cell_readability_zoom_hit_radius_and_projected_geometry(self):
        result = subprocess.run([shutil.which("node"), "--test", "--test-reporter=tap",
                                 str(ROOT / "tests/js/node-visibility.test.mjs")],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 6", result.stdout)


if __name__ == "__main__":
    unittest.main()
