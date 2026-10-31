# TESTIGO+ — F7: Aprobación

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F7 del spec general: la cápsula con la que la persona aprueba lo que realmente va a pasar, vista en recortes reales de la pantalla, confirmada en voz alta y firmada con passkey. Responde la pregunta que Wonder hace antes de una acción importante. Si algo aquí contradice a `00-spec-general.md`, `01-spec-construccion.md` o `02-spec-vistas-maquetas.md`, mandan esos. Todo es simulación; la voz y el passkey son reales.

> **1 nov (R2):** la cápsula antes aprobaba un pago; ahora aprueba un pedido: el total y la dirección de entrega (`03-revision-31-oct.md` §10). La persona lee «ciento veinte mil pesos, entrega en Tienda Doña Marta».

## Decisiones pendientes

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F7-D1 | Qué autentica qué | La voz confirma la **intención** (cuánto cuesta el pedido y a dónde se entrega); el passkey prueba la **identidad** (quién aprueba). Son cosas distintas y la cápsula lo dice (nota del spec de vistas). | la vista 5 |
| F7-D2 | Cómo se compara la voz con la pantalla | La transcripción (Voice Transcribe) se normaliza y se compara con el monto y el nombre del destino **leídos de los píxeles** (F4), no del DOM. El monto en palabras se convierte a número para comparar. Coincide o no coincide; si no, el botón de passkey queda desactivado. | la vista 5 |
| F7-D3 | Biblioteca de WebAuthn del lado del servidor | A elegir al implementar; debe soportar registro y aserción de passkey en `localhost` (contexto seguro). El origen y el `rp_id` salen de `UI_ORIGIN` y `WEBAUTHN_RP_ID` (F0). | la firma de la aprobación |
| F7-D4 | Si el passkey de la demo es real o simulado | Real: WebAuthn del navegador con una passkey de plataforma, registrada una vez para la demo. Las credenciales se guardan en `.secrets/webauthn/` (F0), nunca en el repositorio. | — |

## 1. Objetivo

Cuando el motor (F6) dice que la confirmación de un pedido cumple la política y necesita aprobación, mostrar una cápsula con dos recortes exactos de la pantalla —monto y dirección de entrega, sin interpretación del agente—, pedir que la persona los lea en voz alta, comprobar que lo dicho coincide con lo que se ve, y recoger un passkey. Solo con voz que coincide y passkey válido se emite la aprobación, que lleva los hashes de los recortes aprobados hacia la verificación (F8) y el recibo (F9).

Fuera de alcance de F7: capturar, segmentar o decidir si hace falta aprobación (eso es F4 y F6). F7 recibe el evento `approval.requested` con sus recortes y produce `approval.granted` o un rechazo.

## 2. Entradas y salidas

**Entradas**

- De F6: `approval.requested` con el monto, la dirección de entrega y los hashes de los recortes de monto y dirección.
- Los PNG de esos recortes, para mostrarlos.
- El micrófono del navegador (voz) y el autenticador de plataforma (passkey).

**Salidas**

- `approval.granted` con el método (`passkey`), la transcripción de la voz y si la voz coincidió, más la firma/aserción del passkey.
- O un rechazo, con el motivo (voz no coincide, o passkey cancelado), sin aprobación.
- Los hashes de los recortes aprobados, que pasan a F8 y F9 (ya venían en el evento; F7 confirma cuáles se aprobaron).

## 3. Los cuatro estados (vista 5)

Del spec de vistas:

| Estado | Qué se ve | Qué lo produce |
| --- | --- | --- |
| Esperando voz | Los recortes, la onda y «Read aloud to confirm»; el botón de passkey inactivo | Llegó `approval.requested`, no hay voz aún |
| Voz que coincide | Indicador verde; el botón de passkey se activa | La transcripción, normalizada, coincide con los píxeles (F7-D2) |
| Voz que no coincide | La diferencia en rojo; el botón sigue inactivo | La transcripción difiere del monto o del nombre del destino de los píxeles |
| Aprobado | Sello verde con la hora y el hash de la aprobación | Passkey válido tras voz que coincide |

La nota pequeña de la cápsula: «Tu voz confirma lo que quieres; tu passkey prueba que eres tú» (F7-D1).

## 4. Cómo coincide la voz

