# Specs de TESTIGO+

Documentos de diseño del proyecto. Se escriben antes del código y el código los sigue.

| Archivo | Qué es |
| --- | --- |
| `00-spec-general.md` | Qué es TESTIGO+, objetivo, reglas de Meta, alcance, arquitectura, features (F0 a F11), riesgos y gate. Es la base de todos los demás. |
| `01-spec-construccion.md` | Correcciones a las maquetas, piezas del sistema, portal simulado y ataques, vistas reales, formatos y orden de construcción. |
| `02-spec-vistas-maquetas.md` | Spec de las 8 vistas y la portada usadas para las maquetas en Claude Design. |
| `03-revision-31-oct.md` | Revisión del 31 de oct: estado real del código, decisiones R1 a R11, calendario nuevo hasta el 4 de nov, infraestructura y stack. §10: R2 decidido el 1 de nov, se protege la dirección de entrega de un pedido (antes era un pago). **Manda sobre los demás donde los contradiga.** |

Specs de cada feature (objetivo, entradas y salidas, criterios de aceptación, qué se prueba con modelos reales y qué con datos de prueba, y qué del código actual se conserva):

| Archivo | Feature | Estado |
| --- | --- | --- |
| `F0-infraestructura.md` | Estructura del repositorio, instalación, secretos, API de Meta, Playwright, pruebas, gate | Aprobado 28 oct; implementado; gate: g1 5/5 y g2 10/10 contra la API real (31 oct, dominio anterior; se vuelven a correr en el dominio de entrega); g3–g6 y `run_gate` escritos, probados con una muestra mínima, corridas completas pendientes; g7 omitido (R8) |
| `F1-mandato-y-politica.md` | Mandato por voz y política firmada | Borrador; implementado: formato con dirección atada (`deliver_only`), firma Ed25519 y la compilación por voz (`python -m policy.compile mandate <wav>`: Voice + Spark con esquema JSON estricto, validado por código, dirección del perfil de la tienda, confirmación y firma), probado sin red; falta correrlo en vivo con claves y los eventos de la vista 1 |
| `F2-portal-y-ataques.md` | Portal simulado y escenarios | Aprobado 28 oct; implementados F2-D1, F2-D2, F2-D3 y F2-D5: pedido en dos pasos (`/orders/new` con carrito vacío → `/review` → `/confirmation`), dirección de entrega editable, A3 en la revisión, escenario solo del lado del servidor, `GET /api/orders` con `SCORER_TOKEN`; F2-D4 hecho (texto oculto legítimo distinto por variante, también en A1–A3, sin mover un píxel, no marcado por el filtro) y el escenario límite `a1edge` (R10); falta la fuente local |
| `F3-agente-y-navegador.md` | Wonder con Playwright, con y sin supervisor | Borrador; implementados Wonder con herramientas `function` (F3-D5), Playwright real, el bucle de varios pasos con tope de 15 (R3, aprobado) y la acción sensible por la caja de SAM (R4) |
| `F4-canal-de-pixeles.md` | SAM y Spark sobre la captura | F4-D5 aprobado 1 nov; implementado con modelos reales: recortes reales (R7), cajas de SAM ajustadas por prompt de caja (R6), lectura por mosaicos; resultados por escenario y latencia: pendiente: se vuelve a medir en el dominio de entrega |
| `F5-comparacion-codigo-pixeles.md` | Divergencia código/píxeles y el filtro | Borrador; implementado el filtro «parece una instrucción», con el texto oculto legítimo probado |
| `F6-motor-de-decision.md` | Las reglas de decisión | Borrador; implementado (dirección atada por F1, divergencia filtrada por F5); falta la latencia medida (F4) |
| `F7-aprobacion.md` | Cápsula con voz y passkey | Borrador; implementada con R8: aprobación en la vista 5 por voz que coincide con los píxeles + clic en «Approve» (`ServiceApprover`, `approval/desk.py`, endpoints `/api/approval/*`, grabación WAV en el navegador); probado offline con transcriptor falso; falta la primera prueba con Voice real y micrófono real. Passkey (WebAuthn) opcional, no hecho |
| `F8-verificacion.md` | Verificación antes de confirmar y después del clic | Borrador |
| `F9-recibos-y-verify.md` | Recibos firmados y la CLI `verify` | Borrador; implementado el recibo real en el loop: id y hora generados, aprobación del aprobador, firma Ed25519 con la llave del dueño, `receipt.json` y recortes en `runs/<fecha>/<corrida>/`, `receipt.signed.path`; el paso 4 compara los valores leídos de los recortes (o el hash en recibos viejos) y respeta `blocked`; sin llave la corrida sigue y lo dice; falta que F8 entregue lo leído después del clic |
| `F10-witnessbench.md` | Las 20 corridas y los resultados | Borrador; implementado `bench/` (corridas reales, conteos R9) y `--edge` para el límite del filtro (R10, F10-D4, filas `r10_filter_limit` aparte); falta el caso del verificador que podría obedecer |
| `F11-interfaz.md` | Las vistas conectadas a los eventos | Borrador; implementada (WebSocket, 9 vistas, verify real, aviso de datos de prueba); faltan capturas y recortes reales (F3/F4), voz y passkey en vivo (F1/F7) |

Cada spec en borrador abre con una tabla de decisiones propuestas y una sección «Hallazgos para los specs siguientes». Falta revisarlos y aprobarlos.

Versiones editables en línea (fuente de verdad mientras se discuten; estos archivos son la copia del 28 de octubre de 2026):

- Spec general: https://claude.ai/artifact/MDNnDhTk7WBsuwN8SzD8C8
- Spec de construcción: https://claude.ai/artifact/ERY31GSR1FnpQS18TswN2b
- Spec de vistas: https://claude.ai/artifact/V43w8x3LqticCCBDWSVcZ8
- Maquetas (Claude Design): https://claude.ai/artifact/SoZszjAzJTnYJvehGp1dJ7
