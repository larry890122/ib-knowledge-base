import copy
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rv_data import FIELDS, SECTIONS, METRICS, choose, validate
from scripts.extract_rv import cell_number, slide_values, NS


class RVTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT/'assets/rv-data.json').read_text())

    def test_all_460_values(self):
        validate(self.data)
        values = [r[f] for s in self.data['sections'].values() for rows in s.values() for r in rows for f in FIELDS]
        self.assertEqual(len(values), 460)
        self.assertTrue(all(v is not None for v in values))
        self.assertEqual(self.data['date'], '2026-08-05')

    def test_public_snapshot_identical(self):
        self.assertEqual(self.data, json.loads((ROOT/'public/assets/rv-data.json').read_text()))

    def test_navigation_and_page(self):
        home = (ROOT/'public/index.html').read_text()
        self.assertIn('href="rv/">RV 相對價值', home)
        rv = (ROOT/'public/rv/index.html').read_text()
        self.assertIn('href="../index.html"', rv)
        self.assertIn('2026/08/05', rv)
        self.assertIn('非即時行情', rv)
        self.assertEqual(rv.count('name="metric"'),4)
        self.assertEqual(rv.count('name="section"'),3)

    def test_missing_errors_and_no_cache(self):
        ns = NS['m']
        for content in ('<c/>','<c><f>A1+B1</f></c>','<c t="e"><v>#REF!</v></c>','<c t="s"><v>0</v></c>','<c><v>NaN</v></c>','<c><v>Infinity</v></c>'):
            cell = ET.fromstring(content.replace('<c', f'<c xmlns="{ns}"',1))
            self.assertIsNone(cell_number(cell),content)
        cell = ET.fromstring(f'<c xmlns="{ns}"><f>A1</f><v>0</v></c>')
        self.assertEqual(cell_number(cell),0)

    def test_fallback_and_dates(self):
        date = '2026-08-05'
        for bad in (None, '#REF!', float('nan'), float('inf'), True):
            self.assertEqual(choose(bad,91,'current',date,date,date),(91,'投影片'))
            self.assertEqual(choose(bad,91,'current',date,date,'2026-08-04'),(None,'缺值'))
        self.assertEqual(choose(0,91,'current',date,date,date),(0,'Excel'))
        self.assertEqual(choose(90,91,'current',date,'2026-08-04',date),(91,'投影片'))
        self.assertEqual(choose(90,91,'current',date,'2026-08-04','2026-08-04'),(None,'缺值'))
        self.assertEqual(choose(None,None,'median',date,date,date),(None,'缺值'))

    def test_percentile_limits(self):
        for value in (-.01,1.01):
            self.assertEqual(choose(value,.409,'pct','d','d','d'),(.409,'投影片'))
        for value in (0,1):
            self.assertEqual(choose(value,.409,'pct','d','d','d'),(value,'Excel'))

    def test_invalid_snapshot_rejected(self):
        for field,value in [('min',1000),('median',-10),('max',0),('pct',1.1),('current',float('nan'))]:
            data = copy.deepcopy(self.data)
            data['sections']['Overview']['Spread'][0][field]=value
            with self.assertRaises(ValueError): validate(data)

    def test_missing_does_not_turn_into_zero(self):
        row = self.data['sections']['Overview']['Spread'][0]
        row['median']=None;row['sources']['median']='缺值'
        validate(self.data)
        self.assertIsNone(row['median'])

    def test_slide_fallback_excludes_stale_combo_chart(self):
        class FakeDeck:
            def read(self,path):
                if 'slide2.xml' in path:
                    return f'<p:sld xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:sp><p:nvSpPr><p:cNvPr name="value-current-0"/></p:nvSpPr><a:t>91</a:t></p:sp></p:sld>'
                # The extractor must request only the new chart, never stale chart1.
                if path != 'ppt/slides/charts/chart2.xml': raise AssertionError(path)
                return f'<c:chart xmlns:c="{NS["c"]}"><c:ser><c:val><c:numCache><c:pt idx="0"><c:v>0.409</c:v></c:pt></c:numCache></c:val></c:ser></c:chart>'
        data = slide_values(FakeDeck(),2,1)[0]
        self.assertEqual(data['current'][0],91)
        self.assertEqual(data['pct'][0],.409)
        self.assertNotIn('median',data)

    def test_no_provenance_leak(self):
        serialized = json.dumps(self.data)
        for term in ('.xlsx','.pptx','/Users/','sha256','cell','slide_locator'):
            self.assertNotIn(term,serialized)

if __name__ == '__main__':
    unittest.main()
