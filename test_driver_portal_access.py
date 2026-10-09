import pytest
import app as core
from routes import driver_portal as portal
from pypdf import PdfWriter

@pytest.fixture
def driver_client(monkeypatch,tmp_path):
    for name in ('STORES_FILE','ROUTES_FILE'):
        monkeypatch.setattr(portal,name,tmp_path/(name+'.json'))
    monkeypatch.setattr(core,'BOL_DIR',tmp_path)
    pdf=tmp_path/'own.pdf';writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(pdf)
    core.write_json(portal.STORES_FILE,[{'id':'own','bol':'OWN-BOL','store_name':'My pickup','status':'Assigned','due_date':'2026-10-10','pdf_path':str(pdf)},{'id':'other','bol':'OTHER-BOL','status':'Assigned','pdf_path':str(pdf)},{'id':'second','bol':'SECOND-BOL','status':'Assigned'}])
    core.write_json(portal.ROUTES_FILE,[{'id':'r1','route_number':'MY-ROUTE','driver':'d1','status':'Assigned','store_ids':['own']},{'id':'r2','route_number':'OTHER-ROUTE','driver':'d2','status':'Assigned','store_ids':['other']},{'id':'r3','route_number':'MY-SECOND','driver':'d1','status':'Assigned','store_ids':['second']}])
    monkeypatch.setattr(core,'current_user',lambda:{'username':'d1','role':'Driver','display_name':'Driver One'})
    monkeypatch.setattr(core,'current_role',lambda:'Driver')
    monkeypatch.setattr(portal,'current_user',core.current_user);monkeypatch.setattr(portal,'current_role',core.current_role)
    client=core.app.test_client()
    with client.session_transaction() as s:s['logged_in']=True;s['username']='d1'
    return client

def test_own_routes_visible_other_driver_hidden(driver_client):
    result=driver_client.get('/driver');assert result.status_code==200
    assert b'MY-ROUTE' in result.data and b'MY-SECOND' in result.data
    assert b'OTHER-ROUTE' not in result.data and b'OTHER-BOL' not in result.data
    assert b'View BOL' in result.data
    assert result.headers['Cache-Control']=='no-store'

def test_switch_own_route_cannot_switch_other(driver_client):
    result=driver_client.get('/driver?route_id=r3');assert result.status_code==200
    assert b'SECOND-BOL' in result.data and b'OWN-BOL' not in result.data
    assert driver_client.get('/driver?route_id=r2').status_code==404

def test_document_is_private(driver_client):
    assert driver_client.get('/driver/bol/own').status_code==200
    assert driver_client.get('/driver/bol/own').mimetype=='application/pdf'
    assert driver_client.get('/driver/bol/other').status_code==404
    assert driver_client.get('/driver/bol/missing').status_code==404

def test_document_requires_login():
    assert core.app.test_client().get('/driver/bol/own').status_code==302

def test_owner_dispatch_does_not_call_sms():
    from pathlib import Path
    script=(Path(__file__).parent/'static/owner/owner.js').read_text(encoding='utf-8')
    assert '/api/owner/sms' not in script and 'Dispatch & text' not in script
