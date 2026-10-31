# TESTIGO+ — Revisión de specs, código e infraestructura

31 de octubre de 2026 · Revisión para aprobación del equipo

Revisé los 15 specs, el código (≈4.500 líneas) y la infraestructura tal como están en la carpeta el 31 de octubre a mediodía. Este documento dice qué cambiar y en qué orden, y **manda sobre los demás specs donde los contradiga** hasta que el equipo apruebe o rechace cada decisión. Las decisiones nuevas van con el prefijo R.

## Resumen en cinco líneas

1. Los specs son buenos: el diseño de canales independientes, la regla de que el código decide y no un modelo, la honestidad sobre lo simulado y el benchmark con modelos reales son lo mejor del proyecto.
2. El problema es de ejecución: **ningún modelo de Meta está conectado todavía.** El agente real, el navegador real, SAM y el recorte de las capturas son esqueletos que lanzan `NotImplementedError`. El gate del 28 de octubre no aparece aprobado y el calendario del spec 01 ya va atrasado dos días.
3. Hay tres huecos de diseño que van a romper la integración si no se resuelven ya: el bucle es de **una sola acción**, el motor espera acciones **semánticas** («pay») cuando Wonder entrega **clics con coordenadas**, y el cliente usa el endpoint de chat cuando la documentación de Meta usa otro para computer use y para SAM.
4. Hay dos riesgos de reglas que no son técnicos: el equipo tiene 6 personas y el spec dice «máximo 4, verificado»; y el escenario es de **pagos**, que el equipo había excluido por la exclusividad con el banco.
5. Con 3,5 días, el alcance tiene que bajar: fuera Glimmer y WebAuthn real; la voz se queda; WitnessBench se queda pero contado con honestidad.

## 1. Estado real (verificado en el código, 31 oct)

| Pieza | Spec | Código | Estado |
| --- | --- | --- | --- |
| Portal y escenarios | F2 aprobado | `portal/server.py`, `scenarios.py` | Funciona offline. **El destinatario sigue siendo `<input type="hidden">`** (F2-D1 y F0-D10 no se implementaron), así que A1 y A2 no pueden tener éxito contra Wonder y g3 no puede correr. |
| Cliente de Meta | F0 aprobado | `common/meta_client.py` | Bien hecho (un solo punto de entrada, registro de gasto, tope, reintentos). Pero `segment()` (SAM) se niega, Voice asume `audio.transcriptions` y Wonder asume `chat.completions`. Nada probado contra la API. |
| Agente Wonder | F3 borrador | `agent/agent.py` | `ComputerUseAgent.propose` y `parse_action` lanzan `NotImplementedError`. |
| Navegador | F3 borrador | `agent/driver.py` | `PlaywrightDriver` solo tiene la forma; los cuatro métodos lanzan `NotImplementedError`. |
| Bucle | F3 | `agent/loop.py` | Hace **una** observación, **una** propuesta y **una** ejecución. La latencia es una constante (1.400 ms) y el recibo tiene id, hora y transcripción escritos a mano. |
| Canal de píxeles | F4 borrador | `interceptor/channels.py` | `_crop()` devuelve la captura entera: **el hash del «recorte» es el hash de toda la pantalla**, así que F8 y F9 hoy comparan pantallas completas, no recortes. |
| Motor, filtro, política, recibos, voz numérica, UI | F5–F7, F9, F11 | sí | Funcionan con datos de prueba. Son la parte más madura. |
| WitnessBench | F10 | no existe `bench/` | Sin código. |
| Gate | 00, F0 §13 | `gate/` solo tiene `__init__.py` | Ningún script del gate escrito; las casillas del 28 de oct siguen sin marcar. |
| Git | F0 §11 | 2 commits, ambos del 28 oct, ambos de una persona | Para un equipo, «contribución poco clara» es riesgo de descalificación. |

## 2. Decisiones nuevas

