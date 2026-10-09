import pytest
from eoms_modules.archive_reopen import reopen_archived_bol
from eoms_modules.weekly_driver_pay import build_weekly_pay

def completed():
    return {'id':'a','bol':'100','status':'Completed','assigned_driver':'d1','completed_at':'2026-10-09T15:00:00Z','dispatcher_closeout_status':'Closed','warehouse_verified_pieces':100,'received_at':'2026-10-09T16:00:00Z','pdf_path':'saved.pdf','expected_racks':5,'weight':1000,'driver_counts_saved_at':'2026-10-09T15:00:00Z','rms_status':'Closed in RMS','corner_posts':20,'drb40':30}

def test_reopen_resets_workflow_preserves_document_and_audit():
    stores=[completed(),{'id':'b','status':'Assigned'}];routes=[{'id':'r1','store_ids':['a','b'],'status':'Completed','metrics':{'weight':1000},'recovery_stops':[{'store_id':'a'},{'store_id':'b'}]}]
    store,changed=reopen_archived_bol(stores,routes,'a','owner')
    assert changed and store['status']=='Unassigned'
    assert store['pdf_path']=='saved.pdf' and store['corner_posts']==20
    assert not store.get('completed_at') and not store.get('assigned_driver') and not store.get('dispatcher_closeout_status')
    assert store['audit_history'][-1]['previous_record']['warehouse_verified_pieces']==100
    assert routes[0]['store_ids']==['b'] and routes[0]['recovery_stops']==[{'store_id':'b'}]
    assert build_weekly_pay(stores,[],'2026-10-05',{'d1':'0.25'})['drivers']==[]
    _,changed=reopen_archived_bol(stores,routes,'a','owner');assert not changed

def test_reopen_blocks_active_assignment_and_preserves_review():
    stores=[completed()];stores[0]['status']='Dispatched'
    with pytest.raises(ValueError):reopen_archived_bol(stores,[],'a','owner')
    stores[0]['status']='Completed';stores[0]['review_reasons']=['Verify address']
    reopened,_=reopen_archived_bol(stores,[],'a','owner');assert reopened['status']=='Need Review'
