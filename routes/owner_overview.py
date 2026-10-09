import json,secrets,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from functools import wraps
from flask import Blueprint,jsonify,request,session,render_template
from app import (DATA_DIR,STORES_FILE,ROUTES_FILE,SYNC_STATE_FILE,read_json,write_json,
    synchronized_data_write,filter_stores_for_user,filter_routes_for_user,users_payload,
    current_role,dispatch_required,admin_required,worker_token_required,HUBS,IS_AZURE)

owner_bp=Blueprint('owner_overview',__name__)
OWNER_JOBS_FILE=DATA_DIR/'owner_rms_requests.json'
TERMINAL={'Completed','Recovered','Cancelled','Closed'}

def priority(value):
    parsed=None
    for fmt in ('%m/%d/%Y','%Y-%m-%d','%m/%d/%y'):
        try:parsed=datetime.strptime(str(value or '').strip(),fmt).date();break
        except ValueError:pass
    if parsed is None:return {'priority':'Unknown date','days_due':None,'due_iso':None}
    days=(parsed-datetime.now(ZoneInfo('America/Chicago')).date()).days
    return {'priority':'Overdue' if days<0 else 'Due today' if days==0 else 'Due soon' if days<=4 else 'Scheduled','days_due':days,'due_iso':parsed.isoformat()}

def csrf_required(fn):
    @wraps(fn)
    def check(*args,**kwargs):
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('owner_csrf','!')):
            return jsonify(ok=False,message='Reload Owner Overview before trying again.'),403
        return fn(*args,**kwargs)
    return check

def jobs():
    rows=read_json(OWNER_JOBS_FILE)
    return rows if isinstance(rows,list) else []

def clean_job(job):return {k:job.get(k) for k in ('id','status','message','started','finished')}

def lease_valid(job,payload):return job and job.get('status')=='running' and secrets.compare_digest(str(payload.get('lease','')),str(job.get('lease','!')))

@owner_bp.get('/owner')
@dispatch_required
def overview():
    if not session.get('owner_csrf'):session['owner_csrf']=secrets.token_urlsafe(32)
    return render_template('owner_dashboard.html',csrf_token=session['owner_csrf'],company='Essayons BAX')

@owner_bp.get('/api/owner/data')
@dispatch_required
def data():
    fields=('id','bol','store_name','origin_name','address','city','state','zip','hub','lat','lng','due_date','expected_racks','weight','status','collected_racks','review_reasons','assigned_driver','driver_work_status','receiving_status','dispatcher_closeout_status','route_id','geocode_status')
    stores=[]
    for row in filter_stores_for_user(read_json(STORES_FILE)):
        s={k:row.get(k) for k in fields};s['status']=s.get('status') or 'Unassigned';s.update(priority(s.get('due_date')))
        if s['status'] in TERMINAL:s['priority']='Completed'
        s['exact_location']=str(s.get('geocode_status') or '').lower().startswith(('azure maps geocoded:','google geocoded:')) or bool(row.get('location_verified'))
        s['document']=bool(row.get('pdf_path') or row.get('printable_path'));stores.append(s)
    routes=[]
    for row in filter_routes_for_user(read_json(ROUTES_FILE)):
        routes.append({k:row.get(k) for k in ('id','route_number','driver','driver_phone','truck','hub','status','store_ids','metrics','last_sms_sent_at')})
        safe_metrics={k:v for k,v in (row.get('metrics') or {}).items() if k in {'hub','store_count','racks','pieces','weight','remaining_capacity','mileage','status'} or current_role()=='Admin'}
        routes[-1].update(number=row.get('route_number'),stops=row.get('store_ids') or [],metrics=safe_metrics,sms_status='Sent' if row.get('last_sms_sent_at') else None)
    drivers=[{'id':u.get('username'),'name':u.get('display_name') or u.get('username'),'username':u.get('username'),'phone':u.get('phone',''),'truck':''} for u in users_payload().get('users',[]) if u.get('role')=='Driver' and u.get('active',True)]
    current_jobs=jobs();job=current_jobs[-1] if current_jobs else None
    if job and job['status']=='running' and time.time()-float(job.get('heartbeat',job.get('epoch',0)))>120:
        job=dict(job,status='error',message='PC worker stopped responding. Check the RMS listener and retry. The existing upload queue remains on your PC.')
    return jsonify(stores=stores,routes=routes,drivers=drivers,hubs={name:[point['lat'],point['lng']] for name,point in HUBS.items()},job=clean_job(job) if job else None,connections={'rms':True},role=current_role(),sync=read_json(SYNC_STATE_FILE))

