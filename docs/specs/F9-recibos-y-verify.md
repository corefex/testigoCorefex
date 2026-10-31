# TESTIGO+ — F9: Recibos firmados y `verify`

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F9 del spec general: cada acción supervisada deja un recibo firmado, y cualquiera puede comprobarlo sin confiar en nosotros. Es la salida verificable del sistema: no decide nada, solo registra y prueba lo que ya decidió el motor (F6) y verificó F8. Si algo aquí contradice a `00-spec-general.md` o `01-spec-construccion.md`, mandan esos; lo que no esté en ningún spec va marcado como **[DECIDIR]**. Todo es simulación; la firma y la verificación son reales.

## Decisiones pendientes

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F9-D1 | Qué firma exactamente «la política firmada» (hueco 3 de F0) | La política lleva su propia firma Ed25519 del mismo par de llaves del dueño, y el recibo guarda el `policy_sha256`. El passkey autentica a la persona en el momento de aprobar (F7); la firma Ed25519 da integridad al archivo. Son dos cosas distintas y el recibo nombra ambas. | F1 y la coherencia del recibo |
| F9-D2 | Los campos del recibo: el código actual usa `amount`/`recipient`, el spec 01 usa `crop_amount`/`crop_recipient` | Usar los del spec 01 (`crop_amount`, `crop_recipient`), y cambiar el código. El contrato manda sobre el código. | el formato |
| F9-D3 | Custodia de la llave de firma | Una llave por equipo para la demo, en `.secrets/receipts.key` (F0), nunca en el repositorio. La pública se publica para que cualquiera verifique. | la firma |
| F9-D4 | Qué guarda `executed` cuando el pago se bloqueó en la revisión y nunca se confirmó (hueco 2 de F0) | Entonces no hay «ejecutado»: el recibo es de un intento **bloqueado**, con `executed: null` y un `blocked_at` que dice dónde (revisión o resultado). Un recibo con `executed` solo existe si el pago se confirmó. | F8 y las vistas 6 y 7 |

## 1. Objetivo

Que al final de cada acción supervisada quede un archivo que: nombre la política bajo la que corrió, guarde los hashes de los recortes aprobados y, si hubo confirmación, los de los ejecutados, diga cómo se aprobó, y lleve una firma Ed25519 sobre todo lo demás. Y una herramienta, `testigo verify`, que cualquiera corre contra ese archivo y su evidencia, sin cuenta ni acceso a nosotros, y que da válido para un recibo bueno y señala exactamente dónde falla uno alterado o uno que registra una divergencia.

El aporte propio (spec general): el recibo incluye el **hash de los recortes de evidencia visual**. Lo demás (recibos firmados para agentes) ya existe y se cita como tal.

Fuera de alcance de F9: capturar, segmentar, comparar o decidir. F9 recibe los hashes ya calculados por F4 y F8 y la política de F1, y solo arma, firma y verifica.

## 2. Entradas y salidas

**Entradas**

- De F8: los hashes de los recortes aprobados y, si se confirmó, los ejecutados, más su estado (coincide o no coincide) y, si se bloqueó, dónde.
- De F1: la política firmada y su `sha256`.
- De F7: cómo se aprobó (passkey y transcripción de la voz).
- La llave privada de firma, en `.secrets/receipts.key` (F0).
- Para verificar: el `receipt.json`, la carpeta de evidencia con los PNG de los recortes, la política, y opcionalmente la llave pública fijada.

**Salidas**

- Un `receipt.json` firmado por acción, y su carpeta de evidencia, bajo `runs/evidence/<corrida>/` (git-ignorada).
- El resultado de `testigo verify`: un listado de cuatro comprobaciones y una línea final, con código de salida 0 solo si todas pasan.

## 3. El recibo

Formato del spec 01, con `amount_cop` explícito y el campo de estado que resuelve F9-D4:

```json
{"id": "rcpt_2041_7f3a", "time": "2026-10-28T09:16:05-05:00",
 "agent": "wonder@marta-shop",
 "action": "pay COP 120,000 -> Distribuidora X · 310-XXX-4417",
 "amount_cop": 120000,
 "recipient": "Distribuidora X · 310-XXX-4417",
 "policy_sha256": "....",
 "approved": {"crop_amount": "....", "crop_recipient": "...."},
 "executed": {"crop_amount": "....", "crop_recipient": "...."},
 "status": "confirmed",
 "approval": {"method": "passkey", "voice_transcript": "ciento veinte mil pesos a Distribuidora X"},
 "signed_by": "passkey:marta",
 "pubkey": "....",
 "signature": "ed25519:...."}
```

