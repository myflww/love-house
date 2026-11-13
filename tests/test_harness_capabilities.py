"""Compatibility regressions use real SDK files and isolated installation fixtures."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / 'extensions/deepseek-harness'
spec = importlib.util.spec_from_file_location('capability_detector', EXTENSION / 'configure.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@unittest.skipUnless((EXTENSION / 'node_modules/@deepseek-ai/dsh-agent/package.json').is_file(),
                     'real SDK fixtures installed by Harness compatibility CI')
class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='harness-接口-')
        self.root = Path(self.temporary.name)
        self.app = self.root / 'Harness'
        self.modules = self.app / 'resources/app/dsh/node_modules'
        self.manifest = json.loads(helper.CAPABILITY_FILE.read_text('utf-8'))
        self.version = '99.2.0-compatible-future'
        for name, contract in self.manifest['packages'].items():
            source = EXTENSION / 'node_modules' / name
            target = self.modules / name
            target.mkdir(parents=True)
            metadata = json.loads((source / 'package.json').read_text('utf-8'))
            metadata['version'] = self.version
            (target / 'package.json').write_text(json.dumps(metadata), encoding='utf-8')
            for filename in {metadata['main'], *contract['files'], *contract['runtime_files']}:
                (target / filename).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / filename, target / filename)
        cordis = self.modules / '@deepseek-ai/cordis/package.json'
        cordis.parent.mkdir(parents=True)
        cordis.write_text(json.dumps({'name': '@deepseek-ai/cordis', 'version': '4.9.0'}))

    def tearDown(self):
        self.temporary.cleanup()

    def detect(self):
        return helper.detect(self.app, self.root / 'no-personal-profile')

    def test_future_version_with_additive_code_does_not_require_version_whitelist(self):
        runtime = self.modules / '@deepseek-ai/dsh-agent/lib/index.js'
        runtime.write_text(runtime.read_text('utf-8') + '\nexport const unrelatedAdditiveFeature = true;\n', encoding='utf-8')
        result = self.detect()
        self.assertTrue(result['supported'], result['compatibility'])
        self.assertEqual(result['compatibility']['status'], 'capability_match')
        self.assertEqual(result['version'], self.version)

    def test_pre_step_payload_accepts_added_fields_like_newer_official_sdk(self):
        path = self.modules / '@deepseek-ai/dsh-agent/lib/types/runtime-types.d.ts'
        declaration = path.read_text('utf-8')
        start = declaration.index("'agent/pre-step'")
        end = declaration.index('Promise<PreStepDecision>;', start) + len('Promise<PreStepDecision>;')
        original = declaration[start:end]
        changed = original.replace('signal: AbortSignal;', 'signal: AbortSignal; futureContext?: { effort: string };')
        self.assertNotEqual(original, changed)
        path.write_text(declaration[:start] + changed + declaration[end:], encoding='utf-8')
        self.assertTrue(self.detect()['supported'])

    def test_changed_pre_step_return_type_is_rejected_with_detected_version(self):
        path = self.modules / '@deepseek-ai/dsh-agent/lib/types/runtime-types.d.ts'
        declaration = path.read_text('utf-8')
        original = '}, next: () => Promise<PreStepDecision>): Promise<PreStepDecision>;'
        self.assertIn(original, declaration)
        path.write_text(declaration.replace(original, '}, next: () => Promise<PreStepDecision>): Promise<void>;'),
                        encoding='utf-8')
        result = self.detect()
        self.assertTrue(result['detected'])
        self.assertEqual(result['version'], self.version)
        self.assertFalse(result['supported'])
        self.assertTrue(any('runtime-types.d.ts' in item for item in result['compatibility']['diagnostics']))

    def test_production_archive_without_development_declarations_remains_compatible(self):
        for path in self.modules.rglob('*.d.ts'):
            path.unlink()
        self.assertTrue(self.detect()['supported'])

    def test_removed_hook_even_when_left_in_comment_is_not_accepted(self):
        runtime = self.modules / '@deepseek-ai/dsh-agent/lib/index.js'
        runtime.write_text('// agent/pre-step\nexport const unrelated = true;\n')
        result = self.detect()
        self.assertTrue(result['detected'])
        self.assertFalse(result['supported'])
        self.assertIn('已找到', result['message'])

    def test_mixed_sdk_versions_and_breaking_cordis_major_are_rejected(self):
        path = self.modules / '@deepseek-ai/dsh-session/package.json'
        original = path.read_text('utf-8')
        metadata = json.loads(original)
        metadata['version'] = 'different-sdk-version'
        path.write_text(json.dumps(metadata))
        self.assertFalse(self.detect()['supported'])
        path.write_text(original)
        cordis = self.modules / '@deepseek-ai/cordis/package.json'
        cordis.write_text(json.dumps({'name': '@deepseek-ai/cordis', 'version': '5.0.0'}))
        self.assertFalse(self.detect()['supported'])

    def test_official_npm_cli_uses_same_api_contract(self):
        package = self.modules / '@deepseek-ai/dsh'
        (package / 'lib').mkdir(parents=True)
        (package / 'lib/bin.js').write_text('// inert CLI fixture')
        (package / 'package.json').write_text(json.dumps({'name': '@deepseek-ai/dsh',
            'version': self.version, 'bin': {'dsh': 'lib/bin.js'}}))
        result = helper.detect(package, self.root / 'no-personal-profile')
        self.assertTrue(result['supported'], result['compatibility'])
        self.assertEqual(result['compatibility']['descriptor']['layout'], 'node_modules')

    def test_changed_public_entry_cannot_reuse_stale_capability_files(self):
        path = self.modules / '@deepseek-ai/dsh-session/package.json'
        metadata = json.loads(path.read_text('utf-8'))
        metadata['exports']['.']['default'] = './lib/new-entry.js'
        (path.parent / 'lib/new-entry.js').write_text('export const incompatible = true;')
        path.write_text(json.dumps(metadata))
        self.assertFalse(self.detect()['supported'])
        metadata['main'] = 'lib/new-entry.js'
        path.write_text(json.dumps(metadata))
        self.assertFalse(self.detect()['supported'])