@owner_bp.post('/api/owner/import')
@admin_required
@csrf_required
@synchronized_data_write(OWNER_JOBS_FILE)
def request_import():
    from uuid import uuid4
    rows=jobs();active=next((j for j in rows if j['status'] in ('queued','running')),None)
    if active:
        if active['status']=='queued' or time.time()-float(active.get('heartbeat',0))<120:
            return jsonify(ok=False,message='An RMS request is already queued or running. Keep your PC listener open.'),409
        active.update(status='error',message='Worker disconnected; request superseded.',finished=datetime.now(ZoneInfo('America/Chicago')).isoformat())
    row={'id':str(uuid4()),'status':'queued','message':'Waiting for your PC RMS listener. Keep the listener running on your computer.','started':datetime.now(ZoneInfo('America/Chicago')).isoformat(),'finished':None,'epoch':time.time()}
    rows.append(row);write_json(OWNER_JOBS_FILE,rows[-100:]);return jsonify(ok=True),202

@owner_bp.post('/api/owner/worker/claim')
@worker_token_required
@synchronized_data_write(OWNER_JOBS_FILE)
def claim():
    rows=jobs();job=next((j for j in rows if j['status']=='queued'),None)
    if not job:return jsonify(ok=True,job=None)
    job.update(status='running',lease=secrets.token_urlsafe(32),heartbeat=time.time(),message='PC worker is importing RMS BOLs and uploading them to Azure.')
    write_json(OWNER_JOBS_FILE,rows);return jsonify(ok=True,job={'id':job['id'],'lease':job['lease']})

@owner_bp.post('/api/owner/worker/heartbeat')
@worker_token_required
@synchronized_data_write(OWNER_JOBS_FILE)
def heartbeat():
    p=request.get_json(silent=True) or {};rows=jobs();job=next((j for j in rows if j['id']==p.get('id')),None)
    if not lease_valid(job,p):return jsonify(ok=False,message='Job lease expired.'),409
    job['heartbeat']=time.time();write_json(OWNER_JOBS_FILE,rows);return jsonify(ok=True)

@owner_bp.post('/api/owner/worker/result')
@worker_token_required
@synchronized_data_write(OWNER_JOBS_FILE)
def result():
    p=request.get_json(silent=True) or {};rows=jobs();job=next((j for j in rows if j['id']==p.get('id')),None)
    if not lease_valid(job,p):return jsonify(ok=False,message='Job lease expired.'),409
    successful=p.get('ok') is True
    job.update(status='ready' if successful else 'error',message='PC worker finished. Uploaded BOLs are shown below; check Automation Center for counts and import exceptions.' if successful else 'RMS worker reported a failure. Check Automation Center and the PC worker log. Existing BOLs remain available.',finished=datetime.now(ZoneInfo('America/Chicago')).isoformat(),heartbeat=time.time());job.pop('lease',None)
    write_json(OWNER_JOBS_FILE,rows);return jsonify(ok=True)

@owner_bp.post('/api/owner/preview')
@dispatch_required
@csrf_required
def preview():
    from routes.route_dispatch import api_preview_route
    return api_preview_route()

@owner_bp.post('/api/owner/assign')
@dispatch_required
@csrf_required
def assign():
    p=request.get_json(silent=True) or {}
    if p.get('driver') not in {u.get('username') for u in users_payload().get('users',[]) if u.get('role')=='Driver' and u.get('active',True)}:
        return jsonify(ok=False,message='Choose an active driver account.'),400
    from routes.route_dispatch import api_assign_route
    return api_assign_route()

@owner_bp.post('/api/owner/dispatch')
@dispatch_required
@csrf_required
def dispatch():
    from routes.route_dispatch import api_dispatch_route
    return api_dispatch_route()

@owner_bp.post('/api/owner/sms')
@dispatch_required
@csrf_required
def sms():
    rid=str((request.get_json(silent=True) or {}).get('route_id',''))
    visible=filter_routes_for_user(read_json(ROUTES_FILE))
    if rid not in {str(r.get('id')) for r in visible}|{str(r.get('route_number')) for r in visible}:return jsonify(ok=False,message='Route not found or outside your assigned cities.'),404
    from routes.route_dispatch import api_send_route_sms
    return api_send_route_sms()
