import concurrent.futures, http.client, json, os, sqlite3, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
import server as app

class ArtecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); app.DB=cls.tmp.name+'/test.db'
        os.environ['ARTEC_ADMIN_PASSWORD']='Testing-password-2026'
        app.init(); cls.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler); cls.port=cls.server.server_port
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
        cls.admin=cls.login('admin','Testing-password-2026')
        for role in ['supervisor','consulta']:
            cls.request('/api/users',{'name':role,'username':role,'password':'Testing-password-2026','role':role},cls.admin)
        cls.supervisor=cls.login('supervisor','Testing-password-2026'); cls.viewer=cls.login('consulta','Testing-password-2026')
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup()
    @classmethod
    def request(cls,path,body=None,auth=None,extra=None):
        conn=http.client.HTTPConnection('127.0.0.1',cls.port)
        headers={'Content-Type':'application/json'}
        if auth: headers.update({'Cookie':auth['cookie'],'X-CSRF-Token':auth['csrf']})
        headers.update(extra or {})
        conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
        r=conn.getresponse(); data=r.read(); ct=r.getheader('Content-Type',''); result=(r.status,json.loads(data) if ct.startswith('application/json') else data.decode('utf-8-sig'),dict(r.getheaders())); conn.close(); return result
    @classmethod
    def login(cls,name,password):
        status,_,headers=cls.request('/api/login',{'username':name,'password':password}); assert status==200
        auth={'cookie':headers['Set-Cookie'].split(';')[0],'csrf':''}; status,state,_=cls.request('/api/state',auth=auth); auth['csrf']=state['csrf']; return auth
    def setUp(self):
        with app.connect() as db:
            db.execute('DELETE FROM payments'); db.execute('DELETE FROM elevators'); db.execute('DELETE FROM clients'); db.execute('UPDATE rates SET cents=10100'); db.execute('UPDATE workers SET active=1')
        self.client=self.request('/api/clients',{'name':'Cliente Prueba'},self.admin)[1]['id']
    def draft(self,assignments=None,reference='PR-0001'):
        a={t:[] for t in app.TASKS}; a['Fabricación']=[{'worker_id':1,'percent':50},{'worker_id':2,'percent':50}]
        if assignments is not None: a=assignments
        return self.request('/api/elevators',{'client_id':self.client,'reference':reference,'type':'Cabina alta','registered_on':'2026-10-26','assignments':a},self.supervisor)
    def state(self): return self.request('/api/state',auth=self.admin)[1]
    def approve(self,id):
        e=next(e for e in self.state()['elevators'] if e['id']==id)
        return self.request('/api/approve',{'id':id,'version':e['version'],'expected_calculation':e['calculation']},self.admin)
    def payment(self,id,amount='10',key='one',auth=None):
        return self.request('/api/payments',{'elevator_id':id,'worker_id':1,'amount':amount,'paid_on':'2026-10-26','note':'Transferencia','request_key':key},auth or self.supervisor)
    def test_unauthenticated_and_static(self):
        self.assertEqual(self.request('/api/state')[0],401); self.assertEqual(self.request('/')[0],200); self.assertEqual(self.request('/server.py')[0],404)
    def test_empty_tasks_excluded_and_cent_conservation(self):
        id=self.draft()[1]['id']; e=self.state()['elevators'][0]; s=e['calculation']
        self.assertEqual(s['total_cents'],10100); self.assertEqual(s['workers'],{'1':5100,'2':5000}); self.assertEqual(len(s['tasks']),1)
    def test_integer_amounts_and_assistant(self):
        self.assertEqual(self.request('/api/rates',{'type':'Cabina alta','task':'Asistente','amount':'25.5'},self.admin)[0],400)
        self.assertEqual(self.request('/api/rates',{'type':'Cabina alta','task':'Asistente','amount':'25'},self.admin)[0],200)
        a={t:[] for t in app.TASKS}; a['Asistente']=[{'worker_id':3,'percent':100}]
        id=self.draft(a)[1]['id']; self.assertEqual(self.approve(id)[0],200)
        self.assertEqual(self.state()['elevators'][0]['calculation']['workers'],{'3':2500})
    def test_task_descriptions_permissions_validation_and_conflict(self):
        task='Fabricación'; old=self.state()['task_descriptions'][task]
        body={'task':task,'description':'Corte y preparación de piezas.','previous':old}
        for auth in [self.supervisor,self.viewer]:
            self.assertEqual(self.request('/api/task-descriptions',body,auth)[0],403)
        self.assertEqual(self.request('/api/task-descriptions',body)[0],401)
        for invalid in [None,42,'x'*1001]:
            self.assertEqual(self.request('/api/task-descriptions',{**body,'description':invalid},self.admin)[0],400)
        self.assertEqual(self.request('/api/task-descriptions',{**body,'task':'No existe'},self.admin)[0],400)
        self.assertEqual(self.request('/api/task-descriptions',body,self.admin)[0],200)
        self.assertEqual(self.request('/api/task-descriptions',{**body,'previous':'desactualizado'},self.admin)[0],409)
        for auth in [self.admin,self.supervisor,self.viewer]:
            self.assertEqual(self.request('/api/state',auth=auth)[1]['task_descriptions'][task],body['description'])
        app.init()
        self.assertEqual(self.state()['task_descriptions'][task],body['description'])
        self.assertTrue(any(a['entity']=='tareas' and a['entity_id']==task for a in self.state()['audit']))
        self.assertEqual(self.request('/api/task-descriptions',{'task':task,'description':'','previous':body['description']},self.admin)[0],200)
        self.assertEqual(self.state()['task_descriptions'][task],'')
    def test_reference_format(self):
        for ref in ['PR','PR-','1234','PR1234','PR-123','PR-12345','pr-1234','PR-12a4']:
            self.assertEqual(self.draft(reference=ref)[0],400)
        self.assertEqual(self.draft(reference='PR-0007')[0],200)
    def test_client_edit_preserves_links_and_audits(self):
        self.draft(); old=next(c for c in self.state()['clients'] if c['id']==self.client)
        body={'id':self.client,'name':'Cliente editado','contact':'Contacto','previous':{'name':old['name'],'contact':old['contact']}}
        self.assertEqual(self.request('/api/clients',body,self.viewer)[0],403)
        self.assertEqual(self.request('/api/clients',body,self.supervisor)[0],200)
        self.assertEqual(self.request('/api/clients',body,self.supervisor)[0],409)
        state=self.state(); c=next(c for c in state['clients'] if c['id']==self.client)
        self.assertEqual(c['created_at'],old['created_at']); self.assertEqual(state['elevators'][0]['client_id'],self.client)
        self.assertEqual(state['audit'][0]['action'],'editar')
    def test_migration_preserves_approved_and_adds_assistant(self):
        id=self.draft()[1]['id']; self.approve(id)
        with app.connect() as db:
            e=app.row(db,'elevators',id); old=json.loads(e['assignments']); old.pop('Asistente')
            db.execute('UPDATE elevators SET assignments=? WHERE id=?',(json.dumps(old),id))
            db.execute("DELETE FROM rates WHERE task='Asistente'")
        app.init(); app.init()
        with app.connect() as db:
            updated=app.row(db,'elevators',id)
            self.assertEqual(updated['settlement'],e['settlement']); self.assertEqual(updated['approved_at'],e['approved_at'])
            self.assertEqual(json.loads(updated['assignments'])['Asistente'],[])
            self.assertEqual(db.execute("SELECT count(*) FROM rates WHERE task='Asistente'").fetchone()[0],3)
    def delete(self,id,auth=None):
        with app.connect() as db: e=app.row(db,'elevators',id)
        return self.request('/api/delete-elevator',{'id':id,'version':e['version'],'reference':e['reference'],'reason':'Registro duplicado'},auth or self.admin)
    def test_delete_draft_permissions_and_history(self):
        id=self.draft()[1]['id']
        self.assertEqual(self.delete(id,self.viewer)[0],403)
        self.assertEqual(self.delete(id,self.supervisor)[0],403)
        self.assertEqual(self.delete(id)[0],200)
        self.assertEqual(self.state()['elevators'],[])
        self.assertEqual(self.state()['audit'][0]['action'],'eliminar')
        self.assertNotIn('PR-0001',self.request('/api/export',auth=self.admin)[1])
        self.assertEqual(self.delete(id)[0],409)
    def test_delete_requires_confirmation_and_current_version(self):
        id=self.draft()[1]['id']
        for body,expected in [({'reference':'wrong','version':1,'reason':'Error'},400),({'reference':'PR-0001','version':0,'reason':'Error'},409),({'reference':'PR-0001','version':1,'reason':''},400)]:
            self.assertEqual(self.request('/api/delete-elevator',{'id':id,**body},self.admin)[0],expected)
        self.assertEqual(len(self.state()['elevators']),1)
    def test_delete_with_payments_requires_void_and_keeps_history(self):
        id=self.draft()[1]['id']; self.approve(id); payment=self.payment(id)[1]['id']
        self.assertEqual(self.delete(id)[0],409)
        self.request('/api/void-payment',{'id':payment,'reason':'Duplicado'},self.admin)
        self.assertEqual(self.delete(id)[0],200)
        state=self.state(); self.assertEqual(state['elevators'],[])
        self.assertEqual(state['payments'][0]['elevator_reference'],'PR-0001')
        self.assertTrue(state['payments'][0]['voided_at'])
        self.assertEqual(self.payment(id,key='after-delete')[0],400)
        self.assertEqual(self.request('/api/approve',{'id':id},self.admin)[0],409)
    def test_percent_validation(self):
        for percent in [0,99,101,-10,'NaN','33.333']:
            a={t:[] for t in app.TASKS}; a['Pintura']=[{'worker_id':1,'percent':percent}]
            self.assertEqual(self.draft(a)[0],400)
    def test_supervision_single(self):
        a={t:[] for t in app.TASKS}; a['Supervisión']=[{'worker_id':1,'percent':50},{'worker_id':2,'percent':50}]
        self.assertEqual(self.draft(a)[0],400); a['Supervisión']=[{'worker_id':1,'percent':100}]; self.assertEqual(self.draft(a)[0],200)
    def test_duplicate_worker_and_inactive(self):
        a={t:[] for t in app.TASKS}; a['Armado']=[{'worker_id':1,'percent':50},{'worker_id':1,'percent':50}]; self.assertEqual(self.draft(a)[0],400)
        with app.connect() as db: db.execute('UPDATE workers SET active=0 WHERE id=1')
        self.assertEqual(self.draft()[0],400)
    def test_roles_server_enforced(self):
        self.assertEqual(self.request('/api/clients',{'name':'No'},self.viewer)[0],403)
        self.assertEqual(self.request('/api/rates',{'type':'Cabina alta','task':'Pintura','amount':1},self.supervisor)[0],403)
        id=self.draft()[1]['id']; self.assertEqual(self.request('/api/approve',{'id':id},self.supervisor)[0],403)
        self.assertEqual(self.request('/api/users',{},self.supervisor)[0],403)
    def test_csrf_and_origin(self):
        self.assertEqual(self.request('/api/clients',{'name':'No'},self.admin,{'X-CSRF-Token':'bad'})[0],403)
        self.assertEqual(self.request('/api/clients',{'name':'No'},self.admin,{'Origin':'https://evil.invalid'})[0],403)
    def test_approval_freezes_rates(self):
        id=self.draft()[1]['id']; self.assertEqual(self.approve(id)[0],200)
        self.request('/api/rates',{'type':'Cabina alta','task':'Fabricación','amount':'500'},self.admin)
        e=self.state()['elevators'][0]; self.assertEqual(e['calculation']['total_cents'],10100)
        e['id']=id; self.assertEqual(self.request('/api/elevators',e,self.admin)[0],409)
    def test_zero_tariff_and_empty_approval_rejected(self):
        id=self.draft({t:[] for t in app.TASKS})[1]['id']; self.assertEqual(self.approve(id)[0],400)
        with app.connect() as db: db.execute('DELETE FROM elevators'); db.execute('UPDATE rates SET cents=0')
        id=self.draft()[1]['id']; self.assertEqual(self.approve(id)[0],400)
    def test_approval_rejects_stale_tariff(self):
        id=self.draft()[1]['id']; e=self.state()['elevators'][0]
        self.request('/api/rates',{'type':'Cabina alta','task':'Fabricación','amount':'500'},self.admin)
        self.assertEqual(self.request('/api/approve',{'id':id,'version':e['version'],'expected_calculation':e['calculation']},self.admin)[0],409)
    def test_multiple_payments_and_balance(self):
        id=self.draft()[1]['id']; self.approve(id); self.assertEqual(self.payment(id,'20','p1')[0],200); self.assertEqual(self.payment(id,'31','p2')[0],200)
        self.assertEqual(self.payment(id,'1','p3')[0],400); e=self.state()['elevators'][0]; self.assertEqual(e['paid_cents'],5100); self.assertEqual(e['pending_cents'],5000)
    def test_payment_restrictions(self):
        id=self.draft()[1]['id']; self.assertEqual(self.payment(id)[0],400); self.approve(id)
        for amount in ['0','-1','52','0.001','NaN','Infinity']:
            self.assertEqual(self.payment(id,amount)[0],400)
        self.assertEqual(self.payment(id,auth=self.viewer)[0],403)
    def test_duplicate_payment_retry(self):
        id=self.draft()[1]['id']; self.approve(id); self.assertEqual(self.payment(id)[0],200); self.assertEqual(self.payment(id)[0],409); self.assertEqual(len(self.state()['payments']),1)
    def test_concurrent_payment_overdraft(self):
        id=self.draft()[1]['id']; self.approve(id)
        with concurrent.futures.ThreadPoolExecutor() as pool:
            results=list(pool.map(lambda key:self.payment(id,'40',key)[0],['race1','race2']))
        self.assertEqual(sorted(results),[200,400]); self.assertEqual(self.state()['elevators'][0]['paid_cents'],4000)
    def test_void_keeps_audit_and_restores_balance(self):
        id=self.draft()[1]['id']; self.approve(id); p=self.payment(id)[1]['id']
        self.assertEqual(self.request('/api/void-payment',{'id':p,'reason':'Error'},self.supervisor)[0],403)
        self.assertEqual(self.request('/api/void-payment',{'id':p,'reason':'Error'},self.admin)[0],200)
        s=self.state(); self.assertEqual(s['elevators'][0]['paid_cents'],0); self.assertTrue(s['payments'][0]['voided_at']); self.assertEqual(s['audit'][0]['action'],'anular')
    def test_stale_version(self):
        id=self.draft()[1]['id']; e=self.state()['elevators'][0]; self.assertEqual(self.request('/api/elevators',e,self.supervisor)[0],200); self.assertEqual(self.request('/api/elevators',e,self.supervisor)[0],409)
    def test_date_validation(self):
        id=self.draft()[1]['id']; self.approve(id)
        b={'elevator_id':id,'worker_id':1,'amount':1,'paid_on':'2026-02-30','note':'Pago','request_key':'date'}
        self.assertEqual(self.request('/api/payments',b,self.supervisor)[0],400); b['paid_on']='2020-01-01'; self.assertEqual(self.request('/api/payments',b,self.supervisor)[0],400)
    def test_csv_formula_injection_and_audit(self):
        self.request('/api/clients',{'id':self.client,'name':'=SUM(1,2)','contact':'','previous':{'name':'Cliente Prueba','contact':''}},self.admin); self.draft(); status,csv,_=self.request('/api/export',auth=self.viewer); self.assertEqual(status,200); self.assertIn("'=SUM",csv)
        self.assertEqual(self.request('/api/export-audit',auth=self.admin)[0],200)
    def test_no_password_or_session_leak(self):
        s=self.state(); self.assertNotIn('password',s['users'][0]); self.assertNotIn('token',s['user']); self.assertEqual(self.request('/api/state',auth=self.viewer)[1]['users'],[])
    def test_last_admin_protected(self):
        self.assertEqual(self.request('/api/users',{'id':1,'name':'Admin','username':'admin','role':'consulta','active':True},self.admin)[0],400)
    def test_disable_user_revokes_session(self):
        self.request('/api/users',{'name':'Temp','username':'temp','password':'Testing-password-2026','role':'consulta'},self.admin)
        auth=self.login('temp','Testing-password-2026'); u=next(u for u in self.state()['users'] if u['username']=='temp')
        self.request('/api/users',{**u,'active':False},self.admin); self.assertEqual(self.request('/api/state',auth=auth)[0],401)
    def test_database_persists_with_new_connection(self):
        id=self.draft()[1]['id']; self.approve(id); self.payment(id)
        with app.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM payments').fetchone()[0],1); self.assertEqual(db.execute('SELECT status FROM elevators WHERE id=?',(id,)).fetchone()[0],'aprobado')
    def test_login_throttle(self):
        for _ in range(10): self.assertEqual(self.request('/api/login',{'username':'nobody','password':'wrong'})[0],401)
        self.assertEqual(self.request('/api/login',{'username':'nobody','password':'wrong'})[0],429)
    def test_all_types_and_tasks(self):
        a={t:[{'worker_id':1,'percent':100}] for t in app.TASKS}
        for i,kind in enumerate(app.TYPES):
            r=self.request('/api/elevators',{'client_id':self.client,'reference':f'PR-{i:04d}','type':kind,'registered_on':'2026-10-26','assignments':a},self.admin)
            self.assertEqual(r[0],200); self.assertEqual(self.approve(r[1]['id'])[0],200)
        self.assertTrue(all(e['calculation']['total_cents']==70700 for e in self.state()['elevators']))

if __name__=='__main__': unittest.main(verbosity=2)
