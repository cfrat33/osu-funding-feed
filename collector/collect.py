"""Bounded public-source collector. No credentials, AI, or invented grant facts."""
import argparse, datetime as dt, hashlib, html, json, os, re, time
import urllib.request, urllib.error
from pathlib import Path
API='https://api.grants.gov/v1/api/'
UTC=dt.timezone.utc

def now(): return dt.datetime.now(UTC).isoformat(timespec='seconds')
def plain(value):
    return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',str(value or '')))).strip()
def money(value):
    try:
        n=float(str(value).replace(',','').replace('$',''))
        return n if n>=0 and n<float('inf') else None
    except (ValueError,TypeError): return None

def normalize(detail, checked):
    s=detail.get('synopsis') or detail.get('forecast') or {}
    ident=str(detail['id'])
    raw_date=s.get('responseDateStr') or s.get('responseDate')
    prose=plain(s.get('responseDateDesc'))
    year=re.search(r'(20\d{2})',str(raw_date or ''))
    sentinel=bool(year and int(year.group())>dt.datetime.now(UTC).year+10)
    anytime=bool(re.search(r'any\s*time|continuously|rolling',prose,re.I))
    deadline=None
    if raw_date and not sentinel and not anytime:
        m=re.match(r'(\d{4})-(\d{2})-(\d{2})',str(raw_date))
        if m:
            try: deadline=dt.date(*map(int,m.groups())).isoformat()
            except ValueError: pass
    applicant=s.get('applicantTypes') or []
    return {
        'id':'grants-gov-'+ident,'source_id':ident,
        'title':plain(detail.get('opportunityTitle')),
        'opportunity_number':detail.get('opportunityNumber'),
        'agency':plain(s.get('agencyName') or (s.get('agencyDetails') or {}).get('agencyName')),
        'agency_code':s.get('agencyCode'),
        'status':str(detail.get('ost') or 'unknown').lower(),
        'url':'https://www.grants.gov/search-results-detail/'+ident,
        'source':'Grants.gov','summary':plain(s.get('synopsisDesc') or s.get('forecastDesc')),
        'funding_min':money(s.get('awardFloor')),'funding_max':money(s.get('awardCeiling')),
        'currency':'USD','amount_raw':{'floor':s.get('awardFloor'),'ceiling':s.get('awardCeiling')},
        'deadline':deadline,'deadline_description':prose or ('Needs source review' if sentinel else 'Not specified'),
        'deadline_raw':raw_date,'deadline_type':'anytime' if anytime else 'date' if deadline else 'review' if sentinel else 'unknown',
        'eligibility':[{ 'code':str(a.get('id','')), 'description':plain(a.get('description'))} for a in applicant],
        'eligibility_notes':plain(s.get('applicantEligibilityDesc')),
        'categories':[plain(x.get('description')) for x in s.get('fundingActivityCategories',[])],
        'funding_instruments':[plain(x.get('description')) for x in s.get('fundingInstruments',[])],
        'cost_sharing':s.get('costSharing'),
        'source_modified_at':s.get('lastUpdatedDate') or s.get('createTimeStamp'),
        'last_successful_detail_check':checked,
        'source_version':detail.get('revision'),
        'source_detail_endpoint':API+'fetchOpportunity',
        'source_evidence':'Official Grants.gov detail retrieved; eligibility and current solicitation terms still require applicant review.',
        'data_warnings':(['Far-future listing date treated as sentinel; see official deadline description.'] if sentinel else [])+(['Award ceiling not specified by source.'] if money(s.get('awardCeiling')) is None else []),
    }

class Client:
    def __init__(self,cap=200,delay=1): self.requests=0; self.cap=cap; self.delay=delay; self.last=0
    def post(self,endpoint,payload):
        for attempt in range(3):
            if self.requests>=self.cap: raise RuntimeError('Request safety cap reached')
            time.sleep(max(0,self.delay-(time.monotonic()-self.last)))
            self.requests+=1; self.last=time.monotonic()
            req=urllib.request.Request(API+endpoint,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'ResearchFundingFeed/1.0 (public-source research catalog)'})
            try:
                with urllib.request.urlopen(req,timeout=25) as response: result=json.load(response)
                if result.get('errorcode') not in (0,'0',None): raise RuntimeError('Source API rejected request')
                if not isinstance(result.get('data'),dict): raise RuntimeError('Invalid source data shape')
                return result['data'] # Never retain response envelope tokens.
            except urllib.error.HTTPError as exc:
                if exc.code==429: raise RuntimeError('Source rate limited; stop this run') from None
                if exc.code<500 or attempt==2: raise RuntimeError('Source HTTP '+str(exc.code)) from None
                time.sleep(2**(attempt+1))
            except (urllib.error.URLError,TimeoutError):
                if attempt==2: raise RuntimeError('Source network unavailable') from None
                time.sleep(2**(attempt+1))
        raise RuntimeError('Source unavailable')