- La voz se transcribe con Voice Transcribe (español), a través de `common/meta_client.py`.
- Se normaliza: minúsculas, sin puntuación, el monto en palabras a número («ciento veinte mil» → 120000).
- Se compara el número con el monto leído de los píxeles y el nombre con el destino leído de los píxeles (F4, «Tienda Doña Marta»). Ambos deben coincidir. Los dígitos de la dirección no se dictan: los comprueban los píxeles y la política.
- El criterio exacto (tolerancia del nombre, idioma del monto) se fija en la primera prueba con voz real; el gate de hoy ya mide voz numérica en español (95 % exacto, menos de 1,5 s).

## 5. Criterios de aceptación de F7

1. Con `approval.requested`, la cápsula muestra los dos recortes reales y queda esperando voz, con el passkey inactivo.
2. Una lectura que coincide con el monto y el nombre del destino de los píxeles activa el passkey; una que no coincide lo deja inactivo y marca la diferencia en rojo (criterio del 31 de oct del spec de construcción).
3. Con voz que coincide y passkey válido, se emite `approval.granted` con la transcripción y el método.
4. Un passkey cancelado o fallido no produce aprobación.
5. La voz se compara contra los píxeles (F4), nunca contra el DOM del portal.
6. El origen y el `rp_id` de WebAuthn salen de `UI_ORIGIN` y `WEBAUTHN_RP_ID`; funciona en `localhost`.

## 6. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F7 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| Transcripción de voz | Sí: Voice Transcribe, en el gate y en la demo | Pruebas de la normalización y la comparación con transcripciones fijas (monto en palabras → número, coincide / no coincide) |
| Passkey | Real en la demo (WebAuthn del navegador) | Pruebas del flujo del servidor con una aserción de ejemplo |
| La cápsula | — | Pruebas: dado `approval.requested`, pinta los recortes y los estados correctos |

La comparación de voz contra pantalla es la lógica propia y se prueba con datos de prueba; la transcripción real es de Voice Transcribe. El resultado de la demo sale de voz y passkey reales.

## 7. Qué del código actual se conserva

| Archivo | Se conserva | Cambia | Sale |
| --- | --- | --- | --- |
| `agent/approval.py` | Las interfaces `Approver` y `WebAuthnApprover` (el contrato) | El `WebAuthnApprover` se implementa de verdad; los aprobadores de prueba (`AutoApprover`, `DenyApprover`) se mueven a `tests/` | — |

La normalización y comparación de voz es código nuevo (propuesta: `approval/voice_match.py`), con el cliente de Voice a través de `common/meta_client.py`. La cápsula es parte de la interfaz (F11), alimentada por los eventos de F7.

## Hallazgos para los specs siguientes

1. **F4.** La comparación de voz necesita el monto y el destino **leídos de los píxeles**, no del DOM. F7 depende de que F4 entregue esos dos valores con su confianza.
2. **F9.** La transcripción de la voz y el método entran en el recibo (`approval`), y los hashes de los recortes aprobados son los que F9 guarda como `approved`.
3. **F1.** El mismo passkey que respalda la política (F1) es el mecanismo de identidad aquí. Conviene un solo registro de passkey para la demo, reutilizado en el mandato y en la aprobación.

## Implementación (31 de octubre)

Con R8 (`03-revision-31-oct.md`): la aprobación es **voz que coincide con los píxeles + clic en «Approve»**. El passkey queda opcional y no se usa; la cápsula lo dice: «la voz confirma la intención (cuánto y a dónde se entrega); no prueba quién eres; un passkey lo haría y es opcional (R8)». Probado offline (`tests/test_approval_service.py`, `approval/test_voice_match.py`) con un transcriptor falso; ninguna prueba llama a la API de Meta.

**Flujo en una corrida real.**

