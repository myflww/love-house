"""Real-edge visual state and geometry contracts; no GPU, credentials or API calls."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NeuralAtlasTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is optional for frontend checks")
    def test_real_association_activity_layout_and_theme(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", "--test-reporter=tap",
             str(ROOT / "tests/js/synapse-dynamics.test.mjs"),
             str(ROOT / "tests/js/warm-theme.test.cjs"),
             str(ROOT / "tests/js/graph-view-state.test.cjs")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 25", result.stdout)

    @unittest.skipUnless(
        shutil.which("node") and (ROOT / "nkb/viz/art/node_modules/three/package.json").is_file(),
        "Optional Three.js development dependencies are not installed",
    )
    def test_real_fibre_geometry_projection_pause_and_cleanup(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", "--test-reporter=tap",
             str(ROOT / "tests/js/neural-fibers.test.mjs")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 7", result.stdout)

    @unittest.skipUnless(
        shutil.which("node") and (ROOT / "nkb/viz/art/node_modules/three/package.json").is_file(),
        "Optional Three.js camera development dependencies are not installed",
    )
    def test_approved_source_reuse_canvas_projection_and_lifecycle(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", "--test-reporter=tap",
             str(ROOT / "tests/js/approved-atlas-painter.test.mjs"),
             str(ROOT / "tests/js/approved-atlas-renderer.test.mjs")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 21", result.stdout)


if __name__ == "__main__":
    unittest.main()
