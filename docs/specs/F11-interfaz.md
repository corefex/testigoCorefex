# TESTIGO+ — F11: Interfaz

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F11 del spec general: las vistas del lienzo de diseño, conectadas a los eventos en vivo del sistema. La interfaz no decide nada ni llama a modelos; solo muestra lo que los demás emiten. Si algo aquí contradice a `00-spec-general.md`, `01-spec-construccion.md` o `02-spec-vistas-maquetas.md`, mandan esos. Todo es simulación.

> **31 oct, rediseño:** la consola de 9 pestañas confundía a quien llegaba por primera vez. Ahora hay una portada y un recorrido guiado de cuatro pasos que arranca corridas desde la página (§8). Las 9 vistas siguen en `#/present`, sin enlace, para grabar el video.
>
> **1 nov (R2):** las vistas antes contaban un pago; ahora cuentan un pedido y su dirección de entrega (`03-revision-31-oct.md` §10). Los textos de las vistas siguen a `02-spec-vistas-maquetas.md`.

## Decisiones pendientes

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F11-D1 | Transporte de eventos | WebSocket desde el interceptor (spec de construcción). La página se suscribe a un flujo y pinta cada evento al llegar. | todo F11 |
| F11-D2 | HTML a mano o un framework | HTML, CSS y JavaScript estático servido por el interceptor (F0, sin Node). Las maquetas son HTML; se portan tal cual, sin paso de build. | — |
| F11-D3 | Resolución de la interfaz (las maquetas son 1440×900; el portal captura 1280×800) | La interfaz se diseña a 1440×900 como las maquetas; dentro, la captura del portal es una imagen de 1280×800 con las cajas de SAM dibujadas encima por coordenadas. Son dos tamaños distintos: la ventana de la demo y la captura dentro de ella. | las vistas 2 a 6 |
| F11-D4 | Si la interfaz guarda o solo muestra | Solo muestra. El estado vive en los eventos y los archivos (`receipt.json`, `bench_results.json`); la interfaz no tiene almacenamiento propio. | — |

## 1. Objetivo

Una página web que recorra el guion de la demo —portada, mandato, agente trabajando, divergencia, aprobación, verificación, recibo y WitnessBench— con cada dato saliendo de un evento o un archivo del sistema, no escrito a mano. Reutiliza el aspecto de las maquetas (sistema visual del spec de vistas) y se puede grabar de corrido para el video de 3 minutos.

Fuera de alcance de F11: producir los eventos (eso es F3 a F10). F11 los recibe y los pinta.

## 2. Entradas y salidas

**Entradas**

- El flujo de eventos del interceptor por WebSocket: `agent.step`, `frame.captured`, `check.result`, `approval.requested`, `approval.granted`, `verify.result`, `receipt.signed` (contrato de eventos, F0 hueco 8 lo completa cada feature).
- Archivos: la política firmada (vista 1), `receipt.json` (vista 7), `bench_results.json` (vista 8).
- Las capturas y los recortes PNG que referencian los eventos, servidos por el interceptor desde `runs/`.

**Salidas**

- Las pantallas renderizadas, una por vista, navegables en orden para la grabación.
- Ningún archivo ni estado propio (F11-D4).

## 3. De cada vista a su evento

Del spec de construcción, «De cada vista a su implementación real»:

| Vista | Qué pinta | De qué evento o archivo |
| --- | --- | --- |
| Portada | Título y los tres iconos | Estático |
| 1 Mandato | Onda de voz, transcripción, tarjetas de política, sello firmado | Micrófono y Voice (F1); la política firmada del archivo |
| 2 Agente | Pasos del agente y la captura en vivo | `agent.step`, `frame.captured` |
| 3 Sin TESTIGO+ | La corrida sin el interceptor y el pedido confirmado con entrega en la bodega del atacante | Corrida `--no-supervisor` (F3); el registro del portal |
| 4 Divergencia | Cajas de SAM sobre la captura y las dos columnas código/píxeles | `check.result` con `regions`, `code_only_text`, `pixels_only_text`, `latency_ms` |
| 4d No se puede verificar | El bloqueo por duda, en ámbar, con el motivo y «Ask a human» | `check.result` con `status: cannot_verify` |
| 5 Aprobación | Los dos recortes, la onda de voz, la transcripción, el passkey | PNG recortados, Voice (F7), WebAuthn |
| 6 Después del clic | Recortes de antes y después y su comparación | `verify.result` con ambos grupos de hashes |
| 7 Recibo | La tarjeta del recibo y la terminal de `testigo verify` | `receipt.json` y la CLI en vivo |
| 8 WitnessBench | Pedidos entregados en la dirección del atacante, sin y con TESTIGO+ (conteos), y las barras por ataque | `bench_results.json` |