1. El loop emite `approval.requested` (monto y dirección de entrega leídos de los píxeles, hashes de los recortes) y llama al aprobador. En `agent/run.py` el aprobador es `ServiceApprover` (`agent/approval.py`): abre la aprobación en el servicio (`POST /api/approval/open`, con las rutas de los PNG de los recortes si existen) y consulta cada 0,5 s hasta que la persona decide. Sin decisión en `--approval-timeout` (300 s por defecto) la niega con el motivo y la cierra en el servicio. Servicio caído, decisión de otra aprobación o «approve» sin voz que coincida = negada.
2. Vista 5: la persona pulsa **Record** y lee el total y el destino («ciento veinte mil pesos, entrega en Tienda Doña Marta»). El navegador graba con WebAudio y codifica **WAV PCM de 16 kHz, mono, 16 bits** en JS (Voice Transcribe solo acepta WAV); lo envía en base64 dentro de JSON a `POST /api/approval/<id>/voice`.
3. El servicio valida el WAV (mono, 16 bits, 8–48 kHz, 0,3–20 s), lo escribe en un archivo temporal que borra al terminar (el audio no se guarda), llama a `MetaClient.transcribe` y compara la transcripción con `approval/voice_match.py` contra el monto y el destino **del evento** (píxeles, nunca el DOM). Devuelve la transcripción, si coincide, el monto oído y si se oyó el nombre.
4. La vista muestra los estados: esperando voz, grabando, transcribiendo, **coincide** (verde, se activa «Approve»), **no coincide** (rojo, con la diferencia: «Amount heard COP 150,000 · screen COP 120,000» o que no se oyó el nombre del destino; se puede grabar otra vez) y **aprobado** (sello con la hora). «Deny» siempre está disponible mientras la aprobación esté abierta.
5. `POST /api/approval/<id>/decision` registra la decisión; el servicio rechaza «approve» sin una voz que coincida (409), no solo el botón. El loop emite `approval.granted` con `method: "voice"`, la transcripción real y `voice_match`.

**Recortes en la cápsula.** `agent/run.py` envuelve el canal de píxeles (`CropFiles`) y guarda cada recorte en la carpeta de la corrida con su sha256 en el nombre; el aprobador manda las rutas cuyo hash es el del evento, así la vista 5 muestra exactamente los píxeles aprobados. Si faltan, la vista muestra el texto leído y el hash, como antes.

**Seguridad del servicio.** Los endpoints nuevos son solo loopback, con `Host` local y mismo origen (el middleware de F11), escrituras en JSON con límite de tamaño leído del cuerpo (64 KB; 1,5 MB para la voz) y nunca reciben rutas de archivo para el audio. Solo el loop (sin `Origin`) abre una aprobación: ninguna página puede fabricar una. Máximo 5 transcripciones por aprobación (cada una gasta créditos de la API).

**Elegir el aprobador.** `python -m agent.run ... --approve-in interface|console`. Sin la opción: la interfaz si el servicio del interceptor responde en `/health`, la consola si no (`ConsoleApprover`, sin voz).

**Ajustes a `voice_match`.** Montos escritos en cifras por el transcriptor («120.000», «120,000», «$120 000») se juntan antes de convertir; el nombre se compara palabra por palabra, sin tildes ni mayúsculas («tienda doña marta» = «Tienda Doña Marta»). Tras la revisión de código: (a) el monto es **una sola** frase numérica continua y bien formada («ciento veinte mil», «un millón doscientos mil» o cifras como «120.000»); una segunda frase separada («cinco mil, ciento quince mil») o una mal formada («veinte cien mil») no coincide, nunca se suman; (b) solo cuenta la frase antes del nombre del destino (después, si antes no se dijo ninguna) y los números de una dirección dicha se ignoran; (c) una negación o cancelación («no», «no pidas», «cancela», «mejor no», «nunca», «detente») rechaza; (d) se aceptan millones hasta 999.999.999; fuera de rango la vista lo dice («amount out of range»); (e) los nombres de consonantes («equis», «jota»…) valen por una letra, por si un nombre de destino la lleva. **La voz confirma el total y el NOMBRE del destino, no los dígitos de la dirección**: la dirección la comprueban los píxeles (F4/F5) y la política firmada (F1/F6). `ServiceApprover` además comprueba que el id del registro sea el que abrió y vuelve a calcular `voice_matches` con el evento; si algo no cuadra, niega. Abrir una aprobación exige `amount_cop` entero (422 si no). La grabación se corta a los 18 s para no pasar el límite de 20 s del servicio.

**Pendiente.** La primera prueba con micrófono y Voice Transcribe reales (fija la tolerancia del criterio, §4). En Chromium sin interfaz de este entorno `getUserMedia` no responde ni con los flags de dispositivo falso; la revisión automática de la vista 5 sustituyó el micrófono por un oscilador de WebAudio (la grabación, el WAV y el resto del flujo sí son los reales). El passkey (F7-D3, F7-D4) sigue fuera por R8. El recibo (`build_receipt` en `agent/loop.py`) aún escribe `method: "passkey"` y una transcripción fija; lo cambia F9.
