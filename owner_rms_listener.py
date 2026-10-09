"""Run on the RMS computer. Only a website button starts an RMS import."""
import os,time,subprocess,sys,logging
from pathlib import Path
import requests
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:pass
BASE=os.environ.get('EOMS_BASE_URL','').rstrip('/')
TOKEN=os.environ.get('EOMS_WORKER_TOKEN','') or os.environ.get('LOCAL_RMS_IMPORT_TOKEN','')
if not BASE.startswith('https://') or not TOKEN:raise SystemExit('Set HTTPS EOMS_BASE_URL and EOMS_WORKER_TOKEN in your local .env. Use the same worker token as Azure.')
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
http=requests.Session();http.headers['Authorization']='Bearer '+TOKEN

def post(path,payload):
    r=http.post(BASE+path,json=payload,timeout=30)
    r.raise_for_status();return r.json()

def main():
    logging.info('Owner RMS listener ready. Imports run only when requested from the website.')
    pending_result=None
    while True:
        try:
            if pending_result:
                post('/api/owner/worker/result',pending_result);pending_result=None
            job=post('/api/owner/worker/claim',{}).get('job')
            if job:
                env=os.environ.copy()
                logging.info('Website requested an RMS import. Starting existing local worker.')
                try:
                    child=subprocess.Popen([sys.executable,'-u',str(ROOT/'eoms_local_worker.py')],cwd=str(ROOT),env=env)
                except OSError:
                    pending_result=dict(job,ok=False)
                    logging.error('Could not start local worker. Check the Python installation and project folder.')
                    continue
                while child.poll() is None:
                    try:post('/api/owner/worker/heartbeat',job)
                    except requests.RequestException:logging.warning('Connection interrupted. Local worker continues; waiting for upload confirmation.')
                    time.sleep(10)
                pending_result=dict(job,ok=child.returncode==0)
                logging.info('Local worker exited. Reporting status to website.')
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code==409:pending_result=None
            logging.warning('Website request failed. Check worker token and Azure connection; retrying.')
        except (requests.RequestException,ValueError):logging.warning('Website connection unavailable; retrying.')
        time.sleep(5)

if __name__=='__main__':main()
