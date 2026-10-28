# ARTEC · Bonos y liquidaciones — versión 1.2

MVP local ejecutable, en español y HNL. Python 3.10 o posterior; no requiere instalar paquetes. La base de datos SQLite reside en `data/artec.sqlite3` y persiste al cerrar el navegador o reiniciar el servidor.

## Inicio

Desde esta carpeta:

```sh
python3 server.py
```

Abre http://localhost:8765. El primer inicio crea el usuario `admin` e imprime una contraseña aleatoria **una sola vez** en la terminal. Guárdala y cámbiala en **Mi cuenta**. También puedes establecer `ARTEC_ADMIN_PASSWORD` mediante un gestor de secretos antes del primer arranque. Nunca hay una contraseña predeterminada compartida.

En macOS también puedes abrir `Iniciar ARTEC.command`. Mantén la terminal abierta mientras uses la aplicación. Si el puerto está ocupado: `python3 server.py --port 8766`.

## Primeros pasos

1. En **Trabajadores**, sustituye los seis nombres genéricos. Puedes agregar o desactivar trabajadores sin borrar su historial.
2. En **Tarifas de bonos**, guarda los 21 importes reales: tres tipos de elevador por siete tareas. Empiezan en cero; no se pueden aprobar tareas asignadas con tarifa cero.
3. Crea clientes y luego elevadores. La referencia debe ser única: PR seguida de cuatro cifras, por ejemplo PR0123.
4. Marca los trabajadores por tarea y asigna porcentajes enteros positivos que sumen exactamente 100%. Supervisión permite una sola persona al 100%.
5. Revisa el detalle por trabajador. El administrador aprueba la liquidación y fija los importes.
6. Registra uno o más abonos por trabajador y elevador, con fecha, importe y referencia. Consulta el saldo restante.
7. Revisa reportes, imprime o exporta CSV. El CSV de reportes incluye todos los registros; los filtros visuales aplican a la vista y a su impresión.

## Roles

| Operación | Administrador | Supervisor | Consulta |
|---|---|---|---|
| Ver datos, reportes e historial; exportar | Sí | Sí | Sí |
| Crear clientes; crear/editar elevadores en borrador | Sí | Sí | No |
| Registrar abonos | Sí | Sí | No |
| Aprobar liquidaciones; anular abonos con motivo | Sí | No | No |
| Administrar trabajadores, tarifas y usuarios | Sí | No | No |
| Cambiar su propia contraseña | Sí | Sí | Sí |

Los roles se verifican en el servidor. Todos los usuarios autorizados comparten la información de la empresa; no hay separación por cliente. Desactivar un usuario o cambiar sus permisos revoca sus sesiones. Un administrador no puede quitarse su propio rol ni desactivarse. Las sesiones vencen a las ocho horas.

## Reglas y decisiones del MVP

- Tipos: Cabina alta, Cabina baja y Monoriel.
- Tareas: Fabricación, Pintura, Armado, Instalación, Eléctrico, Supervisión y Asistente.
- Un trabajador puede participar en varias tareas; no se impone un máximo de dos, pues los acuerdos solo lo mencionaban como ejemplo.
- Tareas sin trabajadores: costo cero, aunque tengan una tarifa configurada.
- Dinero almacenado en centavos enteros. Los nuevos importes son lempiras enteros. El reparto distribuye lempiras completos por mayores restos; empates se resuelven por ID de trabajador. La suma de repartos coincide exactamente con el bono.
- Fechas operativas se ingresan como fecha calendario; la interfaz propone la fecha de Honduras. El historial técnico usa UTC, indicado en pantalla.
- Aprobar requiere al menos una tarea asignada y tarifas positivas. El servidor comprueba versión y cálculo esperado para evitar aprobar un reparto o tarifas que hayan cambiado mientras se revisaban.
- Las liquidaciones aprobadas quedan cerradas: no se cambian tipo, fecha, tareas, asignaciones ni importes. Los cambios posteriores de tarifas solo afectan borradores.
- No se puede pagar antes de aprobar, antes de la fecha de registro, a un trabajador ajeno al reparto ni por encima del saldo. Se permiten fechas futuras ingresadas explícitamente; son registros manuales, no programación bancaria.
- Cada abono lleva clave única contra duplicados por reintento. Las transacciones serializan la validación y escritura para impedir sobrepagos concurrentes.
- Los abonos no se borran: el administrador puede anularlos con motivo, conservando registro e historial. Los pagos no ejecutan transferencias bancarias.
- Se permite desactivar trabajadores con historial; no se pueden incluir en nuevas asignaciones ni aprobar borradores que aún los incluyan. Sus bonos aprobados pendientes siguen siendo pagables.
- Los clientes no tienen un límite programado; no hay paginación en este MVP. La capacidad práctica depende del servidor y del tamaño de la base de datos.
- El historial conserva cambios de datos, aprobaciones, pagos y anulaciones. No es un registro inalterable ante un administrador con acceso directo al archivo de base de datos.

