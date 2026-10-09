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
    assert core.post_login_url_for_user({'role':'Dispatcher'},'/dashboard')=='/owner'


def archived_record(**extra):
    row=core.read_json(owner.STORES_FILE)[0]
    row.update(rms_status='Closed in RMS',collected_racks=4)
    row.update(extra)
    core.write_json(owner.STORES_FILE,[row])
    return row

def archive_save(c,status,csrf=True):
    return c.post('/api/archive/status/test-store',json={'status':status},headers={'X-CSRF-Token':'test-csrf'} if csrf else {})

def test_archive_completion_preserves_file_counts_and_rms(setup):
    archived_record()
    assert archive_save(setup,'Completed').status_code==200
    row=core.read_json(owner.STORES_FILE)[0]
    assert row['status']=='Completed' and row['completed_at'] and row['closed_source']=='Both'
    assert row['pdf_path']=='PRIVATE-PATH' and row['collected_racks']==4 and row['rms_status']=='Closed in RMS'
    assert row['audit_history'][-1]['operator']=='owner-test'
    stamp=row['completed_at'];assert archive_save(setup,'Completed').status_code==200
    assert core.read_json(owner.STORES_FILE)[0]['completed_at']==stamp
    assert len(core.read_json(owner.STORES_FILE)[0]['audit_history'])==1

def test_archive_rejects_invalid_status_and_csrf(setup):
    before=archived_record()
    assert archive_save(setup,'Completed',False).status_code==403
    assert archive_save(setup,'Made up').status_code==400
    assert core.read_json(owner.STORES_FILE)[0]==before

def test_archive_active_route_needs_closeout(setup):
    archived_record(route_id='route-1')
    core.write_json(owner.ROUTES_FILE,[{'id':'route-1','status':'Dispatched','store_ids':['test-store']}])
    assert archive_save(setup,'Completed').status_code==409
    archived_record(route_id='route-1',dispatcher_closeout_status='Closed')
    assert archive_save(setup,'Completed').status_code==200

def test_archive_requires_visible_archived_record(setup,monkeypatch):
    assert archive_save(setup,'Completed').status_code==409
    archived_record();monkeypatch.setattr(owner,'filter_stores_for_user',lambda records:[])
    assert archive_save(setup,'Completed').status_code==404

def test_archive_status_can_be_corrected_again(setup):
    archived_record(status='Completed',rms_status='Open')
    assert archive_save(setup,'Exception').status_code==200
    assert archive_save(setup,'Completed').status_code==200


@pytest.fixture
def reset_setup(setup,monkeypatch,tmp_path):
    monkeypatch.setattr(owner,'DATA_DIR',tmp_path/'data');owner.DATA_DIR.mkdir()
    monkeypatch.setattr(core,'RMS_QUEUE_FILE',tmp_path/'reset_queue.json');core.write_json(core.RMS_QUEUE_FILE,[])
    monkeypatch.setattr(core,'BOL_DIR',tmp_path/'bols');core.BOL_DIR.mkdir()
    monkeypatch.setattr(core,'UPLOAD_DIR',tmp_path/'uploads');core.UPLOAD_DIR.mkdir()
    monkeypatch.setattr(core,'audit',lambda *args:None)
    return setup

def reset_request(c,**changes):
    payload={'csrf':'test-csrf','confirmation':'CLEAR BOLS'};payload.update(changes)
    return c.post('/bol-reset',data=payload)

def test_reset_backs_up_documents_and_clears_records(reset_setup,tmp_path):
    from zipfile import ZipFile
    document=core.BOL_DIR/'123.pdf';document.write_bytes(b'Synthetic BOL')
    outside=tmp_path/'keep.txt';outside.write_text('keep')
    rows=core.read_json(owner.STORES_FILE);rows[0].update(pdf_path=str(document),printable_path=str(outside));core.write_json(owner.STORES_FILE,rows)
    core.write_json(owner.ROUTES_FILE,[{'id':'route','status':'Assigned','store_ids':['test-store'],'stops':[rows[0]]}])
    assert reset_request(reset_setup).status_code==200
    assert core.read_json(owner.STORES_FILE)==[] and core.read_json(core.RMS_QUEUE_FILE)==[]
    assert not document.exists() and outside.read_text()=='keep'
    assert core.read_json(owner.ROUTES_FILE)[0]['store_ids']==[]
    name=core.read_json(owner.DATA_DIR/'bol_reset_backup.json')['filename']
    with ZipFile(owner.DATA_DIR/'bol_reset_backups'/name) as z:
        assert json.loads(z.read('data/stores.json'))[0]['id']=='test-store'
        assert any(z.read(n)==b'Synthetic BOL' for n in z.namelist() if n.startswith('documents/'))
    assert reset_setup.get('/bol-reset-backup').status_code==200

