from datetime import date
import pytest
from eoms_modules.weekly_driver_pay import build_weekly_pay,pay_week,piece_rate

USERS=[{'username':'d1','display_name':'Driver One','role':'Driver'}]
def row(id,pieces,completed='2026-10-10T23:00:00-05:00',**extra):
    return dict(id=id,bol=id,assigned_driver='d1',completed_at=completed,warehouse_verified_pieces=pieces,dispatcher_closeout_status='Closed',**extra)

def test_sunday_saturday_week_and_payment_dates():
    report=build_weekly_pay([row('sun',3,'2026-10-04T00:00:00-05:00'),row('mon',7,'2026-10-05T00:00:00-05:00'),row('next',99,'2026-10-11T00:00:00-05:00')],USERS,'2026-10-07',{'d1':'0.30'})
    assert (report['start'],report['end'])==('2026-10-04','2026-10-10')
    assert (report['verify'],report['send'],report['payday'])==('2026-10-14','2026-10-15','2026-10-16')
    assert report['drivers'][0]['pieces']==10 and report['total']=='3.00'

def test_central_timezone_boundary():
    report=build_weekly_pay([row('in',1,'2026-10-11T04:59:59Z'),row('out',9,'2026-10-11T05:00:00Z')],USERS,'2026-10-05',{'d1':'0.05'})
    assert report['drivers'][0]['pieces']==1

def test_no_automatic_rate_pending_excluded_and_duplicates_not_counted():
    approved=row('one',11);pending=row('pending',99);pending['dispatcher_closeout_status']='Pending'
    report=build_weekly_pay([approved,dict(approved),pending],USERS,'2026-10-05')
    assert report['drivers'][0]['closed_bols']==1 and report['drivers'][0]['pieces']==11
    assert report['drivers'][0]['amount'] is None and report['pending_bols']==1

def test_decimal_pay_and_missing_verified_count():
    report=build_weekly_pay([row('one',3)],USERS,'2026-10-05',{'d1':'0.125'})
    assert report['total']=='0.38'
    report=build_weekly_pay([row('missing',None)],USERS,'2026-10-05',{'d1':'0.30'})
    assert report['drivers'][0]['amount'] is None

def test_assigned_driver_used_instead_of_admin_operator():
    report=build_weekly_pay([row('one',10,completed_by='admin')],USERS,'2026-10-05')
    assert report['drivers'][0]['driver']=='d1'

def test_rate_validation_and_default_previous_week():
    assert piece_rate('') is None
    for value in ['-1','NaN','Infinity','bad','0.00001']:
        with pytest.raises(ValueError):piece_rate(value)
    assert pay_week(today=date(2026,10,9))==(date(2026,9,27),date(2026,10,3))
