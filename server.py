#!/usr/bin/env python3
"""ARTEC MVP. Python 3.10+; stdlib only."""
from contextlib import contextmanager
import argparse, csv, hashlib, hmac, io, json, os, secrets, sqlite3, time, re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
TASKS = ['Fabricación','Pintura','Armado','Instalación','Eléctrico','Supervisión','Asistente']
TYPES = ['Cabina alta','Cabina baja','Monoriel']
ROLES = ['administrador','supervisor','consulta']
DB = os.environ.get('ARTEC_DB', str(ROOT / 'data' / 'artec.sqlite3'))
SECURE = os.environ.get('ARTEC_SECURE_COOKIE') == '1'

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def password_hash(p, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(salt),600000).hex()
def check_password(p, hashed): return hmac.compare_digest(password_hash(p,hashed.split(':')[0]), hashed)
@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def init():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT NOT NULL,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('administrador','supervisor','consulta')),active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,count INTEGER NOT NULL,until REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS workers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY,name TEXT NOT NULL,contact TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rates(type TEXT NOT NULL,task TEXT NOT NULL,cents INTEGER NOT NULL CHECK(cents>=0),PRIMARY KEY(type,task));
        CREATE TABLE IF NOT EXISTS elevators(id INTEGER PRIMARY KEY,client_id INTEGER NOT NULL REFERENCES clients(id),reference TEXT UNIQUE NOT NULL,type TEXT NOT NULL,registered_on TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'borrador',assignments TEXT NOT NULL,settlement TEXT,approved_by INTEGER REFERENCES users(id),approved_at TEXT,version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,elevator_id INTEGER NOT NULL REFERENCES elevators(id),worker_id INTEGER NOT NULL REFERENCES workers(id),paid_on TEXT NOT NULL,cents INTEGER NOT NULL CHECK(cents>0),note TEXT NOT NULL,request_key TEXT UNIQUE NOT NULL,created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,voided_at TEXT,void_reason TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,user_id INTEGER REFERENCES users(id),action TEXT NOT NULL,entity TEXT NOT NULL,entity_id TEXT NOT NULL,before_json TEXT,after_json TEXT);
        ''')
        if not db.execute('SELECT 1 FROM users').fetchone():
            p = os.environ.get('ARTEC_ADMIN_PASSWORD') or secrets.token_urlsafe(15)
            if len(p)<12: raise ValueError('La contraseña inicial necesita 12 caracteres.')
            db.execute('INSERT INTO users(name,username,password,role) VALUES(?,?,?,?)',('Administrador','admin',password_hash(p),'administrador'))
            print('Usuario inicial: admin\nContraseña inicial: '+p, flush=True)
        if not db.execute('SELECT 1 FROM workers').fetchone():
            db.executemany('INSERT INTO workers(name) VALUES(?)',[(f'Trabajador {i}',) for i in range(1,7)])
        db.executemany('INSERT OR IGNORE INTO rates VALUES(?,?,0)',[(t,k) for t in TYPES for k in TASKS])
        # Add the new task without changing approved amounts or existing tariffs.
        for e in db.execute('SELECT id,assignments FROM elevators').fetchall():
            assignments=json.loads(e['assignments'])
            if 'Asistente' not in assignments:
                assignments['Asistente']=[]
                db.execute('UPDATE elevators SET assignments=? WHERE id=?',(json.dumps(assignments,ensure_ascii=False),e['id']))
    os.chmod(DB,0o600)

class Problem(Exception):
    def __init__(self,message,status=400): self.message,self.status=message,status

def need(ok,msg,status=400):
    if not ok: raise Problem(msg,status)
def txt(v, name, limit=200):
    need(isinstance(v,str) and 0<len(v.strip())<=limit,f'{name}: texto requerido (máximo {limit}).')
    return v.strip()
def money(v):
    try:
        d=Decimal(str(v)); need(d.is_finite() and 0<=d<=Decimal('999999999') and d==d.to_integral_value(),'Ingrese una cantidad entera, sin decimales.')
        return int(d*100)
    except (InvalidOperation,ValueError): raise Problem('Importe inválido.')
def valid_date(v):
    try: need(isinstance(v,str) and date.fromisoformat(v).isoformat()==v,'Fecha inválida.'); return v
    except (ValueError,TypeError): raise Problem('Fecha inválida.')
def integer(v):
    need(type(v) is int and v>0,'Identificador inválido.'); return v
def row(db,table,id):
    r=db.execute(f'SELECT * FROM {table} WHERE id=?',(integer(id),)).fetchone()
    need(r is not None,'Registro no encontrado.',404); return dict(r)
def audit(db,u,action,entity,id,before=None,after=None):
    db.execute('INSERT INTO audit(at,user_id,action,entity,entity_id,before_json,after_json) VALUES(?,?,?,?,?,?,?)',(now(),u['id'],action,entity,str(id),json.dumps(before,ensure_ascii=False) if before is not None else None,json.dumps(after,ensure_ascii=False) if after is not None else None))
def permission(u,*roles): need(u['role'] in roles,'No tiene permiso para esta acción.',403)

def validate_assignments(db,a):
    need(isinstance(a,dict) and set(a)==set(TASKS),'Se requieren las siete tareas.')
    for task, entries in a.items():
        need(isinstance(entries,list),'Asignación inválida.')
        ids=set(); total=0
        for entry in entries:
            need(isinstance(entry,dict),'Asignación inválida.')
            w=row(db,'workers',entry.get('worker_id')); need(w['active'],'El trabajador está inactivo.')
            need(w['id'] not in ids,'Trabajador duplicado en una tarea.'); ids.add(w['id'])
            bp=money(entry.get('percent')); need(0<bp<=10000,'El porcentaje debe ser mayor que 0 y hasta 100.'); total+=bp
        need(not entries or total==10000,f'{task}: los porcentajes deben sumar 100%.')
        if task=='Supervisión': need(len(entries)<=1,'Supervisión admite un solo trabajador al 100%.')
    return a

def settlement(db,e):
    a=json.loads(e['assignments']); totals={}; details=[]
    for task in TASKS:
        entries=a[task]
        if not entries: continue
        cents=db.execute('SELECT cents FROM rates WHERE type=? AND task=?',(e['type'],task)).fetchone()[0]
        shares=[]
        for entry in entries:
            numerator=((cents+50)//100)*money(entry['percent']); shares.append([entry['worker_id'],numerator//10000,numerator%10000])
        cents=((cents+50)//100)*100
        remainder=cents//100-sum(s[1] for s in shares)
        for share in sorted(shares,key=lambda s:(-s[2],s[0]))[:remainder]: share[1]+=1
        for share in shares: share[1]*=100
        for wid,amount,_ in shares: totals[str(wid)]=totals.get(str(wid),0)+amount
        details.append({'task':task,'cents':cents,'shares':[{'worker_id':s[0],'cents':s[1]} for s in shares]})
    return {'total_cents':sum(totals.values()),'workers':totals,'tasks':details}

def enrich(db,e):
    e=dict(e); e['assignments']=json.loads(e['assignments'])
    e['calculation']=json.loads(e['settlement']) if e['settlement'] else settlement(db,{**e,'assignments':json.dumps(e['assignments'])})
    e.pop('settlement'); e['paid_cents']=db.execute('SELECT COALESCE(sum(cents),0) FROM payments WHERE elevator_id=? AND voided_at IS NULL',(e['id'],)).fetchone()[0]
    e['pending_cents']=e['calculation']['total_cents']-e['paid_cents']; return e

def state(db,u):
    result={'user':u,'tasks':TASKS,'types':TYPES}
    for name in ['workers','clients','rates','payments']:
        result[name]=[dict(r) for r in db.execute(f'SELECT * FROM {name}')]
    for payment in result['payments']:
        payment['elevator_reference']=db.execute('SELECT reference FROM elevators WHERE id=?',(payment['elevator_id'],)).fetchone()[0]
    result['elevators']=[enrich(db,r) for r in db.execute("SELECT * FROM elevators WHERE status!='eliminado' ORDER BY id DESC")]
    result['users']=[dict(r) for r in db.execute('SELECT id,name,username,role,active FROM users')] if u['role']=='administrador' else []
    result['audit']=[dict(r) for r in db.execute('SELECT a.*,u.name AS actor FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 500')]
    return result

def mutate(db,u,path,b):
    if path=='/api/password':
        old=row(db,'users',u['id']); need(check_password(str(b.get('current','')),old['password']),'Contraseña actual incorrecta.',403)
        p=txt(b.get('password'),'Contraseña',256); need(len(p)>=12,'Use al menos 12 caracteres.')
        db.execute('UPDATE users SET password=? WHERE id=?',(password_hash(p),u['id'])); db.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
        audit(db,u,'cambiar contraseña','usuarios',u['id']); return {'reauth':True}
    if path=='/api/clients':
        permission(u,'administrador','supervisor'); name=txt(b.get('name'),'Nombre'); contact=str(b.get('contact',''))[:200]
        before=None
        if b.get('id'):
            before=row(db,'clients',b['id']); id=before['id']
            need(b.get('previous')=={'name':before['name'],'contact':before['contact']},'Otro usuario modificó el cliente. Recargue antes de guardar.',409)
            db.execute('UPDATE clients SET name=?,contact=? WHERE id=?',(name,contact,id))
        else:
            id=db.execute('INSERT INTO clients(name,contact,created_at) VALUES(?,?,?)',(name,contact,now())).lastrowid
        audit(db,u,'editar' if before else 'crear','clientes',id,before,{'name':name,'contact':contact}); return {'id':id}
    if path=='/api/workers':
        permission(u,'administrador'); name=txt(b.get('name'),'Nombre'); active=1 if b.get('active',True) else 0; before=None
        if b.get('id'):
            before=row(db,'workers',b['id']); id=before['id']; db.execute('UPDATE workers SET name=?,active=? WHERE id=?',(name,active,id))
        else: id=db.execute('INSERT INTO workers(name,active) VALUES(?,?)',(name,active)).lastrowid
        audit(db,u,'guardar','trabajadores',id,before,{'name':name,'active':active}); return {'id':id}
    if path=='/api/rates':
        permission(u,'administrador'); need(b.get('type') in TYPES and b.get('task') in TASKS,'Tarifa inválida.')
        cents=money(b.get('amount')); old=dict(db.execute('SELECT * FROM rates WHERE type=? AND task=?',(b['type'],b['task'])).fetchone())
        db.execute('UPDATE rates SET cents=? WHERE type=? AND task=?',(cents,b['type'],b['task'])); audit(db,u,'tarifa','tarifas',b['type']+'/'+b['task'],old,{**b,'cents':cents}); return {}
    if path=='/api/users':
        permission(u,'administrador'); name=txt(b.get('name'),'Nombre'); username=txt(b.get('username'),'Usuario',80).lower(); role=b.get('role'); need(role in ROLES,'Rol inválido.')
        p=b.get('password',''); need(isinstance(p,str) and len(p)<=256,'Contraseña inválida.'); active=1 if b.get('active',True) else 0
        if b.get('id'):
            old=row(db,'users',b['id']); need(old['id']!=u['id'] or (active and role=='administrador'),'No puede quitarse su propio acceso administrativo.')
            if old['role']=='administrador' and old['active'] and (not active or role!='administrador'):
                need(db.execute("SELECT count(*) FROM users WHERE role='administrador' AND active=1").fetchone()[0]>1,'Debe quedar un administrador activo.')
            db.execute('UPDATE users SET name=?,username=?,role=?,active=? WHERE id=?',(name,username,role,active,old['id'])); id=old['id']
            if p: need(len(p)>=12,'Use al menos 12 caracteres.'); db.execute('UPDATE users SET password=? WHERE id=?',(password_hash(p),id))
            db.execute('DELETE FROM sessions WHERE user_id=?',(id,))
        else:
            need(len(p)>=12,'Use al menos 12 caracteres.'); id=db.execute('INSERT INTO users(name,username,password,role) VALUES(?,?,?,?)',(name,username,password_hash(p),role)).lastrowid
        audit(db,u,'guardar','usuarios',id,after={'name':name,'username':username,'role':role,'active':active}); return {'id':id}
    if path=='/api/elevators':
        permission(u,'administrador','supervisor'); client=row(db,'clients',b.get('client_id')); ref=txt(b.get('reference'),'Referencia',100); kind=b.get('type'); need(kind in TYPES,'Tipo inválido.')
        old_reference=row(db,'elevators',b['id'])['reference'] if b.get('id') else None
        need(re.fullmatch(r'PR[0-9]{4}',ref) is not None or ref==old_reference,'La referencia debe ser PR seguida de 4 cifras, por ejemplo PR0123.')
        registered=valid_date(b.get('registered_on')); assignments=validate_assignments(db,b.get('assignments')); before=None
        if b.get('id'):
            before=row(db,'elevators',b['id']); need(before['status']=='borrador','Una liquidación aprobada no se puede modificar.',409)
            need(b.get('version')==before['version'],'Otro usuario modificó el elevador. Recargue antes de guardar.',409)
            id=before['id']; db.execute('UPDATE elevators SET client_id=?,reference=?,type=?,registered_on=?,assignments=?,version=version+1 WHERE id=?',(client['id'],ref,kind,registered,json.dumps(assignments),id))
        else: id=db.execute('INSERT INTO elevators(client_id,reference,type,registered_on,assignments) VALUES(?,?,?,?,?)',(client['id'],ref,kind,registered,json.dumps(assignments))).lastrowid
        audit(db,u,'guardar','elevadores',id,before,b); return {'id':id}
    if path=='/api/delete-elevator':
        permission(u,'administrador'); e=row(db,'elevators',b.get('id'))
        need(e['status']!='eliminado','El elevador ya fue eliminado.',409)
        need(b.get('version')==e['version'],'Otro usuario modificó el elevador. Recargue antes de eliminar.',409)
        need(b.get('reference')==e['reference'],'Escriba la referencia exacta para confirmar la eliminación.')
        reason=txt(b.get('reason'),'Motivo de eliminación',300)
        need(not db.execute('SELECT 1 FROM payments WHERE elevator_id=? AND voided_at IS NULL',(e['id'],)).fetchone(),'El elevador tiene abonos vigentes. Anúlelos antes de eliminarlo.',409)
        db.execute("UPDATE elevators SET status='eliminado',version=version+1 WHERE id=?",(e['id'],))
        audit(db,u,'eliminar','elevadores',e['id'],e,{'reference':e['reference'],'reason':reason,'status':'eliminado'})
        return {}
    if path=='/api/approve':
        permission(u,'administrador'); e=row(db,'elevators',b.get('id')); need(e['status']=='borrador','La liquidación ya está aprobada.',409)
        need(b.get('version')==e['version'],'La versión cambió; recargue.',409)
        validate_assignments(db,json.loads(e['assignments'])); s=settlement(db,e)
        need(s['tasks'] and all(t['cents']>0 for t in s['tasks']),'Configure tarifas mayores que cero para todas las tareas asignadas.')
        need(b.get('expected_calculation')==s,'Las tarifas cambiaron; recargue y revise los importes antes de aprobar.',409)
        db.execute("UPDATE elevators SET status='aprobado',settlement=?,approved_by=?,approved_at=?,version=version+1 WHERE id=?",(json.dumps(s),u['id'],now(),e['id']))
        audit(db,u,'aprobar','liquidaciones',e['id'],after=s); return {}
    if path=='/api/payments':
        permission(u,'administrador','supervisor'); key=txt(b.get('request_key'),'Clave de operación',100)
        need(not db.execute('SELECT 1 FROM payments WHERE request_key=?',(key,)).fetchone(),'Este abono ya se registró.',409)
        e=row(db,'elevators',b.get('elevator_id')); need(e['status']=='aprobado','Apruebe la liquidación antes de abonar.')
        w=row(db,'workers',b.get('worker_id')); s=json.loads(e['settlement']); earned=s['workers'].get(str(w['id']),0)
        paid=db.execute('SELECT COALESCE(sum(cents),0) FROM payments WHERE elevator_id=? AND worker_id=? AND voided_at IS NULL',(e['id'],w['id'])).fetchone()[0]
        cents=money(b.get('amount')); need(0<cents<=earned-paid,'El abono debe ser positivo y no superar el saldo pendiente.')
        day=valid_date(b.get('paid_on')); need(day>=e['registered_on'],'El abono no puede ser anterior al registro del elevador.'); note=txt(b.get('note'),'Referencia del pago',300)
        id=db.execute('INSERT INTO payments(elevator_id,worker_id,paid_on,cents,note,request_key,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',(e['id'],w['id'],day,cents,note,key,u['id'],now())).lastrowid
        audit(db,u,'abonar','abonos',id,after={**b,'cents':cents}); return {'id':id}
    if path=='/api/void-payment':
        permission(u,'administrador'); p=row(db,'payments',b.get('id')); need(not p['voided_at'],'El abono ya está anulado.',409); reason=txt(b.get('reason'),'Motivo',300)
        db.execute('UPDATE payments SET voided_at=?,void_reason=? WHERE id=?',(now(),reason,p['id'])); audit(db,u,'anular','abonos',p['id'],p,{'reason':reason}); return {}
    raise Problem('Ruta no encontrada.',404)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): pass
    def send(self,status,data,kind='application/json; charset=utf-8',headers=None):
        raw=json.dumps(data,ensure_ascii=False).encode() if kind.startswith('application/json') else (data.encode() if isinstance(data,str) else data)
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",**(headers or {})}.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)
    def cookie(self,token,age=28800): return f'artec={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}'+('; Secure' if SECURE else '')
    def session(self,db):
        cookies=dict(part.strip().split('=',1) for part in self.headers.get('Cookie','').split(';') if '=' in part)
        s=db.execute('SELECT s.*,u.name,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE token=? AND expires>? AND u.active=1',(digest(cookies.get('artec','')),time.time())).fetchone()
        need(s is not None,'Inicie sesión.',401)
        return dict(s),{'id':s['user_id'],'name':s['name'],'username':s['username'],'role':s['role']}
    def do_GET(self):
        try:
            path=urlparse(self.path).path
            if path.startswith('/api/'):
                with connect() as db:
                    s,u=self.session(db)
                    if path=='/api/state': return self.send(200,{**state(db,u),'csrf':s['csrf']})
                    if path in ['/api/export','/api/export-audit']:
                        out=io.StringIO(); writer=csv.writer(out)
                        def safe(v):
                            v=str(v); return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
                        if path=='/api/export-audit':
                            writer.writerow(['Fecha UTC','Usuario','Acción','Entidad','ID','Antes','Después'])
                            for r in db.execute('SELECT * FROM audit ORDER BY id'): writer.writerow([safe(r[k] or '') for k in ['at','user_id','action','entity','entity_id','before_json','after_json']])
                        else:
                            writer.writerow(['Elevador','Cliente','Tipo','Fecha registro','Estado','Trabajador','Bono HNL','Pagado HNL','Saldo HNL'])
                            for e in db.execute("SELECT * FROM elevators WHERE status!='eliminado'"):
                                e=enrich(db,e); client=row(db,'clients',e['client_id'])
                                for wid,earned in e['calculation']['workers'].items():
                                    paid=db.execute('SELECT COALESCE(sum(cents),0) FROM payments WHERE elevator_id=? AND worker_id=? AND voided_at IS NULL',(e['id'],int(wid))).fetchone()[0]
                                    writer.writerow([safe(x) for x in [e['reference'],client['name'],e['type'],e['registered_on'],e['status'],row(db,'workers',int(wid))['name'],str((earned+50)//100),str((paid+50)//100),str((earned-paid+50)//100)]])
                        return self.send(200,'\ufeff'+out.getvalue(),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="artec-reporte.csv"'})
                    raise Problem('Ruta no encontrada.',404)
            files={'/icon-192.png':('icon-192.png','image/png'),'/icon-512.png':('icon-512.png','image/png'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css'),'/sw.js':('sw.js','text/javascript'),'/manifest.webmanifest':('manifest.webmanifest','application/manifest+json'),'/icon.svg':('icon.svg','image/svg+xml'),'/offline.html':('offline.html','text/html; charset=utf-8')}
            need(path in files,'No encontrado.',404); f,kind=files[path]; self.send(200,(ROOT/'static'/f).read_bytes(),kind)
        except Problem as e: self.send(e.status,{'error':e.message})
    def do_POST(self):
        try:
            origin=self.headers.get('Origin'); host=self.headers.get('Host')
            need(origin is None or (urlparse(origin).netloc==host and urlparse(origin).scheme in ['http','https']),'Origen no permitido.',403)
            need(self.headers.get('Content-Type','').split(';')[0]=='application/json','Se requiere JSON.',415)
            size=int(self.headers.get('Content-Length','0')); need(0<size<=100000,'Solicitud demasiado grande o vacía.',413)
            b=json.loads(self.rfile.read(size)); need(isinstance(b,dict),'Solicitud inválida.')
            path=urlparse(self.path).path
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if path=='/api/login':
                    name=txt(b.get('username'),'Usuario',80).lower(); p=txt(b.get('password'),'Contraseña',256); key=digest(self.client_address[0]+'|'+name)
                    attempt=db.execute('SELECT * FROM attempts WHERE key=?',(key,)).fetchone()
                    need(not attempt or attempt['count']<10 or attempt['until']<time.time(),'Demasiados intentos. Espere 15 minutos.',429)
                    u=db.execute('SELECT * FROM users WHERE username=? AND active=1',(name,)).fetchone()
                    if not u or not check_password(p,u['password']):
                        count=attempt['count']+1 if attempt and attempt['until']>time.time() else 1
                        db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(key,count,time.time()+900)); db.commit(); raise Problem('Usuario o contraseña incorrectos.',401)
                    db.execute('DELETE FROM attempts WHERE key=?',(key,)); db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
                    token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
                    db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),u['id'],csrf,time.time()+28800)); db.commit()
                    return self.send(200,{'ok':True},headers={'Set-Cookie':self.cookie(token)})
                s,u=self.session(db); need(hmac.compare_digest(self.headers.get('X-CSRF-Token',''),s['csrf']),'Sesión de formulario inválida. Recargue.',403)
                if path=='/api/logout':
                    db.execute('DELETE FROM sessions WHERE token=?',(s['token'],)); db.commit(); return self.send(200,{},headers={'Set-Cookie':self.cookie('',0)})
                result=mutate(db,u,path,b); db.commit(); self.send(200,result)
        except Problem as e: self.send(e.status,{'error':e.message})
        except sqlite3.IntegrityError: self.send(409,{'error':'Ya existe la referencia o el usuario, o un registro relacionado no es válido.'})
        except (ValueError,TypeError,KeyError,AttributeError): self.send(400,{'error':'Datos inválidos. Revise el formulario.'})
        except Exception:
            import traceback; traceback.print_exc(); self.send(500,{'error':'Error interno. La operación no se guardó.'})

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--host',default='127.0.0.1'); args=parser.parse_args()
    init(); print(f'ARTEC disponible en http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
