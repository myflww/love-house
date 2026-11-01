from pathlib import Path
import shutil
import subprocess
import unittest
from nkb.viz.builder import template


class PersonaGrowthUITests(unittest.TestCase):
    def test_component_is_inline_after_organizer_before_imports_and_hints(self):
        html=template()
        marker='data-nkb-component="persona-growth-ui.js"'
        self.assertEqual(html.count(marker),1)
        self.assertLess(html.index('data-nkb-component="memory-organizer-ui.js"'),html.index(marker))
        self.assertLess(html.index(marker),html.index('data-nkb-component="dialogue-import-ui.js"'))
        self.assertLess(html.index(marker),html.index('data-nkb-component="button-hints.js"'))
        for name in ('quickOrganizePersona','personaFormedTraits','organizerApiRecommendation','saveAndEnableOrganizer','personaImportPrompt'):
            self.assertIn(name,html)
        self.assertIn('强烈建议：配置整理 API',html)

    def test_imports_offer_scoped_followup_without_starting_a_model(self):
        root=Path(__file__).parents[1]/'nkb/viz/web'
        for filename in ('dialogue-import-ui.js','memory-portability-ui.js','index.html'):
            source=(root/filename).read_text()
            self.assertIn('LoveHousePersonaGrowth?.afterImport({library_id:',source)
            self.assertNotIn("api('persona/organize'",source)

    @unittest.skipUnless(shutil.which('node'),'Node optional for UI behavior')
    def test_actual_persona_growth_component_behavior(self):
        result=subprocess.run([shutil.which('node'),'--test','--test-reporter=tap',str(Path(__file__).parent/'js/persona-growth-ui.test.cjs')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('# fail 0',result.stdout)
