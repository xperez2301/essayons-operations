import json,time
import pytest
import app as core
from routes import owner_overview as owner

@pytest.fixture
def setup(monkeypatch,tmp_path):
    core.app.config['TESTING']=True
    for name,file in [('STORES_FILE','stores.json'),('ROUTES_FILE','routes.json'),('SYNC_STATE_FILE','sync_state.json'),('OWNER_JOBS_FILE','jobs.json')]:monkeypatch.setattr(owner,name,tmp_path/file)
    monkeypatch.setattr(core,'current_user',lambda:{'username':'owner-test','role':'Admin','assigned_cities':['All']})
    monkeypatch.setattr(core,'current_role',lambda:'Admin');monkeypatch.setattr(owner,'current_role',lambda:'Admin')
    monkeypatch.setattr(owner,'users_payload',lambda:{'users':[{'username':'driver','display_name':'Example Driver','role':'Driver','password':'NOT-EXPOSED','phone':'+12105550123'}]})
    monkeypatch.setenv('EOMS_WORKER_TOKEN','synthetic-worker-token')
    core.write_json(owner.STORES_FILE,[{'id':'test-store','bol':'123','store_name':'Test store','status':'Unassigned','expected_racks':5,'weight':1000,'due_date':'2026-10-08','lat':29.4,'lng':-98.5,'hub':'San Antonio','pdf_path':'PRIVATE-PATH'}]);core.write_json(owner.ROUTES_FILE,[]);core.write_json(owner.SYNC_STATE_FILE,{})
    c=core.app.test_client()
    with c.session_transaction() as s:s['logged_in']=True;s['username']='owner-test';s['owner_csrf']='test-csrf'
    return c

def manual(c):return c.post('/api/owner/import',json={},headers={'X-CSRF-Token':'test-csrf'})
def worker(c,path,payload):return c.post('/api/owner/worker/'+path,json=payload,headers={'Authorization':'Bearer synthetic-worker-token'})

def test_owner_template_and_redaction(setup):
    c=setup;assert c.get('/owner').status_code==200
    data=c.get('/api/owner/data').json;assert len(data['stores'])==1
    assert 'PRIVATE-PATH' not in json.dumps(data);assert 'NOT-EXPOSED' not in json.dumps(data)

def test_worker_queue_manual_only(setup):
    c=setup;assert worker(c,'claim',{}).json['job'] is None
    assert c.get('/api/owner/data').json['job'] is None
    assert manual(c).status_code==202
    assert manual(c).status_code==409

def test_csrf_guard(setup):assert setup.post('/api/owner/import',json={}).status_code==403

def test_worker_requires_token(setup):
    c=core.app.test_client();assert c.post('/api/owner/worker/claim',json={}).status_code==401
    assert c.post('/api/owner/worker/result',json={},headers={'Authorization':'Bearer wrong'}).status_code==401

def test_claim_heartbeat_and_result(setup):
    c=setup;manual(c);job=worker(c,'claim',{}).json['job'];assert job and job['lease']
    assert worker(c,'claim',{}).json['job'] is None
    assert worker(c,'heartbeat',job).status_code==200
    assert worker(c,'result',dict(job,ok=True)).status_code==200
    public=c.get('/api/owner/data').json['job'];assert public['status']=='ready';assert 'lease' not in public

def test_wrong_lease_cannot_complete(setup):
    c=setup;manual(c);job=worker(c,'claim',{}).json['job'];job['lease']='wrong'
    assert worker(c,'result',dict(job,ok=True)).status_code==409

def test_worker_failure_retains_stores(setup):
    c=setup;manual(c);job=worker(c,'claim',{}).json['job'];assert worker(c,'result',dict(job,ok=False)).status_code==200
    data=c.get('/api/owner/data').json;assert data['job']['status']=='error';assert len(data['stores'])==1

def test_new_owner_route_honors_driver_role(setup,monkeypatch):
    monkeypatch.setattr(core,'current_role',lambda:'Driver')
    assert setup.get('/api/owner/data').status_code==403

def test_admin_default_and_driver_redirect():
    assert core.post_login_url_for_user({'role':'Admin'},'/dashboard')=='/owner'
    assert core.post_login_url_for_user({'role':'Driver'},'/owner')=='/driver'
    assert core.post_login_url_for_user({'role':'Dispatcher'},'/dashboard')=='/dashboard'
