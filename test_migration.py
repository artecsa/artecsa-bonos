from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
import migration_copy as migration
import server

class MigrationTests(unittest.TestCase):
    def test_export_and_manual_restore_preserve_records_and_protect_existing_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.sqlite3'; snapshot=Path(folder)/'snapshot.sqlite3'; restored=Path(folder)/'restored.sqlite3'
            original=server.DB
            try:
                server.DB=str(source);server.init()
                with server.connect() as db:
                    db.execute("INSERT INTO clients VALUES(1,'Cliente prueba','Contacto','2026-10-28')")
                    db.execute("INSERT INTO sessions VALUES('secret-session',1,'secret-csrf',9999999999)")
                    db.execute("INSERT INTO attempts VALUES('attempt-key',1,9999999999)")
                fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()
                migration.export_copy(source,snapshot)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),fingerprint)
                with closing(sqlite3.connect(snapshot)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
                    self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)
                    self.assertEqual(db.execute('SELECT password,active FROM users').fetchone(),('',0))
                    self.assertEqual(db.execute('SELECT name FROM clients').fetchone()[0],'Cliente prueba')
                self.assertNotIn(b'secret-session',snapshot.read_bytes())
                migration.restore_copy(snapshot,restored,'admin','Administrador','New-test-password-2026')
                with closing(sqlite3.connect(restored)) as db:
                    user=db.execute('SELECT password,active FROM users WHERE username=?',('admin',)).fetchone()
                    self.assertTrue(server.check_password('New-test-password-2026',user[0]));self.assertEqual(user[1],1)
                    self.assertEqual(db.execute('SELECT count(*) FROM clients').fetchone()[0],1)
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
                restored_hash=hashlib.sha256(restored.read_bytes()).hexdigest()
                with self.assertRaises(FileExistsError):migration.restore_copy(snapshot,restored,'admin','Administrador','New-test-password-2026')
                self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(),restored_hash)
            finally:server.DB=original

if __name__=='__main__':unittest.main()
