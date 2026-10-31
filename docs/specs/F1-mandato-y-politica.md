# TESTIGO+ — F1: Mandato por voz y política

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F1 del spec general: la dueña dice, hablando, qué puede hacer el agente, y queda una política firmada que el motor (F6) hace cumplir. Si algo aquí contradice a `00-spec-general.md`, `01-spec-construccion.md` o `02-spec-vistas-maquetas.md`, mandan esos. Todo es simulación; la voz, la compilación y la firma son reales.

## Decisiones pendientes

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F1-D1 | Qué compila la voz en reglas: Glimmer local o Spark por API | Spark por API (a través de `common/meta_client.py`); Glimmer solo si hay una GPU de 24 GB (opcional, del spec general). La compilación pide a Spark una extracción con formato fijo, no una decisión. | la política |
| F1-D2 | La política ata el destinatario solo por nombre (hueco 1 de F0) | Atar también la cuenta: `pay_only` guarda nombre **y** cuenta (`Distribuidora X · 310-XXX-4417`). Un cambio de cuenta con el nombre intacto ya no cumple la regla 3. | F6 |
| F1-D3 | Qué firma la política | Una firma Ed25519 del par de llaves del dueño (el mismo de los recibos, `receipts/keys.py`), más el registro de que un passkey la respaldó (F7). El archivo guarda su `sha256` y su firma. | F9 |
| F1-D4 | Si la compilación por voz es en vivo en la demo o preparada antes | En vivo en la vista 1: se graba, se transcribe y se compila mientras se ve. La política resultante se firma y queda en un archivo que el resto del sistema lee. | la vista 1 |

## 1. Objetivo

Que la dueña defina los límites del agente hablando, y que de ahí salga un archivo de política firmado y legible por máquina, con tres reglas: a quién se puede pagar, el máximo por pago, y cuándo preguntar. El motor (F6) lo hace cumplir; la interfaz (vista 1) muestra la onda, la transcripción y las reglas compiladas con su sello.

Fuera de alcance de F1: decidir sobre una acción (F6), aprobar un pago (F7). F1 solo produce la política.

## 2. Entradas y salidas

**Entradas**

- La voz de la dueña por el micrófono del navegador.
- Un passkey para respaldar la política (F7-D1, F1-D3).

**Salidas**

- La transcripción de la voz (Voice Transcribe).
- Un archivo de política firmado, en el formato del spec de construcción, con nombre y cuenta en `pay_only` (F1-D2).
- Los eventos para la vista 1: escuchando, transcribiendo, política firmada.

## 3. El formato de la política

Del spec de construcción, con la cuenta atada (F1-D2) y la firma (F1-D3):

```yaml
version: 1
owner: marta
source: voice
transcript: "Solo puedes pagarle a Distribuidora X, máximo ciento cincuenta mil pesos"
rules:
  - pay_only:
      - name: "Distribuidora X"
        account: "310-XXX-4417"
  - max_per_payment_cop: 150000
  - ask_before: new_recipient
signed_by: passkey:marta
sha256: "...."
signature: "ed25519:...."
```

- `pay_only` pasa de una lista de nombres a una lista de `{name, account}`. El código actual (`interceptor/policy.py`) solo mira el nombre; F1 y F6 lo cambian para exigir ambos.
- `sha256` es el hash del contenido canónico (todo menos `sha256` y `signature`), el mismo que ya calcula `interceptor/policy.py`.
- `signature` la agrega F1 al firmar; hoy el archivo solo lleva el hash.

## 4. Cómo se compila la voz

1. Se graba la voz y se transcribe con Voice Transcribe (español), vía `common/meta_client.py`.
2. Se le pide a Spark (o Glimmer) una extracción con formato fijo: de la transcripción, sacar el destinatario permitido (nombre y, si se dice, cuenta), el máximo por pago en pesos, y si pide preguntar antes de un nuevo destinatario. Spark devuelve esos campos en un esquema fijo; no decide nada ni recibe instrucciones de la transcripción como órdenes.
3. Se arma el YAML, se calcula el `sha256` y se firma con Ed25519 (`receipts/keys.py`), respaldado por el passkey.
4. El archivo queda donde el resto del sistema lo lee (`policy/` o `runs/`, a decidir al implementar).

Como el destinatario de la demo no lleva cuenta en la frase hablada («Solo puedes pagarle a Distribuidora X…»), la cuenta se toma del catálogo del portal para esa demo; en un caso real la diría la dueña. Esto se anota como simulado.

## 5. Criterios de aceptación de F1

1. Una grabación de la frase de ejemplo produce una política con `pay_only` = Distribuidora X (nombre y cuenta), `max_per_payment_cop` = 150000 y `ask_before` = new_recipient.
2. El archivo lleva un `sha256` correcto y una firma Ed25519 válida para ese contenido.
3. `interceptor/policy.py` lee el formato nuevo (nombre y cuenta) y su hash coincide con el que reporta.
4. La vista 1 muestra los tres estados (escuchando, transcribiendo, firmada) desde eventos reales.
5. La compilación usa Spark (o Glimmer) solo como extractor de formato fijo; la transcripción nunca se ejecuta como instrucción.
6. La voz numérica en español cumple el umbral del gate (95 % exacto, menos de 1,5 s).

