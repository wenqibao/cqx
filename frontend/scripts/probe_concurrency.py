"""Read-only reproduction of A's SQLite thread-affinity error; no backend edits."""
import concurrent.futures, http.client, json
from pathlib import Path
paths=['/api/patients/P001/state','/api/patients/P001/tasks','/api/patients/P001/runs']*3
def read(path):
 c=http.client.HTTPConnection('127.0.0.1',8000,timeout=10)
 try:
  c.request('GET',path,headers={'Origin':'http://127.0.0.1:5180'});r=c.getresponse();return {'method':'GET','path':path,'status':r.status,'body':r.read().decode()[:400],'cors':r.getheader('Access-Control-Allow-Origin')}
 finally:c.close()
with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:results=list(pool.map(read,paths))
out=Path(__file__).resolve().parents[1]/'docs/evidence/concurrent-reads.json';out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8');print('Read-only parallel requests:',[r['status'] for r in results])
