from unittest.mock import Mock
import pytest
import app as core
from routes import owner_overview as owner
from test_owner_overview import setup,reset_setup

@pytest.mark.parametrize('text',[
    'Bill of Lading: 1005118', 'Bill of Lading : 1005118',
    'Bill of L ading\n1005118', 'Bill of Lading # 1005118',
])
def test_identifier_accepts_pdf_label_spacing(text):
    assert core.extract_rms_bol_number(text)=='1005118'

def test_identifier_does_not_use_total_weight():
    assert core.extract_rms_bol_number('Bill of Lading Total Weight: 2400')==''

def test_diagnostic_timeout_is_nonfatal():
    page=Mock();page.screenshot.side_effect=TimeoutError('fonts')
    assert core.capture_rms_screenshot(page,path='diagnostic.png') is False
    assert page.screenshot.call_args.kwargs['timeout']==5000

def test_repair_preserves_ids_dates_and_real_review_flags(reset_setup,monkeypatch):
    backup=Mock();monkeypatch.setattr(core,'backup_stores_json',backup)
    monkeypatch.setattr(core,'extract_pdf_text',lambda path:'Bill of L ading: '+('12345' if path.name=='a.pdf' else '23456'))
    for name in ['a.pdf','b.pdf']:(core.BOL_DIR/name).write_bytes(b'test')
    rows=[{'id':name,'bol':'','store_name':'Test','city':'Austin','hub':hub,'expected_racks':5,'status':'Need Review','pdf_path':str(core.BOL_DIR/(name+'.pdf')),'due_date':'2026-10-08'} for name,hub in [('a','San Antonio'),('b','Manual Review')]]
    core.write_json(owner.STORES_FILE,rows)
    preview=reset_setup.get('/bol-number-repair');assert preview.status_code==200
    assert b'Repair 2 BOL numbers' in preview.data
    assert reset_setup.post('/bol-number-repair',data={'csrf':'wrong'}).status_code==403
    assert core.read_json(owner.STORES_FILE)==rows
    response=reset_setup.post('/bol-number-repair',data={'csrf':'test-csrf'})
    assert response.status_code==200;backup.assert_called_once()
    updated=core.read_json(owner.STORES_FILE)
    assert updated[0]['bol']=='12345' and updated[0]['status']=='Unassigned'
    assert updated[0]['id']=='a' and updated[0]['due_date']=='2026-10-08'
    assert updated[1]['bol']=='23456' and updated[1]['status']=='Need Review'
    assert updated[1]['review_reasons']==['Hub outside 100 miles']
    assert b'Repair 0 BOL numbers' in reset_setup.get('/bol-number-repair').data