- `status` es `confirmed` (el pago se ejecutó) o `blocked` (nunca se confirmó). Si es `blocked`, `executed` es `null` y se agrega `"blocked_at": "review"` o `"result"` (F9-D4).
- `pubkey` es la llave pública del firmante, en hexadecimal. Está por comodidad; la confianza viene de fijarla aparte (sección 5).
- La hora sale del reloj de Bogotá real (`common/clock.py`), no de una hora local con el huso pegado (hueco de F0 que F9 ya cumple al usar `common`).
- Los hashes son los mismos `sha256` que calculó el canal de píxeles sobre los PNG de los recortes: el número del recibo es el número que se comprobó.

**Qué firma la firma.** La firma Ed25519 cubre el recibo canónico: todos los campos menos `signature`, serializados de forma estable. Incluye `pubkey`, así que no se puede re-apuntar el recibo a otra llave sin volver a firmarlo.

## 4. Las cuatro comprobaciones de `verify`

En orden; la primera que falla decide el mensaje:

1. **Política.** El `policy_sha256` del recibo es igual al hash de la política firmada que se pasa.
2. **Firma.** La firma Ed25519 es válida para el cuerpo canónico del recibo, con la llave fijada (o la del recibo si no se fija una).
3. **Aprobados.** Cada recorte aprobado de la carpeta de evidencia tiene el `sha256` que el recibo registra.
4. **Ejecutados.** Si `status` es `confirmed`, los recortes ejecutados coinciden con los aprobados (y con los archivos). Si es `blocked`, este paso no aplica y se marca como tal.

Dos fallos distintos, los dos de la vista 7:

- **Recibo alterado** → falla el paso 2 → «Signature invalid».
- **Recibo honesto de un ataque atrapado** → pasan 1 a 3, falla el 4 → «Evidence mismatch at step 4». La firma es válida: el recibo registra con honestidad que lo ejecutado difirió de lo aprobado.

Sin la carpeta de evidencia, los pasos 1, 2 y la parte registrada del 4 corren igual; el 3 y la mitad de archivos del 4 se saltan y se dice.

## 5. Firma Ed25519 y custodia de llaves

- **Biblioteca `cryptography`** (spec de construcción), ya en el código.
- La **llave privada** vive en `.secrets/receipts.key` (F0), fuera del repositorio; se crea con `testigo keygen`. Una por equipo para la demo (F9-D3).
- La **llave pública** se publica, para que cualquiera verifique: en el repositorio como texto, y en `examples/` junto a recibos sintéticos (F0 D7).
- **Modelo de confianza.** El recibo trae su `pubkey`, pero eso es comodidad, no la raíz de la confianza: se fija la llave esperada por fuera y se verifica contra ella (`testigo verify receipt.json --pubkey <hex>`). Como la firma cubre `pubkey`, un recibo no se puede re-apuntar a otra llave sin la privada de esa llave.
- La llave de la demo no se reutiliza fuera de la demo. Si una llave privada se filtra, se revoca y se re-firma; borrarla del historial no basta.

## 6. La CLI `testigo verify`

- `testigo verify <receipt.json> [--evidence <carpeta>] [--policy <archivo>] [--pubkey <hex>]`. La carpeta de evidencia se detecta sola si está junto al recibo.
- Salida como la vista 7: cuatro líneas `[n/4] ✓|✗ ...` y una línea final. Código de salida 0 solo si las cuatro pasan.
- Se instala como el comando `testigo` (F0, `pyproject.toml`). También `testigo keygen` para crear o mostrar la llave.
- En la demo (vista 7) se ejecuta de verdad, en vivo, sobre el recibo de la corrida real.

## 7. Criterios de aceptación de F9

1. Un recibo `confirmed` bueno pasa las cuatro comprobaciones y `verify` sale con 0.
2. Un recibo con un campo cambiado falla el paso 2 («Signature invalid»), salida 1.
3. Un recibo honesto cuyo ejecutado difiere del aprobado pasa 1 a 3 y falla el 4 («Evidence mismatch at step 4»), salida 1, con la firma válida.
4. Un recibo `blocked` no afirma un ejecutado: `executed` es `null`, `blocked_at` dice dónde, y `verify` no inventa un paso 4.
5. Cambiar un archivo de recorte de la evidencia hace fallar el paso 3.
6. Fijar la llave pública correcta verifica; fijar otra, no.
7. Los campos son los del spec 01 (`crop_amount`, `crop_recipient`), y el `policy_sha256` es el mismo que reporta `interceptor/policy.py`.
8. Las pruebas de recibos pasan (las 11 actuales, adaptadas a los campos y al estado `blocked`).

## 8. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F9 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| Firma y verificación | No aplica (es criptografía, no un modelo) | Pruebas con recibos de prueba: firma válida, alteración, divergencia, evidencia cambiada, llave fijada |
| El recibo de la demo (vista 7) | Sí: sale de una corrida real con Wonder, SAM y Spark (F10) | — |
| `examples/` | No aplica | Recibos sintéticos con una llave desechable, solo para que cualquiera pruebe la CLI |

