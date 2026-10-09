import hashlib,json,secrets,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from functools import wraps
from flask import Blueprint,jsonify,request,session,render_template,make_response
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
    static_root=Path(__file__).resolve().parents[1]/'static'/'owner'
    asset_versions={name:hashlib.sha256((static_root/name).read_bytes()).hexdigest()[:12] for name in ('owner.js','owner.css')}
    response=make_response(render_template('owner_dashboard.html',csrf_token=session['owner_csrf'],company='Essayons BAX',asset_versions=asset_versions))
    response.headers['Cache-Control']='no-store'
    return response

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


@owner_bp.post('/api/archive/status/<store_id>')
@dispatch_required
@csrf_required
@synchronized_data_write(STORES_FILE)
def update_archive_status(store_id):
    payload=request.get_json(silent=True) or {}
    status=payload.get('status')
    if status not in {'Completed','Recovered','Exception','Need Review'}:
        return jsonify(ok=False,message='Choose a valid archive status.'),400
    stores=read_json(STORES_FILE)
    visible={str(s.get('id')) for s in filter_stores_for_user(stores)}
    store=next((s for s in stores if str(s.get('id'))==store_id and store_id in visible),None)
    if not store:
        return jsonify(ok=False,message='BOL not found.'),404
    if store.get('status')!='Completed' and not store.get('archive_status_updated_at') and store.get('rms_status') not in {'Missing from RMS','Closed in RMS'}:
        return jsonify(ok=False,message='Use the active BOL workflow for this record.'),409
    route=next((r for r in read_json(ROUTES_FILE) if store_id in (r.get('store_ids') or []) or (store.get('route_id') and r.get('id')==store.get('route_id'))),None)
    if status=='Completed' and store.get('status')!='Completed' and route and route.get('status')!='Completed' and store.get('dispatcher_closeout_status')!='Closed':
        return jsonify(ok=False,message='Finish warehouse receiving and dispatcher closeout for this active route before marking the BOL Completed.'),409
    previous=store.get('status') or 'Unassigned'
    if status!=previous:
        now=datetime.now(ZoneInfo('America/Chicago')).isoformat(timespec='seconds')
        store['status']=status
        store['updated_at']=now
        store['archive_status_updated_at']=now
        if status=='Completed':
            store['completed_at']=store.get('completed_at') or now
            store['closed_source']='Both' if store.get('rms_status') in {'Missing from RMS','Closed in RMS'} else 'EOMS'
        history=store.get('audit_history')
        if not isinstance(history,list):history=[];store['audit_history']=history
        history.append({'event':'Archive Status Updated','timestamp':now,'operator':session.get('username','system'),'previous_status':previous,'status':status})
        write_json(STORES_FILE,stores)
    return jsonify(ok=True,message='BOL status saved: '+status+'.',status=status)


@owner_bp.route('/bol-reset',methods=['GET','POST'])
@admin_required
def bol_reset_page():
    from app import RMS_QUEUE_FILE
    if not session.get('owner_csrf'):session['owner_csrf']=secrets.token_urlsafe(32)
    if request.method=='POST':
        result,code=reset_all_bols()
        return render_template('bol_reset.html',csrf_token=session['owner_csrf'],result=result,stores=len(read_json(STORES_FILE)),queue=len(read_json(RMS_QUEUE_FILE))),code
    return render_template('bol_reset.html',csrf_token=session['owner_csrf'],result=None,stores=len(read_json(STORES_FILE)),queue=len(read_json(RMS_QUEUE_FILE)))


