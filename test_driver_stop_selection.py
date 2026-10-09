import pytest
from eoms_modules.driver_stop_selection import select_driver_stop, service_history

@pytest.fixture
def work():
    routes=[{'id':'r1','driver':'d1','driver_status':'Accepted','store_ids':['a','b']},{'id':'r2','driver':'d2','driver_status':'Accepted','store_ids':['c']}]
    stores=[{'id':'a','assigned_driver':'d1','status':'Dispatched','driver_work_status':'Current','wood_pallet':4},{'id':'b','assigned_driver':'d1','status':'Assigned'},{'id':'c','assigned_driver':'d2','status':'Assigned'}]
    return routes,stores

def test_select_second_stop_preserves_counts_and_assignments(work):
    routes,stores=work;select_driver_stop(routes,stores,'r1','b',['d1'])
    assert stores[1]['driver_work_status']=='Current' and stores[0]['driver_work_status']=='Waiting'
    assert stores[0]['wood_pallet']==4 and stores[0]['assigned_driver']=='d1'
    assert routes[0]['store_ids']==['a','b']

def test_other_driver_and_other_route_denied(work):
    routes,stores=work
    with pytest.raises(PermissionError):select_driver_stop(routes,stores,'r2','c',['d1'])
    with pytest.raises(LookupError):select_driver_stop(routes,stores,'r1','c',['d1'])

def test_completed_stop_and_unaccepted_route_denied(work):
    routes,stores=work;stores[1]['status']='Recovered'
    with pytest.raises(ValueError):select_driver_stop(routes,stores,'r1','b',['d1'])
    routes[0]['driver_status']='Pending'
    with pytest.raises(ValueError):select_driver_stop(routes,stores,'r1','a',['d1'])

def test_history_uses_same_address_latest_completed_visit():
    stop={'id':'new','address':'123 Main Street','city':'Austin','state':'TX','zip':'78701'}
    older=dict(stop,id='old',status='Completed',completed_at='2025-01-01T15:00:00+00:00')
    newer=dict(stop,id='recent',address='123 MAIN ST.',status='Recovered',completed_at='2025-05-01T15:00:00+00:00')
    wrong=dict(newer,id='wrong',address='125 Main Street',completed_at='2025-06-01T15:00:00+00:00')
    failed=dict(newer,id='failed',driver_exception_type='No Pickup',completed_at='2025-07-01T15:00:00+00:00')
    assert 'May 01, 2025' in service_history(stop,[older,newer,wrong,failed])
    assert service_history(stop,[wrong])=='No service history yet'
    assert service_history(dict(stop,address=''),[older])=='No service history yet'