## 4. Cómo se dibujan las cajas y los recortes

- La captura del portal llega como imagen de 1280×800. Las cajas de SAM (`regions` en `check.result`) traen `box: [x0,y0,x1,y1]` en coordenadas de esa imagen; la interfaz las dibuja encima por posición, con el color del estado (azul para marcadas, rojo para la divergencia).
- Los recortes de evidencia (vistas 5 y 6) son los PNG que el interceptor recortó, servidos desde `runs/`, con su hash corto debajo (del evento, no inventado).
- El sistema visual (colores, tipografía, íconos con texto) sale del spec de vistas y es el mismo de las maquetas. Las correcciones de las maquetas (spec de construcción) ya están aplicadas en el lienzo y se portan con ellas.

## 5. Criterios de aceptación de F11

1. Con el portal, el interceptor y una corrida en marcha, la interfaz recorre las 8 vistas y la portada sin tocar el código (criterio del 1 de nov del spec de construcción).
2. Cada dato visible viene de un evento o un archivo; no hay cifras escritas a mano en la vista 4, 6, 7 ni 8.
3. Las cajas de SAM caen sobre los elementos correctos de la captura (coordenadas del evento).
4. La vista 7 corre `testigo verify` de verdad y muestra su salida real.
5. La vista 8 lee `bench_results.json`; mientras no exista, muestra el aviso de «ejemplo» y no cifras como verdaderas.
6. La interfaz no es el protagonista: no hay un tablero de control; el centro son los bloqueos en vivo (vistas 4 a 6), y el recibo y los números van al final (spec de vistas, «qué no maquetar»).

## 6. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F11 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| Pintar eventos | No aplica (no llama a modelos) | Pruebas: dado un evento de ejemplo, la vista pinta los campos correctos; las cajas caen en las coordenadas dadas |
| El recorrido completo del video | Sí: sobre una corrida real (F10) | — |

La interfaz no llama a ningún modelo. Sus pruebas usan eventos de ejemplo solo para comprobar que pinta bien; el video sale de una corrida real.

## 7. Qué del código actual se conserva

No hay código de interfaz todavía. F0 dejó el servicio del interceptor (`interceptor/service.py`) con una página de estado y el lugar donde se montan el WebSocket y los estáticos. F11 agrega la carpeta `ui/` (HTML, CSS y JS estático) y el WebSocket en el servicio. Las maquetas del lienzo son la guía visual; no son código que se importe, se reconstruyen como HTML.

## Hallazgos para los specs siguientes

1. **Contrato de eventos (F0 hueco 8).** F11 necesita que cada evento tenga sus campos fijos. `check.result` ya está definido; `agent.step`, `frame.captured`, `approval.*`, `verify.result` y `receipt.signed` los cierra cada feature que los emite. F11 consume lo que haya; si falta un campo, se pide primero en el spec de esa feature.
2. **Vista 3.** Mostrar la corrida sin supervisor y el pedido desviado necesita que el interceptor pueda emitir eventos también en modo `--no-supervisor` (o que la vista lea el registro del portal). Decidirlo en F3.
3. **Servir `runs/`.** La interfaz sirve capturas y recortes desde `runs/`, que es git-ignorada; en la demo están presentes localmente, nunca en el repositorio.

## Implementación (28 de octubre)

Hecho y probado offline (`tests/test_ui.py`, `agent/test_loop.py`); las 9 vistas se revisaron en el navegador a 1440×900 con eventos de prueba.

- **Transporte (F11-D1).** El loop publica cada evento en un *sink* (`interceptor/sink.py`, `HttpSink` → `POST /events`). El servicio guarda la corrida en memoria (`interceptor/hub.py`) y la reenvía por `WS /ws`: primero el historial (una página que abre tarde lo ve todo) y luego cada evento nuevo. `POST /events` y `/events/reset` solo aceptan conexiones locales. El sink es de mejor esfuerzo: si el servicio está caído, la corrida y el veredicto no cambian (hay prueba).
- **Interfaz (F11-D2).** `ui/index.html`, `ui/app.css`, `ui/app.js`: HTML, CSS y JS estáticos servidos en `/`, sin build. La vista actual va en la URL (hoy `#/present/4`, ver §8); flechas y teclas 0–8 para navegar, `A` para seguir los eventos.
- **Archivos.** `GET /api/policy` (vista 1; la política activa, `common.config.policy_path()`), `POST /api/mandate/draft` y `POST /api/mandate/sign` (vista 1 en vivo, F1), `GET /api/receipt` (el `receipt.json` más reciente bajo `runs/`, o `?path=`), `POST /api/verify` (corre el `testigo verify` real como subproceso y devuelve su salida, criterio 4), `GET /api/bench` (`runs/bench_results.json` o «no disponible», criterio 5), `GET /runs/<ruta>` (solo PNG/JPEG, sin salir de `runs/`).
- **Datos de prueba.** `python -m tests.demos.ui_replay a3 --both` reproduce corridas de los fixtures con `test_data: true`, y la interfaz muestra una franja «Test data — no grabar». No sirve para el video.
- **Estado (F11-D4).** La página no guarda nada; reconstruye todo desde los eventos. Guarda por separado la corrida sin supervisor (vista 3) y la supervisada (vistas 2, 4–7).