## PWA y conectividad

Incluye manifiesto, iconos y service worker. En un navegador compatible puede instalarse desde el menú del navegador, bajo HTTPS o localhost. En iPhone/iPad utiliza Safari → Compartir → Añadir a pantalla de inicio después del despliegue HTTPS.

Los datos financieros y respuestas de la API no se almacenan en la caché del service worker. Sin conexión se muestra una pantalla informativa; **no permite registrar pagos sin conexión**. La aplicación instalada necesita acceso al servidor. La instalación real en iOS/Android está pendiente de validación en dispositivos.

## Pruebas

```sh
python3 -m unittest -v
```

Se usa una base temporal aislada y un servidor HTTP local. Se prueban permisos, sesiones, CSRF, origen, porcentajes, Supervisión, tarifas, centavos, concurrencia, aprobaciones inmutables, fechas, abonos múltiples, anulaciones, exportación segura y persistencia.

## Copias de seguridad

```sh
python3 backup.py /ruta/segura/artec-respaldo.sqlite3
```

El script usa la API de respaldo de SQLite y funciona con el servidor activo. Guarda respaldos fuera del equipo y comprueba periódicamente su restauración. Para restaurar: detén el servidor, conserva una copia de la carpeta `data`, sustituye la base por el respaldo y elimina archivos `artec.sqlite3-wal`/`artec.sqlite3-shm` residuales antes de reiniciar. No borres estos archivos con el servidor en ejecución. Los respaldos contienen información de pagos y contraseñas protegidas mediante hash; protégelos como la base original.

## Pendiente para despliegue de producción

Esta entrega está preparada para uso y evaluación **local**. No se ha publicado ni tiene URL externa.

- Elegir servidor privado con volumen persistente. Esta implementación Python/SQLite no se publica directamente en Sites/Cloudflare Workers; requiere alojamiento Python o una adaptación de backend.
- Colocar un servidor WSGI/ASGI o un servicio equivalente de producción y proxy inverso delante del backend; `http.server` es para el MVP local, no un servidor endurecido de producción.
- Dominio, HTTPS y `ARTEC_SECURE_COOKIE=1`; no exponer HTTP a Internet. Configurar límites de solicitudes, política de acceso y tratamiento de IP del proxy para el bloqueo de intentos.
- Crear cuentas reales; confirmar política de quién registra pagos. Rotar credenciales de evaluación, proteger secretos y restringir permisos del volumen.
- Programar y comprobar respaldos, restauración, monitoreo, mantenimiento y actualización del servidor. SQLite es apropiado para un servidor de baja carga; evaluar PostgreSQL para alta concurrencia o múltiples instancias.
- Confirmar nombres y tarifas reales, revisar cálculos con ejemplos de ARTEC y efectuar aceptación por los usuarios.
- Validar instalación PWA y accesibilidad en iOS, Android y escritorio; probar con los dispositivos reales.
- Definir procedimiento de corrección de liquidaciones aprobadas (en el MVP no se reabren), recuperación de contraseñas y, si se requiere, segundo factor de autenticación.
- Agregar paginación, filtros por rango de fechas y exportaciones PDF/XLSX si el volumen y operación los requieren. Actualmente hay CSV y la impresión del navegador.

## Archivos

- `server.py`: servidor HTTP, autenticación, validaciones, SQLite y exportaciones.
- `static/`: interfaz, manifiesto e instalación PWA.
- `test_artec.py`: pruebas automáticas.
- `backup.py`: respaldo consistente de SQLite.
- `Iniciar ARTEC.command`: inicio en macOS.

Variables opcionales: `ARTEC_DB` (ruta a la base), `ARTEC_ADMIN_PASSWORD` (solo creación inicial) y `ARTEC_SECURE_COOKIE=1` (despliegue HTTPS).

## Cambios de la versión 1.2

- Edición de clientes con historial y detección de modificaciones concurrentes.
- Totales por tipo en tarifas; importes y porcentajes nuevos sin decimales.
- La tarea Asistente se incorpora al iniciar sin cambiar los importes ya aprobados.
- El administrador puede eliminar elevadores desde su detalle, indicando referencia y motivo. Debe anular primero los abonos vigentes. El registro se conserva en el historial, desaparece de listados y reportes, y su referencia permanece reservada.
- Los registros históricos conservan sus importes exactos; si contenían fracciones se muestran redondeados.

## Repositorio

El repositorio contiene el código y las pruebas. La base de datos, los respaldos, los secretos y las notas locales de instalación están excluidos mediante `.gitignore`. Cada instalación crea su propia base de datos. Publicar el código en GitHub no despliega la aplicación ni copia sus registros.

## Copia inicial de datos

Se incluye una copia de migración autorizada y sin credenciales en `migration/`, separada de la base activa. Consulta [las instrucciones de restauración manual](migration/README.md). Mantén la base de producción fuera del repositorio mediante `ARTEC_DB`; las actualizaciones de Git no la reemplazan.