| ID | Tema | Propuesta | Por qué |
| --- | --- | --- | --- |
| R1 | Tamaño del equipo | Confirmar hoy en el Discord oficial el límite del track Startup. Fuentes secundarias dicen que Indie es hasta 4 y que Startup no publica límite; el spec 00 dice «máximo 4, verificado». Si el límite es 4, solo 4 personas se registran y solo esas 4 hacen commits. | Es descalificación, no puntaje. |
| R2 | Dominio de pagos | Opción A (recomendada): cambiar lo que se protege de **la cuenta de pago** a **la dirección de entrega** de un pedido a proveedor (robo de mercancía). El agente hace el pedido a Distribuidora X; el ataque cambia la dirección de entrega a la de un tercero. No hay dinero ni cuentas, el motor no cambia y la historia de Doña Marta se mantiene. Opción B: mantener el pago, después de revisar el contrato de exclusividad. | El equipo excluyó banca, fintech y pagos. Que se pueda crear una empresa no implica que se pueda trabajar en el dominio del empleador. |
| R3 | Bucle de varias acciones | El bucle repite observar → proponer → (interceptar) → ejecutar hasta que Wonder termine o se cumpla un tope de 15 pasos. Ver F3 §3b. | Wonder necesita al menos 4 pasos (agregar artículos, revisar, escribir/confirmar). Con una sola acción no hay demo. |
| R4 | De clic a acción sensible | Wonder entrega clics con coordenadas y texto tecleado, no «pay». La acción es **sensible** si el clic cae dentro de la caja que SAM da para el botón de confirmar (o de revisar), o si escribe en un campo protegido. La sensibilidad se decide con **píxeles**, nunca con el DOM. Solo las acciones sensibles pasan por el canal completo; las demás se registran y siguen. Ver F3 §3b. | Sin esto el motor no puede aplicarse a Wonder real, y sin limitar el canal a lo sensible la latencia y el costo se disparan. |
| R5 | Contrato de la API | Confirmar en g1, con las rutas de la documentación de Meta: computer use por la Responses API con la herramienta `computer` y elementos `computer_call` (dev.meta.ai/docs/computer-use); SAM 3.1 por `/v1/responses` con la máscara codificada como texto que se decodifica con `meta-sam-parser`; Voice Transcribe por archivo o por WebSocket en tiempo real. Ajustar `common/meta_client.py` a lo que responda la API. | Hoy el cliente asume endpoints que la documentación no usa. Estas rutas salen de la investigación del 31 de oct (documentación de Meta y fuentes secundarias); g1 las confirma o las corrige. |
| R6 | SAM: ¿solo texto o también cajas y puntos? | El spec 00 dice «solo prompts de texto en la API». La página dev.meta.ai/docs/sam/segmenting describe también cajas y puntos. Probarlo en g4: si acepta cajas, el plan B de F4 mejora mucho. | Contradicción entre fuentes. |
| R7 | Recortes reales | `_crop()` recorta el PNG a la caja de SAM con Pillow y el hash se calcula sobre ese PNG. Es un arreglo de 10 líneas y es prerrequisito de F8 y F9. | Hoy el aporte «hash de los recortes de evidencia» no es verdad en el código. |
| R8 | Recorte de alcance | Fuera: Glimmer local (F1-D1 ya lo hacía opcional) y WebAuthn real (F7-D4). La aprobación queda en **voz que coincide con los píxeles + clic de aprobar**, y la cápsula lo dice. Si sobra tiempo el 3 de nov, se agrega passkey. Dentro: voz para el mandato y la aprobación, SAM, Spark, Wonder. | WebAuthn en localhost con registro, aserción y verificación en el servidor es un día de trabajo y no suma puntaje. La voz sí suma: usa una herramienta de Meta. |
| R9 | WitnessBench honesto con n pequeño | 20 configuraciones × 2 modos. Reportar **conteos** («11 de 15 ataques funcionaron sin TESTIGO+; 0 de 15 con TESTIGO+; 0 de 5 falsos positivos»), no porcentajes, y la latencia como mediana y p90. Si el costo no alcanza, 10 configuraciones, dicho así. | Con 5 corridas por ataque un porcentaje sugiere una precisión que no existe. |
| R10 | Un ataque que el verificador no ve | Agregar al benchmark una variante A1 redactada sin ninguna señal del filtro (F5-D4) y reportarla aparte como límite conocido. | Un jurado técnico respeta más un límite medido que un 0 % perfecto. |
| R11 | Rúbrica | El spec 00 la llama «rúbrica oficial». Viene de blogs (madrobot.blog, aimagazine.blog), no de las Official Rules. Cambiar a «rúbrica reportada». | Exactitud. |