def reset_all_bols():
    from app import RMS_QUEUE_FILE,delete_saved_bol_files,audit,BOL_DIR,UPLOAD_DIR,path_inside
    import zipfile
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('owner_csrf','!')):
        return {'ok':False,'message':'Reload this page and try again.'},403
    if request.form.get('confirmation')!='CLEAR BOLS':
        return {'ok':False,'message':'Type CLEAR BOLS to reset the BOL list.'},400
    @synchronized_data_write(STORES_FILE,ROUTES_FILE,RMS_QUEUE_FILE,OWNER_JOBS_FILE)
    def apply_reset():
        pending=jobs()
        if any(j.get('status')=='running' and time.time()-float(j.get('heartbeat',j.get('epoch',0)))<120 for j in pending):
            return {'ok':False,'message':'An RMS import is running. Wait for it to finish before resetting BOLs.'},409
        stores=read_json(STORES_FILE);queue=read_json(RMS_QUEUE_FILE)
        if not stores and not queue:return {'ok':True,'message':'The BOL list is already empty.'},200
        backup_dir=DATA_DIR/'bol_reset_backups';backup_dir.mkdir(parents=True,exist_ok=True)
        backup=backup_dir/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)+'.zip')
        candidates=set()
        for root in (BOL_DIR,):
            for pattern in ('*.pdf','*.html'):candidates.update(path.resolve() for path in root.rglob(pattern) if path.is_file() and path_inside(path.resolve(),BOL_DIR))
        for row in stores+queue:
            for key in ('pdf_path','printable_path'):
                if row.get(key):
                    path=Path(row[key]).resolve()
                    if path.is_file() and (path_inside(path,BOL_DIR) or path_inside(path,UPLOAD_DIR)):candidates.add(path)
        with zipfile.ZipFile(backup,'w',zipfile.ZIP_DEFLATED) as z:
            for name,rows in [('stores',stores),('rms_queue',queue),('routes',read_json(ROUTES_FILE))]:z.writestr('data/'+name+'.json',json.dumps(rows))
            for i,path in enumerate(sorted(candidates)):z.write(path,'documents/'+str(i)+'-'+path.name)
        write_json(DATA_DIR/'bol_reset_backup.json',{'filename':backup.name})
        files=[];failed=[]
        for row in stores+queue:
            cleanup=delete_saved_bol_files(row);files.extend(cleanup['deleted']);failed.extend(cleanup['failed'])
        for path in candidates:
            if path.is_file():
                try:path.unlink();files.append(str(path))
                except OSError:failed.append({'path':str(path)})
        if failed:
            return {'ok':False,'message':'Some BOL files could not be removed. The records were kept. Retry the reset.'},500
        ids={str(s.get('id')) for s in stores}
        routes=read_json(ROUTES_FILE)
        for route in routes:
            route['store_ids']=[sid for sid in (route.get('store_ids') or []) if str(sid) not in ids]
            route['stops']=[stop for stop in (route.get('stops') or []) if str(stop.get('id')) not in ids]
            if not route['store_ids'] and not route['stops'] and route.get('status')!='Completed':route['status']='Cancelled'
        for job in pending:
            if job.get('status') in {'queued','running'}:job.update(status='error',message='BOLs were reset. Click Import from RMS to start a fresh import.')
        write_json(STORES_FILE,[]);write_json(RMS_QUEUE_FILE,[]);write_json(ROUTES_FILE,routes);write_json(OWNER_JOBS_FILE,pending)
        audit('Reset All BOLs',{'removed_stores':len(stores),'removed_queue':len(queue),'deleted_files':len(set(files))})
        return {'ok':True,'message':f'BOL reset complete. Removed {len(stores)} BOL records, {len(queue)} queued records, and {len(set(files))} saved files. You can now import from RMS again.'},200
    return apply_reset()


@owner_bp.get('/bol-reset-backup')
@admin_required
def download_bol_reset_backup():
    from flask import send_file,abort
    name=read_json(DATA_DIR/'bol_reset_backup.json').get('filename','')
    if not name or Path(name).name!=name:abort(404)
    path=DATA_DIR/'bol_reset_backups'/name
    if not path.is_file():abort(404)
    return send_file(path,as_attachment=True,download_name='bol-reset-backup.zip')


@owner_bp.route('/bol-number-repair',methods=['GET','POST'])
@admin_required
@synchronized_data_write(STORES_FILE)
def repair_bol_numbers():
    from app import extract_pdf_text,extract_rms_bol_number,essential_review_reasons,backup_stores_json,audit,BOL_DIR,UPLOAD_DIR
    from flask import abort
    if not session.get('owner_csrf'):session['owner_csrf']=secrets.token_urlsafe(32)
    if request.method=='POST' and not secrets.compare_digest(request.form.get('csrf',''),session['owner_csrf']):abort(403)
    sources=[]
    if request.method=='POST' and request.files.get('rms_source'):
        try:sources=json.load(request.files['rms_source'])
        except (ValueError,TypeError):abort(400)
        if not isinstance(sources,list) or len(sources)>10000 or not all(isinstance(s,dict) for s in sources):abort(400)
    def normalized(value):
        import re
        return re.sub(r'[^a-z0-9]','',str(value or '').lower())
    stores=read_json(STORES_FILE);existing={str(s.get('bol')) for s in stores if s.get('bol')};candidates=[]
    for row in stores:
        if row.get('bol'):continue
        path=Path(row.get('pdf_path') or '').resolve()
        roots=[BOL_DIR.resolve(),UPLOAD_DIR.resolve()]
        if not path.is_file() or path.suffix.lower()!='.pdf' or not any(path.is_relative_to(root) for root in roots):continue
        try:bol=extract_rms_bol_number(extract_pdf_text(path))
        except Exception:bol=''
        matches=[s for s in sources if all(normalized(s.get(k))==normalized(row.get(k)) for k in ('address','zip','store_name','city')) and float(s.get('expected_racks') or 0)==float(row.get('expected_racks') or 0)]
        if len(matches)==1 and str(matches[0].get('bol','')).isdigit():
            source_bol=str(matches[0]['bol'])
            if bol and bol!=source_bol:continue
            bol=source_bol
        if not bol or bol in existing:continue
        existing.add(bol);candidate=dict(row,bol=bol)
        reasons=essential_review_reasons(candidate)
        candidates.append({'id':row['id'],'store':row.get('store_name',''),'bol':bol,'reasons':reasons})
    applied=None
    if request.method=='POST':
        backup_stores_json(STORES_FILE,DATA_DIR/'backups',reason='before_bol_number_repair')
        repairs={c['id']:c for c in candidates}
        for row in stores:
            if row['id'] not in repairs:continue
            change=repairs[row['id']];row['bol']=change['bol'];row['review_reasons']=change['reasons']
            if row.get('status')=='Need Review' and not change['reasons']:row['status']='Unassigned'
            row['updated_at']=datetime.now().isoformat(timespec='seconds')
        write_json(STORES_FILE,stores)
        audit('Repair PDF BOL numbers',{'repaired':len(candidates)})
        applied=len(candidates)
    return render_template('bol_number_repair.html',csrf_token=session['owner_csrf'],candidates=candidates,applied=applied)
