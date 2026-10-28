# Validación del MVP ARTEC

Pruebas automáticas actualizadas: 28 de octubre de 2026. Versión 1.2.

## Pruebas realizadas

- Suite de 31 pruebas automáticas de integración HTTP y SQLite: aprobada.
- Comprobación de sintaxis de JavaScript y Python: aprobada.
- Validación visual del MVP inicial (26 de octubre), con base de datos separada de prueba: inicio de sesión, creación de cliente, guardado de tarifa, registro del elevador y selección por checkbox, aprobación de liquidación y registro de abono.
- Resultado visible: bono de **L 1,000.01**, abono de **L 250.00** y saldo de **L 750.01**.
- Revisión visual de escritorio y pantalla de 390 × 844: realizada. Las tablas y la navegación permiten desplazamiento horizontal en teléfono.
- El repositorio no incluye bases de datos ni credenciales reales. Las contraseñas del archivo de pruebas se usan exclusivamente en bases temporales.

## Cobertura automática

Tres tipos y siete tareas; porcentajes inválidos y duplicados; trabajador inactivo; Supervisión única; tareas excluidas; conservación de centavos; autorización por rol; sesiones revocadas; CSRF y origen; bloqueo por intentos fallidos; protección del administrador; tarifas positivas al aprobar; importes aprobados inmutables; edición concurrente; cambios de tarifa mientras se aprueba; pagos parciales y saldo; sobrepago y concurrencia; duplicados de pagos; fechas; anulaciones e historial; exportación CSV con neutralización de fórmulas; persistencia SQLite.

## Límites de la validación

No se ha publicado en un servidor externo. No se ha validado instalación real en iOS/Android, recuperación ante caída del servidor, restauración de respaldo en producción, carga masiva ni auditoría de seguridad independiente. El MVP usa un servidor de desarrollo y necesita el endurecimiento descrito en README antes de exponerse a Internet.

La suite actual también verifica Asistente, importes enteros, formato PR de cuatro cifras, edición de clientes, migración compatible y eliminación de elevadores con restricciones de pagos, permisos y conservación del historial.