## 3. Calendario nuevo (sustituye la tabla del spec 01)

Hoy es sábado 31 de octubre. La entrega cierra el miércoles 4 de noviembre a las 9 PM de Bogotá (ese día ET = UTC-5). Cada corte es una pregunta de sí o no.

| Cuándo | Qué se construye | Corte (sí/no) | Si no |
| --- | --- | --- | --- |
| **Sáb 31, 13:00–17:00** | g1: llamada real desde Bogotá a los 4 modelos (R5). Portal: destinatario editable (F2-D1) y, si se aprueba R2, dirección de entrega. `_crop()` real (R7). | Los 4 modelos responden desde Bogotá sin VPN. | Escalar a soporte de Meta y Discord. Sin API no hay proyecto. |
| **Sáb 31, 17:00–23:59** | g2: Wonder maneja el portal `clean` con Playwright; `parse_action` se llena con las respuestas crudas; el bucle de varias acciones (R3). g4: SAM sobre 30 capturas. | Wonder completa `clean` 2 de 3 veces y todas sus acciones pasan por el gancho. | Plan B: Spark con function calling y acciones de alto nivel (`click_element`, `type_into`) contra el mismo portal, dicho con honestidad en el README. Baja el uso de Meta. |
| **Dom 1** | g3: A1, A2, A3 contra Wonder sin supervisor. `SamSparkChannel` real. Regla R4 (acción sensible por píxeles). | Al menos un ataque funciona 2 de 3 veces sin supervisor y se bloquea con supervisor. | Ajustar redacción, posición y contraste de los ataques. Si Wonder resiste todo, contarlo: es un hallazgo, y el benchmark mide eso. |
| **Lun 2 (festivo)** | F8 en los dos momentos, recibos unificados (F9), mandato y aprobación por voz real (F1, F7 con R8). Primeras 5 corridas reales de punta a punta. | Una corrida real deja recibo y `testigo verify` lo valida y detecta uno alterado. | Recortar la voz del mandato; dejar la política escrita y la voz solo en la aprobación. |
| **Mar 3** | WitnessBench completo (R9, R10). UI con eventos reales. **Congelar a las 18:00.** Grabar por la noche. | `bench_results.json` existe y la vista 8 lo pinta sin el aviso de ejemplo. | Benchmark de 10 configuraciones. |
| **Mié 4** | Editar el video, README, repo público. **Entregar antes de las 15:00.** | Enviado. | — |

## 4. Reparto sugerido

Válido para 4 personas (si R1 lo exige). Si son 6, los frentes 2 y 4 se parten en dos.

| Frente | Dueño | Specs |
| --- | --- | --- |
| 1. API y gate: g1, ajuste del cliente (R5), registro de uso, presupuesto | P1 | F0 |
| 2. Agente y navegador: Playwright real, bucle de varias acciones, `parse_action`, regla R4 | P2 | F3 |
| 3. Píxeles y decisión: SAM real, recortes (R7), Spark con esquema, motor, F8 | P3 | F4, F5, F6, F8 |
| 4. Portal, voz, recibos, benchmark, UI y video | P4 | F1, F2, F7, F9, F10, F11 |

Cada frente hace commits pequeños con su propia identidad de git y en su rama (F0 §11). Un historial con un solo autor es exactamente la «contribución poco clara» que puede descalificar.

## 5. Infraestructura y stack

**Lo que está bien y se conserva**