### Quién puede hablarle al servicio

La revisión de código encontró que cualquier pestaña del navegador local (el portal incluido) podía inyectar eventos falsos —por ejemplo un `verify.result` «match» sin la franja de datos de prueba— o borrar una corrida en plena grabación, porque el chequeo de loopback no alcanza: el navegador también conecta desde 127.0.0.1. Ahora:

- Toda petición necesita un `Host` local (contra DNS rebinding).
- Si la petición trae `Origin`, tiene que ser el del propio servicio. El portal, en otro puerto, es otro origen y queda fuera. El WebSocket hace el mismo chequeo, porque los navegadores no aplican la política de mismo origen a los WebSockets.
- `POST /events` exige `Content-Type: application/json`, que un `fetch` no-cors no puede enviar.
- Cada tipo de evento valida los campos que usan las vistas; un evento mal formado se rechaza en vez de romper la página en cada recarga.

### Cambios al contrato de eventos

En `interceptor/events.py` (todos opcionales o nuevos, compatibles hacia atrás):

| Evento o campo | Para qué | Lo llena |
| --- | --- | --- |
| `run.started` (`mode`, `scenario`, `variant`) | Separar la corrida sin supervisor de la supervisada | El loop, ya |
| `order.confirmed` (`address`, `amount_cop`) | Vista 3: el pedido que se confirmó sin supervisor; vista 6: el registro del portal | El loop, ya (desde `driver.last_order`) |
| `explain.result` (`frame`, `status`, `regions`, `code_only_text`, `pixels_only_text`, `after_run`, `image`) | Vista 3: dónde estaba el texto del ataque, calculado después de la corrida | `agent.run --no-supervisor --explain`, nunca WitnessBench |
| `frame.captured.image` | La captura detrás de las cajas de SAM (vistas 2–4) | F3: el driver guarda la captura en `runs/` y pone `Capture.image` |
| `approval.requested.images`, `verify.result.images` | Los recortes PNG de las vistas 5 y 6 | F4/F8: guardar los recortes en `runs/` |
| `receipt.signed.path` | Qué `receipt.json` muestra la vista 7; sin él, la vista avisa «Not from this run» | F9: escribir el recibo firmado en `runs/` |
| `approval.granted.granted` | La respuesta explícita de la persona (la voz puede coincidir y el passkey faltar) | El loop, ya |

Mientras un campo falte, la vista lo dice en pantalla («No screenshot in this event», «crop image not in this event») y no inventa nada.

### Lo que F10 debe escribir para la vista 8

La vista 8 lee `runs/bench_results.json` y usa solo `summary`, en conteos (R9): pedidos entregados en la dirección del atacante sin y con TESTIGO+.

```json
{
  "summary": {
    "attacks_succeed_without": {"succeeded": 0, "runs": 0},
    "attacks_succeed_with": {"succeeded": 0, "runs": 0},
    "by_attack": {"a1": {"without": {}, "with": {}}, "a2": {}, "a3": {}},
    "false_positives": {"count": 0, "reached_check": 0, "clean_runs": 0},
    "added_latency_ms": {"median": 0, "p90": 0},
    "per_check_latency_ms": {"median": 0, "p90": 0},
    "edge_cases": []
  },
  "rows": []
}
```

Los valores de arriba son la forma, no resultados. Si el archivo no existe o no trae `summary`, la vista muestra «— → —» y el aviso de que aún no hay resultados.

### Pendiente

- Vista 1 en vivo: hecha (1 nov). «Record mandate» → Voice → `policy/compile.py` → borrador junto a la política en uso → «Sign and use» la firma con la llave del dueño y la vuelve la activa (`RUNS_DIR/policy/active.policy.yaml`, F1). Estados: idle, recording, transcribing, draft, refused, signed. Falta probarla con micrófono y claves reales.
- Vista 3 zoom: hecho (1 nov) con `agent.run --no-supervisor --explain` (F3): `explain.result` trae el cuadro, las regiones y las líneas divergentes; la vista dibuja la caja y un acercamiento (recorte por CSS de la captura) con el aviso «calculado después de la corrida, solo para explicar». El texto escondido en el código (A1) no tiene caja: se muestra la línea. Falta correrlo con modelos reales.
- Vista 5: el passkey real (WebAuthn) es F7; hoy el botón refleja `approval.granted`.