## 6. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F1 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| Transcripción | Sí: Voice Transcribe | Pruebas de la compilación con transcripciones fijas → YAML esperado |
| Compilación a reglas | Sí: Spark (o Glimmer), como extractor | Pruebas del esquema fijo y del armado del YAML |
| Firma y hash | No aplica (criptografía) | Pruebas: hash correcto, firma válida, lectura por `policy.py` |

La transcripción y la extracción son de modelos reales; el armado y la firma se prueban con datos de prueba. La política de la demo sale de voz real.

## 7. Qué del código actual se conserva

| Archivo | Se conserva | Cambia | Sale |
| --- | --- | --- | --- |
| `interceptor/policy.py` | La carga, el cálculo del hash, las comprobaciones de destinatario y monto | `pay_only` con `{name, account}`; exigir que la cuenta coincida (no solo el nombre); leer la firma | — |
| `policy/marta.policy.yaml` | De ejemplo | Al formato nuevo (cuenta atada, firma) | — |

El compilador por voz es código nuevo (propuesta: `policy/compile.py`), con Voice y Spark a través de `common/meta_client.py` y la firma con `receipts/keys.py`. La vista 1 es parte de la interfaz (F11).

## Hallazgos para los specs siguientes

1. **F6.** Atar la cuenta (F1-D2) cierra el hueco 1 de F0: un ataque que cambie la cuenta pero deje el nombre ya no cumple la regla 3. F6 debe exigir que coincidan nombre y cuenta leídos de los píxeles.
2. **F9.** La firma de la política y la de los recibos usan el mismo par de llaves (`receipts/keys.py`); conviene un solo camino de firma.
3. **F7.** El passkey que respalda la política es el mismo que aprueba los pagos; un solo registro de passkey para la demo.

## Implementación (31 de octubre)

Hecha la compilación por voz real en `policy/compile.py` (subcomando `mandate`), con R8 aplicado (Spark por API, sin Glimmer ni passkey).

1. **Voz.** Voice Transcribe sobre un WAV (`common/meta_client.py`, idioma detectado por la API).
2. **Extracción.** Spark llena un esquema JSON fijo y estricto (`response_format` `json_schema`, `strict`; `reasoning_effort="low"`, `max_tokens=16000`): proveedores (`name`, `account` solo si se dijo), el monto máximo copiado tal como se dijo (`max_amount_words`), ese monto en pesos y si pidió preguntar antes de un destinatario nuevo. La transcripción va como dato entre comillas, nunca como instrucción.
3. **Validación por código.** Se rechaza (y no se firma nada) todo lo que salga del esquema: llaves de más o de menos, tipos distintos, contenido vacío o no JSON. Además se compara con la transcripción: el nombre del proveedor y las palabras del monto tienen que estar en lo que se dijo (sin tildes ni mayúsculas; «equis» se lee como «x»), y el monto se vuelve a leer por código (`approval/voice_match.spanish_to_int`, también «150 mil» y «150.000»). Si el entero de Spark no coincide con esa lectura, se rechaza.
4. **Cuenta atada por nombre (F1-D2).** La cuenta sale del directorio de proveedores conocidos (el del banco simulado del portal, `portal/scenarios.ACCOUNT_NAMES`; simulado). Un proveedor que no está en el directorio se rechaza; una cuenta dicha que no coincide con la del directorio se rechaza.
5. **Preguntar antes.** `ask_before` queda siempre en `new_recipient` (por defecto seguro, criterio 1); si la dueña no lo dijo, la salida lo marca «por defecto».
6. **Confirmación y firma.** Se imprimen la transcripción y las tres reglas; la dueña confirma en la terminal (`[s/N]`, o `--yes` en una demo guionada) en lugar del passkey (R8). Luego se estampa el `sha256` y se firma con Ed25519 con la llave del dueño (`SIGNING_KEY_PATH`). `signed_by` queda `owner-key:marta`.
7. **Dónde queda.** Por defecto en `runs/mandate/marta.policy.yaml` (ignorado por git), para no pisar la política de la demo. Para que el interceptor la use hay que pedirlo con `--out policy/marta.policy.yaml`.

Para correrlo en vivo (necesita `.env` con `META_API_BASE_URL`, `META_API_KEY`, `META_MODEL_VOICE` y `META_MODEL_SPARK`):

```sh
sh scripts/make_mandate_wav.sh /tmp/mandato.wav      # macOS: voz Paulina → WAV 16 kHz mono
.venv/bin/python -m policy.compile mandate /tmp/mandato.wav
.venv/bin/python -m policy.compile mandate /tmp/mandato.wav --out policy/marta.policy.yaml   # reemplaza la de la demo
.venv/bin/python -m policy.compile mandate --text "Solo puedes pagarle a Distribuidora X, máximo ciento cincuenta mil pesos"   # sin Voice
```

Pruebas sin red en `tests/test_policy_compile.py` con un cliente falso: rechazo por esquema, cuenta atada, proveedor desconocido o no dicho, monto releído, hash estampado y firma válida, nada escrito si no se confirma. El audio no se guarda en el repositorio.

Falta: los eventos de la vista 1 (escuchando, transcribiendo, firmada) y la grabación desde el micrófono del navegador (F11); el criterio 6 (95 % exacto, menos de 1,5 s) se mide en el gate, no aquí; probarlo en vivo con las claves.