- Python 3.12 + FastAPI + uvicorn + Playwright + `openai` + `cryptography`: el stack es pequeño, conocido y suficiente. Sin Node ni build: correcto para 4 días.
- Un solo cliente de Meta con registro de gasto en `runs/usage.jsonl`, tope `MAX_SPEND_USD` y reintentos solo en errores de red: es la mejor pieza de infraestructura del repo.
- El servicio del interceptor ya se defiende de DNS rebinding y de peticiones de otro origen (`local_page_only`, `origin_ok`), y solo acepta escrituras con cuerpo JSON. Bien pensado, dado que el portal atacante corre en la misma máquina.
- `make run`, `make check-secrets`, la prueba de que nadie más crea clientes de la API y la que impide usar datos de prueba fuera de `tests/`.

**Lo que hay que cambiar**

| # | Problema | Cambio |
| --- | --- | --- |
| I1 | El cliente asume `chat.completions` para Wonder, `audio.transcriptions` para Voice y no tiene SAM (R5). | Agregar `computer_step()` sobre la Responses API, `segment()` sobre `/v1/responses` + `meta-sam-parser`, y `transcribe()` por el endpoint que confirme g1. Registrar uso y costo igual que hoy. |
| I2 | Precios de SAM: el cliente cobra USD 2,50 por 1.000 imágenes; en video la tarifa reportada es USD 0,20 por 1.000 cuadros. | Solo se usan imágenes, así que el precio vale; anotar la fuente y revisarla en g1 contra la factura real. |
| I3 | El precio de Spark 1.3 (1,25/4,25) no aparece en una tarifa oficial de Meta según una fuente; otra lo da. | Confirmarlo con el gasto real de `usage.jsonl` y la consola de facturación tras g1. |
| I4 | `requirements.lock` no fija hashes. | Para un repo público basta como está; si sobra tiempo, `pip-compile --generate-hashes`. Bajo prioridad. |
| I5 | `.venv` es de macOS y solo hay un `Makefile`. | Fijar una sola máquina de demo (la de grabación) y que las demás solo corran `make test`. No invertir en Docker ahora. |
| I6 | Costo de WitnessBench sin medir. | Tras g2, multiplicar el costo medido de una corrida `clean` por 40 (20 configuraciones × 2 modos) y fijar `MAX_SPEND_USD` con ese número + 30 %. Repartir las corridas entre las cuentas del equipo si hace falta (cada persona tiene USD 150). |
| I7 | Contributor mode. | Usar claves Standard, nunca una suscripción de Muse Code en modo Contributor: entrena con el contenido (F0 lo dice para material sensible; aquí además las capturas son la evidencia). |
| I8 | Sin integración continua. | Un GitHub Action con `make test` sin claves en el repo público (ya creado). 15 minutos; protege `main` cuando cuatro personas hacen merge el mismo día. |

## 6. Cambios de texto en los specs existentes

| Spec | Cambio |
| --- | --- |
| 00 | Rúbrica «reportada», no «oficial» (R11). Fila «Equipos»: de «Verificado» a «Por confirmar para el track Startup» (R1). Riesgo nuevo: dominio de pagos (R2). Sección «Estado actual»: apuntar a este documento. |
| 01 | El calendario queda sustituido por la sección 3 de este documento. |
| F3 | Nueva sección 3b (bucle de varias acciones y acción sensible por píxeles, R3 y R4). |
| F4 | Recorte real (R7) y la prueba de cajas/puntos de SAM (R6). |
| F7 | Passkey pasa a opcional (R8). |
| F10 | Conteos en vez de porcentajes y el caso límite aparte (R9, R10). |

Los cambios de 00 y F3 ya están aplicados en este commit de specs; los de F4, F7 y F10 quedan cubiertos por las decisiones R6 a R10 de este documento hasta que el dueño de cada spec los pase.

## 7. Lo que no está verificado

- El límite de equipo del track Startup y el texto de las Official Rules (detrás de inicio de sesión).
- Las rutas exactas de la API de Meta para computer use, SAM y Voice: salen de la documentación citada en la investigación del 31 de oct, pero nadie del equipo las ha llamado todavía.
- Si SAM 3.1 por API acepta cajas y puntos (R6).
- El costo real por corrida de Wonder.
