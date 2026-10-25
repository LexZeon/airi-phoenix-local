# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import tempfile
import unittest
from PIL import Image

spec=importlib.util.spec_from_file_location('sticker_prepare',Path(__file__).with_name('prepare_stickers.py'))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='local-sticker-test-')
        self.root=Path(self.temp.name)/'assets';self.root.mkdir()
        self.output=Path(self.temp.name)/'output'
        Image.new('RGBA',(32,24),(10,30,70,255)).save(self.root/'fixture.png')
        self.recipe={'pack_id':'synthetic-fixture','items':[{'id':'one','file':'fixture.png','name':'Original test geometry','emotions':['happy'],'crop':[1,1,25,20]}]}
    def tearDown(self):
        self.temp.cleanup()
    def test_actual_png_and_repeat_output(self):
        first=module.prepare(self.recipe,self.root,self.output)
        original=(self.output/'one.png').read_bytes()
        second=module.prepare(self.recipe,self.root,self.output)
        self.assertEqual(first,second)
        self.assertEqual(original,(self.output/'one.png').read_bytes())
        with Image.open(self.output/'one.png') as image:
            self.assertEqual(image.format,'PNG');self.assertEqual(image.size,(24,19))
    def test_existing_edit_is_preserved(self):
        module.prepare(self.recipe,self.root,self.output)
        (self.output/'one.png').write_bytes(b'user edited output')
        with self.assertRaises(ValueError):module.prepare(self.recipe,self.root,self.output)
        self.assertEqual((self.output/'one.png').read_bytes(),b'user edited output')
    def test_parent_traversal_and_bad_emotion_rejected(self):
        self.recipe['items'][0]['file']='../outside.png'
        with self.assertRaises(ValueError):module.prepare(self.recipe,self.root,self.output)
        self.recipe['items'][0]['file']='fixture.png';self.recipe['items'][0]['emotions']=['invented']
        with self.assertRaises(ValueError):module.prepare(self.recipe,self.root,self.output)
        self.assertFalse(self.output.exists())
    def test_crop_and_duplicate_id_rejected(self):
        self.recipe['items'][0]['crop']=[-1,0,30,20]
        with self.assertRaises(ValueError):module.prepare(self.recipe,self.root,self.output)
        self.recipe['items'][0]['crop']=[1,1,25,20];self.recipe['items'].append(dict(self.recipe['items'][0]))
        with self.assertRaises(ValueError):module.prepare(self.recipe,self.root,self.output)
    def test_dry_run_has_no_output_writes(self):
        result=module.prepare(self.recipe,self.root,self.output,True)
        self.assertEqual(len(result['items']),1);self.assertFalse(self.output.exists())

if __name__=='__main__':
    unittest.main()