def test_reset_rejects_invalid_confirmation_and_csrf(reset_setup):
    assert reset_request(reset_setup,confirmation='wrong').status_code==400
    assert reset_request(reset_setup,csrf='wrong').status_code==403
    assert len(core.read_json(owner.STORES_FILE))==1

def test_reset_requires_admin(reset_setup,monkeypatch):
    monkeypatch.setattr(core,'current_user',lambda:{'username':'dispatcher-test','role':'Dispatcher','assigned_cities':['All']})
    monkeypatch.setattr(core,'current_role',lambda:'Dispatcher')
    assert reset_request(reset_setup).status_code==403
    assert len(core.read_json(owner.STORES_FILE))==1

def test_reset_blocks_active_import(reset_setup):
    core.write_json(owner.OWNER_JOBS_FILE,[{'status':'running','heartbeat':time.time()}])
    assert reset_request(reset_setup).status_code==409
    assert len(core.read_json(owner.STORES_FILE))==1

def test_completed_bol_details_are_available_without_private_paths(setup):
    row=core.read_json(owner.STORES_FILE)[0]
    row.update(status='Recovered',completed_at='2026-10-09T15:00:00+00:00',completed_by='driver',wood_pallet=3,notes='Pickup complete',receiving_status='Pending')
    core.write_json(owner.STORES_FILE,[row])
    result=setup.get('/api/owner/data').json['stores'][0]
    assert result['completed_at']==row['completed_at'] and result['wood_pallet']==3
    assert result['notes']=='Pickup complete' and result['receiving_status']=='Pending'
    assert 'pdf_path' not in result
    assert b'Completed BOLs' in setup.get('/owner').data

def test_weekly_pay_admin_report_and_saved_manual_rates(setup,monkeypatch,tmp_path):
    monkeypatch.setattr(owner,'DRIVER_WEEKLY_RATES_FILE',tmp_path/'rates.json')
    record=core.read_json(owner.STORES_FILE)[0]
    record.update(assigned_driver='driver',completed_at='2026-10-06T15:00:00Z',dispatcher_closeout_status='Closed',warehouse_verified_pieces=100)
    core.write_json(owner.STORES_FILE,[record])
    assert setup.get('/weekly-driver-pay?week=2026-10-05').status_code==200
    assert setup.post('/api/owner/weekly-driver-pay/rates',json={'week':'2026-10-05','rates':{'driver':'0.25'}}).status_code==403
    response=setup.post('/api/owner/weekly-driver-pay/rates',json={'week':'2026-10-05','rates':{'driver':'0.25'}},headers={'X-CSRF-Token':'test-csrf'})
    assert response.status_code==200
    assert b'$25.00' in setup.get('/weekly-driver-pay?week=2026-10-05').data
    monkeypatch.setattr(core,'current_role',lambda:'Dispatcher')
    monkeypatch.setattr(core,'current_user',lambda:{'username':'dispatch-test','role':'Dispatcher'})
    assert setup.get('/weekly-driver-pay?week=2026-10-05').status_code==403

def test_archive_reopen_csrf_and_visibility(setup):
    record=core.read_json(owner.STORES_FILE)[0];record.update(status='Completed',completed_at='2026-10-09T15:00:00Z',rms_status='Closed in RMS')
    core.write_json(owner.STORES_FILE,[record])
    assert setup.post('/api/archive/reopen/test-store',json={}).status_code==403
    response=setup.post('/api/archive/reopen/test-store',json={},headers={'X-CSRF-Token':'test-csrf'})
    assert response.status_code==200 and response.json['status']=='Unassigned'
    reopened=core.read_json(owner.STORES_FILE)[0]
    assert reopened['archive_reopened_at'] and not reopened.get('completed_at')
    assert setup.post('/api/archive/reopen/missing',json={},headers={'X-CSRF-Token':'test-csrf'}).status_code==404
