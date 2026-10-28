# Copia inicial para restauración manual

`artec-inicial-2026-10-28.sqlite3` es una copia puntual de los datos locales del 28 de octubre de 2026. Conserva clientes, trabajadores, tarifas, elevadores (incluidos eliminados), liquidaciones, abonos e historial. Los usuarios mantienen sus identificadores para conservar la atribución de operaciones, pero están desactivados y sin contraseñas. No contiene sesiones ni intentos de acceso.

**Esta copia contiene los datos operativos autorizados para publicación en este repositorio.** No es una base activa ni se actualiza automáticamente. No sustituye los respaldos de producción.

## Primera restauración en el servidor

Desde la carpeta del repositorio y con ARTEC detenido, ejecuta lo siguiente. Elige una ubicación persistente fuera del repositorio; en este ejemplo se utiliza `/srv/artec-data` y el usuario del servicio debe tener permisos sobre ella:

```sh
python3 migration_copy.py restore migration/artec-inicial-2026-10-28.sqlite3 /srv/artec-data/artec.sqlite3 --username admin
```

El programa solicita una nueva contraseña de administrador, sin mostrarla ni guardarla en Git. Conserva los registros; habilita la cuenta indicada y añade al historial la restauración. Las demás cuentas permanecen desactivadas: asígnales nuevas contraseñas antes de reactivarlas.

**Si el archivo de destino existe, la operación se detiene sin sobrescribirlo.** Para sustituir una base deliberadamente, detén el servicio, realiza un respaldo consistente de la base actual y conserva aparte su carpeta completa antes de repetir la restauración hacia una ruta nueva. No copies una base sobre otra con el servicio activo.

Configura de forma persistente en el servicio del servidor:

```text
ARTEC_DB=/srv/artec-data/artec.sqlite3
```

Para una prueba manual desde esa terminal:

```sh
ARTEC_DB=/srv/artec-data/artec.sqlite3 python3 server.py
```

No uses el archivo de `migration/` como base activa. No omitas `ARTEC_DB`: sin esa configuración ARTEC usa `data/artec.sqlite3` dentro del proyecto.

## Futuras actualizaciones

1. Respalda la base de producción antes de actualizar.
2. Actualiza el código mediante Git.
3. Reinicia el servicio manteniendo la misma variable `ARTEC_DB` y el mismo volumen persistente.
4. No vuelvas a ejecutar la restauración inicial.

Git no sobrescribe la base externa. La aplicación puede ejecutar migraciones de esquema al iniciar; revisa las notas de futuras versiones y conserva respaldos antes de actualizar.

## Crear otra copia, solo cuando se decida

```sh
python3 migration_copy.py export /ruta/segura/copia-nueva.sqlite3 --source /srv/artec-data/artec.sqlite3
```

La exportación usa el respaldo consistente de SQLite, limpia credenciales y sesiones únicamente en la copia y no modifica los registros del origen. No sobrescribe un archivo existente. Solo el nombre exacto de la copia inicial está exceptuado de `.gitignore`; futuras bases continúan excluidas.
