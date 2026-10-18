import importlib.util,json,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('collect',Path(__file__).parents[1]/'collector/collect.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class CollectorTests(unittest.TestCase):
 def test_official_anytime(self):
  d=json.loads((Path(__file__).parent/'fixtures/anytime.json').read_text());r=m.normalize(d,'2026-10-18T00:00:00Z')
  self.assertEqual(r['deadline_type'],'anytime');self.assertIsNone(r['deadline']);self.assertIsNone(r['funding_max']);self.assertEqual(r['deadline_description'],'Proposals accepted anytime');self.assertEqual(r['source_id'],'363614');self.assertNotIn('fit',r)
 def test_unknown(self):
  r=m.normalize({'id':1},'x');self.assertIsNone(r['funding_min']);self.assertEqual(r['eligibility'],[]);self.assertEqual(r['deadline_type'],'unknown')
 def test_date_amount(self):
  r=m.normalize({'id':2,'synopsis':{'responseDateStr':'2026-12-01-00-00-00','awardFloor':'1,000','awardCeiling':'250000','applicantTypes':[{'id':'06','description':'Public universities'}]}},'x')
  self.assertEqual(r['deadline'],'2026-12-01');self.assertEqual(r['funding_min'],1000);self.assertEqual(r['funding_max'],250000);self.assertEqual(r['eligibility'][0]['code'],'06')
 def test_money_invalid(self):
  for x in ('none','nan','inf','-1','',None):self.assertIsNone(m.money(x))
 def test_plain(self):self.assertEqual(m.plain('<p>A &amp; B</p>'),'A & B')
 def test_sentinel(self):
  r=m.normalize({'id':3,'synopsis':{'responseDateStr':'2076-10-05-00-00-00'}},'x');self.assertIsNone(r['deadline']);self.assertEqual(r['deadline_type'],'review')
if __name__=='__main__':unittest.main()

class CollectionBehaviorTests(unittest.TestCase):
 def test_failure_keeps_previous_feed(self):
  import tempfile
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); original={'generated_at':'old','opportunities':[{'id':'keep'}]};m.write(p/'opportunities.json',original)
   with patch.object(m.Client,'post',side_effect=RuntimeError('Source unavailable')):self.assertEqual(m.run(p),1)
   self.assertEqual(m.read(p/'opportunities.json',{}),original);self.assertEqual(m.read(p/'health.json',{})['status'],'failed')
 def test_mocked_discovery_detail(self):
  import tempfile
  from unittest.mock import patch
  fixture=json.loads((Path(__file__).parent/'fixtures/anytime.json').read_text())
  def post(client,endpoint,payload):
   return {'hitCount':1,'oppHits':[{'id':'363614','agencyCode':'NSF','title':'Example'}]} if endpoint=='search2' else fixture
  with tempfile.TemporaryDirectory() as d:
   with patch.object(m.Client,'post',post):self.assertEqual(m.run(d),0)
   f=m.read(Path(d)/'opportunities.json',{});self.assertEqual(f['coverage']['pending_detail_records'],0);self.assertEqual(f['opportunities'][0]['deadline_type'],'anytime');self.assertEqual(f['scheduled_interval_hours'],3)
 def test_empty_source_retains(self):
  import tempfile
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   with patch.object(m.Client,'post',return_value={'hitCount':0,'oppHits':[]}):self.assertEqual(m.run(d),1)
   self.assertFalse((Path(d)/'opportunities.json').exists())

class FullCatalogTests(unittest.TestCase):
 def test_change_or_daily_expiry(self):
  stamp=m.dt.datetime.now(m.UTC); hit={'id':'1','title':'A'}
  entry={'checked_at':stamp.isoformat(),'listing_signature':m.listing_signature(hit)}
  self.assertFalse(m.detail_due(entry,hit,stamp));self.assertTrue(m.detail_due(entry,dict(hit,title='B'),stamp))
  self.assertTrue(m.detail_due(entry,hit,stamp+m.dt.timedelta(hours=25)));self.assertTrue(m.detail_due(None,hit,stamp))
 def test_full_initial_then_cached_incremental(self):
  import tempfile
  from unittest.mock import patch
  calls=[]
  def post(client,endpoint,payload):
   calls.append(endpoint)
   if endpoint=='search2':return {'hitCount':250,'oppHits':[{'id':str(i),'title':'Example '+str(i)} for i in range(payload['startRecordNum']+1,min(250,payload['startRecordNum']+200)+1)]}
   return {'id':payload['opportunityId'],'opportunityTitle':'Example','ost':'posted','synopsis':{}}
  with tempfile.TemporaryDirectory() as d:
   with patch.object(m.Client,'post',post):self.assertEqual(m.run(d),0)
   f=m.read(Path(d)/'opportunities.json',{});self.assertEqual(f['coverage']['detailed_active_records'],250);self.assertEqual(f['coverage']['pending_detail_records'],0)
   calls.clear()
   with patch.object(m.Client,'post',post):self.assertEqual(m.run(d),0)
   self.assertEqual(calls.count('fetchOpportunity'),0);self.assertEqual(len(m.read(Path(d)/'opportunities.json',{})['opportunities']),250)
 def test_rate_limit_preserves_partial_details(self):
  import tempfile
  from unittest.mock import patch
  calls=[]
  def post(client,endpoint,payload):
   calls.append(endpoint)
   if endpoint=='search2':return {'hitCount':2,'oppHits':[{'id':'1'},{'id':'2'}]}
   if payload['opportunityId']==2:raise RuntimeError('Source rate limited; stop this run')
   return {'id':1,'opportunityTitle':'One','synopsis':{}}
  with tempfile.TemporaryDirectory() as d:
   with patch.object(m.Client,'post',post):self.assertEqual(m.run(d),0)
   h=m.read(Path(d)/'health.json',{});self.assertEqual(h['status'],'partial');self.assertEqual(h['coverage']['pending_detail_records'],1)
