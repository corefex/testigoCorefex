# Specs de TESTIGO+

Documentos de diseño del proyecto. Se escriben antes del código y el código los sigue.

| Archivo | Qué es |
| --- | --- |
| `00-spec-general.md` | Qué es TESTIGO+, objetivo, reglas de Meta, alcance, arquitectura, features (F0 a F11), riesgos y gate. Es la base de todos los demás. |
| `01-spec-construccion.md` | Correcciones a las maquetas, piezas del sistema, portal simulado y ataques, vistas reales, formatos y orden de construcción. |
| `02-spec-vistas-maquetas.md` | Spec de las 8 vistas y la portada usadas para las maquetas en Claude Design. |
| `03-revision-31-oct.md` | Revisión del 31 de oct: estado real del código, decisiones R1 a R11, calendario nuevo hasta el 4 de nov, infraestructura y stack. **Manda sobre los demás donde los contradiga.** |

Specs de cada feature (objetivo, entradas y salidas, criterios de aceptación, qué se prueba con modelos reales y qué con datos de prueba, y qué del código actual se conserva):

| Archivo | Feature | Estado |
| --- | --- | --- |
| `F0-infraestructura.md` | Estructura del repositorio, instalación, secretos, API de Meta, Playwright, pruebas, gate | Aprobado 28 oct; implementado; del gate solo está g1 (pasa 5/5 contra la API real el 31 oct) |
| `F1-mandato-y-politica.md` | Mandato por voz y política firmada | Borrador; implementado el núcleo offline (formato con cuenta atada, firma Ed25519, compilación desde texto); falta la compilación por voz real (Voice + Spark, necesita claves) |
| `F2-portal-y-ataques.md` | Portal simulado y escenarios | Aprobado 28 oct; implementados F2-D1 (destinatario editable) y el `data-testid` neutro de A1; faltan el pago en dos pasos, la revisión y A3 en ella |
| `F3-agente-y-navegador.md` | Wonder con Playwright, con y sin supervisor | Borrador; implementados Wonder con herramientas `function` (F3-D5), Playwright real, el bucle de varios pasos con tope de 15 y la acción sensible por la caja de SAM (R4); con supervisor, un clic sensible se bloquea con `cannot_verify` hasta que F4 lea los recortes |
| `F4-canal-de-pixeles.md` | SAM y Spark sobre la captura | Borrador; implementado con modelos reales (F4-D5): recortes reales (R7), cajas de SAM ajustadas por prompt de caja (R6), lectura por mosaicos; 0 falsos positivos en `clean` v1–v5 y A1/A2 bloqueados en las variantes probadas; latencia medida 8–16 s por comprobación |
| `F5-comparacion-codigo-pixeles.md` | Divergencia código/píxeles y el filtro | Borrador; implementado el filtro «parece una instrucción», con el texto oculto legítimo probado |
| `F6-motor-de-decision.md` | Las reglas de decisión | Borrador; implementado (cuenta atada por F1, divergencia filtrada por F5); falta la latencia medida (F4) |
| `F7-aprobacion.md` | Cápsula con voz y passkey | Borrador; implementada la coincidencia de voz (número en español → entero, comparación contra los píxeles); faltan WebAuthn y Voice real (claves/navegador) |
| `F8-verificacion.md` | Verificación antes de confirmar y después del clic | Borrador |
| `F9-recibos-y-verify.md` | Recibos firmados y la CLI `verify` | Borrador; implementado el recibo real en el loop: id y hora generados, aprobación del aprobador, firma Ed25519 con la llave del dueño, `receipt.json` y recortes en `runs/<fecha>/<corrida>/`, `receipt.signed.path`; el paso 4 compara los valores leídos de los recortes (o el hash en recibos viejos) y respeta `blocked`; sin llave la corrida sigue y lo dice; falta que F8 entregue lo leído después del clic |
| `F10-witnessbench.md` | Las 20 corridas y los resultados | Borrador |
| `F11-interfaz.md` | Las vistas conectadas a los eventos | Borrador; implementada (WebSocket, 9 vistas, verify real, aviso de datos de prueba); faltan capturas y recortes reales (F3/F4), voz y passkey en vivo (F1/F7) |

Cada spec en borrador abre con una tabla de decisiones propuestas y una sección «Hallazgos para los specs siguientes». Falta revisarlos y aprobarlos.

Versiones editables en línea (fuente de verdad mientras se discuten; estos archivos son la copia del 28 de octubre de 2026):

- Spec general: https://claude.ai/artifact/MDNnDhTk7WBsuwN8SzD8C8
- Spec de construcción: https://claude.ai/artifact/ERY31GSR1FnpQS18TswN2b
- Spec de vistas: https://claude.ai/artifact/V43w8x3LqticCCBDWSVcZ8
- Maquetas (Claude Design): https://claude.ai/artifact/SoZszjAzJTnYJvehGp1dJ7