F9 en sí no llama a ningún modelo. El recibo del video sale de una corrida real; los recibos de prueba solo comprueban la criptografía y nunca aparecen como resultado.

## 9. Qué del código actual se conserva

| Archivo | Se conserva | Cambia | Sale |
| --- | --- | --- | --- |
| `receipts/keys.py` | Entero: keygen, firmar, verificar con `cryptography`; llave en `.secrets/` | — | — |
| `receipts/receipt.py` | La serialización canónica, la firma y la verificación de firma | Campos del spec 01 (`crop_amount`, `crop_recipient`); agregar `status`, `amount_cop`, `blocked_at`; la hora desde `common/clock.py` | — |
| `receipts/verify.py` | Las cuatro comprobaciones y el objeto de resultado | El paso 4 respeta `status: blocked` (no inventa un ejecutado) | — |
| `receipts/cli.py` | `verify` y `keygen`, la salida de cuatro pasos, el comando `testigo` | — | — |
| `receipts/test_receipts.py` | Las 11 pruebas | Adaptarlas a los campos nuevos y agregar el caso `blocked` | — |
| `tests/fixtures/bundles.py` | El armador de recibos de prueba (ya movido a `tests/` en F0) | Reflejar los campos nuevos | — |

El armado del recibo desde una corrida real (no desde datos de prueba) lo conecta F8, que entrega los hashes; F9 provee la función que, dados esos hashes y la política, arma y firma. El `build_receipt` de relleno que quedó en `agent/loop.py` se reemplaza por esa función.

## Hallazgos para los specs siguientes

1. **F8.** F9 necesita de F8 el estado (`confirmed` o `blocked`), dónde se bloqueó, y los dos grupos de hashes. Si F8 bloquea en la revisión, entrega un recibo `blocked`; solo si se confirma hay `executed`.
2. **F1.** La firma de la política (F9-D1) la produce F1 con el mismo par de llaves; F9 solo guarda su `sha256` y confía en que F1 la firmó. Conviene que F1 use `receipts/keys.py` para no tener dos caminos de firma.
3. **F10.** WitnessBench no firma recibos por corrida (serían 20 llaves de evidencia); firma solo las corridas que llegan a un pago. El recibo del video es una de esas, hecha en vivo.

## Implementación (31 de octubre)

- **Recibo real en el loop.** `receipts/bundle.py` arma y firma el recibo de un pago aprobado y ejecutado; `agent/loop.py` lo llama (el `build_receipt` de relleno salió). El id se genera (`rcpt_<fecha>_<hora>_<4 hex>`), la hora sale de `common/clock.py`, el método y la transcripción salen de lo que devolvió el aprobador, `signed_by` es `<método>:<dueño>`, el `policy_sha256` es el de la política cargada y los hashes se calculan sobre los bytes reales de los recortes. Se escribe `receipt.json` con `approved_*.png` (y `executed_*.png` si hubo captura después del clic) en `runs/<fecha>/<corrida>/` (no en `runs/evidence/`), y `receipt.signed` lleva el `path` relativo a `runs/`. `run()` tiene `run_dir` (None: no escribe) y `signing_key` (semilla o ruta; None: `SIGNING_KEY_PATH`).
- **Sin llave no se cae.** Si no hay llave (o no se puede leer), la corrida sigue y emite `agent.step` «receipt not signed: …»; la llave no se crea sola (`testigo keygen`). Un driver de prueba nunca firma con la llave del dueño; `run_fixture` firma con una desechable.
- **Comparación por valores leídos.** Con recortes reales, la misma región en dos capturas no da el mismo hash (las cajas de SAM se mueven unos píxeles y la revisión tiene otro diseño). El recibo guarda, además de los hashes (integridad de los archivos), el texto leído (`read.approved`, `read.executed`) y la comparación firmada (`comparison`: `match`/`mismatch`/`pending`, `by`: `read`/`hash`). Lo aprobado se lee del evento `approval.requested` (monto y destinatario leídos de los píxeles); lo ejecutado lo entregará F8 (`sign_payment(..., executed_read=…)`). El paso 4 de `verify` recalcula la comparación desde los valores firmados (monto: solo dígitos; destinatario: letras y dígitos en minúscula), comprueba que los `executed_*.png` tengan su hash, y si el recibo no trae `read` compara por hash: así `examples/` sigue dando los mismos mensajes.
- **`status`.** `confirmed` o `blocked` (con `executed: null` y `blocked_at`; el paso 4 «no aplica»). Un `confirmed` sin nada capturado después del clic (hoy, en corridas reales, hasta F8) se firma con `executed: null` y `comparison: pending`, y `verify` falla el paso 4 con «Executed evidence not recorded at step 4»: no inventa un ejecutado.
- **Abierto.** F9-D2 sigue sin aplicar: los campos se quedan como `amount`/`recipient` porque la vista 7 y `examples/` los leen así. La normalización de lo leído debe coincidir con la de F8.