def read(path,default):
    try: return json.loads(path.read_text())
    except (OSError,ValueError): return default

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp'); temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n'); temp.replace(path)

def run(root,detail_limit=100,max_pages=15):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    started=now(); client=Client(); cache=read(root/'details.json',{}); previous=read(root/'opportunities.json',{})
    health={'started_at':started,'schedule':'Every 3 hours, best effort','scope':'Grants.gov posted and forecast opportunities listing higher-education or unrestricted eligibility. Other sources are not independently collected.','status':'running','errors':[]}
    hits={}; complete=False; excluded=0; detail_ok=0
    try:
        offset=0
        for page in range(max_pages):
            data=client.post('search2',{'rows':200,'startRecordNum':offset,'oppStatuses':'posted|forecasted','eligibilities':'06|20|99'})
            rows=data.get('oppHits')
            if not isinstance(rows,list): raise RuntimeError('Source listing missing')
            health['source_listing_count']=data.get('hitCount')
            for hit in rows:
                if str(hit.get('agencyCode','')).upper()=='IVV': excluded+=1; continue
                if str(hit.get('id','')).isdigit(): hits[str(hit['id'])]=hit
            offset+=len(rows)
            if offset>=int(data.get('hitCount',0)) or not rows: complete=True; break
        if not hits: raise RuntimeError('No usable source listings; retaining previous feed')
        # Prioritize new records, then oldest successful detail retrieval. No fabricated inferred details.
        def priority(ident):
            if ident in cache: return (1, cache[ident].get('checked_at',''), 0, ident)
            try: opened=dt.datetime.strptime(hits[ident].get('openDate',''),'%m/%d/%Y').timestamp()
            except (ValueError,TypeError): opened=0
            return (0, 0 if hits[ident].get('oppStatus')=='posted' else 1, -opened, ident)
        pending=sorted(hits,key=priority)
        for ident in pending[:detail_limit]:
            if client.requests>=190: break
            try:
                detail=client.post('fetchOpportunity',{'opportunityId':int(ident)})
                if str(detail.get('id'))!=ident: raise RuntimeError('Detail identifier mismatch')
                cache[ident]={'checked_at':now(),'detail':detail}; detail_ok+=1
            except RuntimeError as exc:
                health['errors'].append({'source_id':ident,'error':str(exc)})
                if 'rate limited' in str(exc) or 'cap reached' in str(exc): break
        records=[]
        for ident, entry in cache.items():
            record=normalize(entry['detail'],entry['checked_at'])
            record['present_in_latest_listing']=ident in hits if complete else None
            record['listing_last_checked_at']=now() if ident in hits else None
            record['latest_listing_status']=hits.get(ident,{}).get('oppStatus')
            if complete and ident not in hits:
                record['status']='not_in_active_listing'
                record['data_warnings'].append('Not present in latest scoped active listing; this alone does not prove closed.')
            if str(record.get('agency_code') or '').upper()=='IVV': continue
            records.append(record)
        if not records: raise RuntimeError('No official details retrieved; retaining previous feed')
        checked=now()
        feed={'schema_version':1,'generated_at':checked,'last_successful_listing_check':checked,
              'source':'Grants.gov official API','scope':health['scope'],'scheduled_interval_hours':3,
              'coverage':{'listing_complete':complete,'listed_records':len(hits),'detailed_active_records':sum(r['source_id'] in hits for r in records),'pending_detail_records':sum(k not in cache for k in hits),'details_checked_this_run':detail_ok},
              'opportunities':sorted(records,key=lambda r:r['title'])}
        health.update(status='partial' if any(k not in cache for k in hits) or not complete or health['errors'] else 'success',finished_at=checked,request_count=client.requests,details_checked=detail_ok,excluded_test_records=excluded,coverage=feed['coverage'])
        write(root/'details.json',cache); write(root/'opportunities.json',feed)
        # Listing metadata available for transparent coverage, never rendered as verified detail.
        write(root/'listing.json',{'checked_at':checked,'complete':complete,'records':list(hits.values())})
    except Exception as exc:
        health.update(status='failed',finished_at=now(),request_count=client.requests)
        health['errors'].append({'error':str(exc)[:200]})
        health['retained_feed_generated_at']=previous.get('generated_at')
    write(root/'health.json',health)
    logs=read(root/'runs.json',[]); write(root/'runs.json',(logs+[health])[-24:])
    print(json.dumps({k:v for k,v in health.items() if k not in ('errors','scope')}))
    return 1 if health['status']=='failed' else 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',default='data');p.add_argument('--detail-limit',type=int,default=100)
    a=p.parse_args(); raise SystemExit(run(a.data_dir,min(100,max(1,a.detail_limit))))
