"""Consistent online SQLite backup, without overwriting an existing destination."""
import os, sqlite3, sys
from pathlib import Path
import server
if len(sys.argv)!=2: raise SystemExit('Uso: python3 backup.py /ruta/segura/respaldo.sqlite3')
p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True)
if not Path(server.DB).is_file(): raise SystemExit('No existe la base de datos de origen.')
fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
try:
    with sqlite3.connect(f'file:{Path(server.DB).resolve()}?mode=ro',uri=True) as source, sqlite3.connect(p) as target: source.backup(target)
except Exception:
    p.unlink(); raise
print('Respaldo creado:',p.resolve())
