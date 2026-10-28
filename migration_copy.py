#!/usr/bin/env python3
"""Explicit export/restore only. Never runs on application startup or git pull."""
import argparse
from contextlib import closing
import getpass
import os
from pathlib import Path
import sqlite3
import server


def copy_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('No existe la base de origen.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src, closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    except Exception:
        destination.unlink()
        raise
    return destination


def verify(db):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('La copia no pasó la validación de integridad.')


def export_copy(source, destination):
    output = copy_database(source, destination)
    with closing(sqlite3.connect(output)) as db:
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA secure_delete=ON')
        with db:
            db.execute('DELETE FROM sessions')
            db.execute('DELETE FROM attempts')
            # Keep user IDs for payment, approval and audit attribution; disable access.
            db.execute("UPDATE users SET password='',active=0")
        db.execute('VACUUM')
        verify(db)
    return output


def restore_copy(source, destination, username, name, password):
    if not username.strip() or not name.strip() or not 12 <= len(password) <= 256:
        raise ValueError('Indique usuario, nombre y una contraseña de 12 a 256 caracteres.')
    output = copy_database(source, destination)
    try:
        with closing(sqlite3.connect(output)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('PRAGMA secure_delete=ON')
            with db:
                db.execute('DELETE FROM sessions')
                db.execute('DELETE FROM attempts')
                db.execute("UPDATE users SET password='',active=0")
                existing = db.execute('SELECT id FROM users WHERE username=?',(username.strip().lower(),)).fetchone()
                hashed = server.password_hash(password)
                if existing:
                    uid=existing[0]
                    db.execute("UPDATE users SET password=?,role='administrador',active=1 WHERE id=?",(hashed,uid))
                else:
                    uid=db.execute("INSERT INTO users(name,username,password,role,active) VALUES(?,?,?,'administrador',1)",(name.strip(),username.strip().lower(),hashed)).lastrowid
                server.audit(db,{'id':uid},'restaurar copia','migración',uid,after={'administrator':username.strip().lower()})
            db.execute('VACUUM')
            verify(db)
    except Exception:
        output.unlink()
        raise
    return output


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    export=sub.add_parser('export'); export.add_argument('destination'); export.add_argument('--source',default=server.DB)
    restore=sub.add_parser('restore'); restore.add_argument('source'); restore.add_argument('destination'); restore.add_argument('--username',default='admin'); restore.add_argument('--name',default='Administrador')
    args=parser.parse_args()
    try:
        if args.command=='export':
            out=export_copy(args.source,args.destination)
            print('Copia creada sin contraseñas ni sesiones:',out)
        else:
            password=getpass.getpass('Nueva contraseña del administrador: ')
            if password!=getpass.getpass('Repita la contraseña: '):
                raise ValueError('Las contraseñas no coinciden.')
            out=restore_copy(args.source,args.destination,args.username,args.name,password)
            print('Copia restaurada:',out)
            print('Configure ARTEC_DB con esta ruta. Las demás cuentas están desactivadas; puede reactivarlas asignando nuevas contraseñas.')
    except (ValueError,FileExistsError,sqlite3.Error) as e:
        raise SystemExit('No se completó la operación: '+str(e))