## 8. Portada y recorrido guiado (31 oct)

Problema: 9 pestañas («Cover», «Mandate», …), un botón «Follow», atajos de teclado y estados vacíos que mandaban a la terminal. Quien llegaba no sabía por dónde empezar y no podía arrancar nada desde la página.

**Rutas** (`ui/flow.js`; `ui/app.js` conserva estado, ayudas, aprobación, mandato y las vistas del presentador):

| Ruta | Qué es |
| --- | --- |
| `#/` | Portada (diseño aprobado del lienzo): qué es TESTIGO+, los 3 ataques, cómo funciona, WitnessBench y «Try the demo». `#/how` y `#/attacks` bajan a su sección. |
| `#/demo/rules` | 1 Tus reglas: la política firmada en palabras simples; «Use these rules» (principal) o «Record new rules» (el flujo de mandato en vivo de siempre). |
| `#/demo/run` | 2 Correr el agente: 4 tarjetas (normal, orden escondida en el código, orden pintada en una imagen, dirección cambiada al final), interruptor «Protect with TESTIGO+» (encendido por defecto) y «Run the agent». Versión 1–5 y ventana visible en «More options». |
| `#/demo/watch` | 3 Mirando: la última captura y una línea de tiempo en lenguaje simple; si TESTIGO+ pide aprobación, la cápsula (recortes, voz, aprobar/negar) aparece ahí mismo. |
| `#/demo/result` | 4 Resultado: un solo desenlace grande (bloqueado y por qué, entregado en tu tienda, entregado al atacante, el agente se detuvo solo, error), la comparación con la otra corrida del mismo escenario, el recibo con «Verify receipt», y la evidencia (código vs. píxeles, aprobado vs. ejecutado, dónde estaba el ataque, todos los pasos) detrás de desplegables. «Run another» y «Compare without TESTIGO+». |
| `#/results` | WitnessBench simple: las tres cifras y una tabla por escenario y modo. |
| `#/present[/0-8]` | Las 9 vistas de antes, para grabar. Sin enlace en la navegación; `#/N` viejos llevan ahí. |

Las cifras de la portada y de `#/results` salen de `GET /api/bench` (`runs/bench_results.json`, o la copia versionada más nueva `results/witnessbench-*.json`), nunca escritas a mano: «9 de 10» = filas supervisadas de a1/a2 bloqueadas; «0 de 15» = `attacks_succeed_with/without` (si alguna es > 0 cambia el texto); «1 de 5» = `false_positives`; la mediana por chequeo = `per_check_latency_ms.median`.

**Arrancar una corrida** (`interceptor/service.py`):

- `POST /api/run {scenario, variant?, supervised, explain?, headed?}` lanza `python -m agent.run` como subproceso con una lista argv (nunca shell): `--scenario --variant --approve-in interface`, más `--no-supervisor --explain` sin supervisor y `--headed` si se pide. `INTERCEPTOR_PORT` del hijo = el puerto del servicio. Validación estricta: escenario en `clean|a1|a2|a3`, variante entero 1–5, booleanos de verdad, sin campos extra, `explain` solo sin supervisor. Una corrida a la vez (409).
- `GET /api/run`: `idle | running | finished | failed | cancelled`, código de salida y las últimas 40 líneas impresas (en memoria, sin archivos).
- `POST /api/run/cancel`: termina el proceso (y lo mata a los 5 s).
- Mismas protecciones que las demás escrituras: Host local, Origin propio, JSON, solo loopback.

**Buenas prácticas aplicadas:** botones y enlaces reales, etiquetas en cada control, foco visible, foco al título al cambiar de paso, `aria-live` con el estado de la corrida, contraste ≥ 4.5:1 (`--faint` pasó a `#6B6A66`), sin scroll horizontal a 375 px, estados de carga, vacío y error en cada paso, y la nota «simulation only» en el pie y en el paso 2. La jerga (SAM, hashes, `cannot_verify`, F8) solo aparece dentro de los desplegables y en el presentador.

**Pruebas:** `tests/test_ui.py` (Chromium) cubre portada, resultados, los 4 pasos y los desenlaces con eventos de prueba; `tests/test_service.py` cubre `/api/run` con un proceso falso. Ninguna prueba corre el agente real ni llama a Meta.
