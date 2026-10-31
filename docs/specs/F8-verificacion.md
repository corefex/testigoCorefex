# TESTIGO+ — F8: Verificación antes de confirmar y después del clic

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F8 del spec general: después de aprobar, en la pantalla de revisión y otra vez en el resultado, TESTIGO+ vuelve a capturar y comprueba que lo que se va a ejecutar, y lo que se ejecutó, coinciden con lo aprobado. Es la comprobación con píxeles después del clic, uno de los tres aportes propios. Si algo aquí contradice a `00-spec-general.md` o `01-spec-construccion.md`, mandan esos. Todo es simulación; la comparación es real.

> **1 nov (R2):** antes se comparaba la cuenta de un pago; ahora se compara la dirección de entrega del pedido (`crop_address`, `03-revision-31-oct.md` §10).

## Decisiones pendientes

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F8-D1 | Dónde se compara | Dos momentos: en la pantalla de revisión, antes del clic de confirmar (y ahí **bloquea** si no coincide); y en el resultado, después de confirmar (y ahí **marca** el recibo). | F2 y F9 |
| F8-D2 | Qué guarda `executed` si se bloqueó en la revisión y nunca se confirmó (hueco 2 y 10 de F0) | Nada: el recibo es `blocked` con `blocked_at: review`, sin `executed` (F9-D4). Solo hay `executed` si se llegó a confirmar. | F9, vistas 6 y 7 |
| F8-D3 | Qué se compara exactamente | Los hashes (o los valores leídos) de los recortes de monto y dirección de entrega (F4), aprobados contra los de la nueva captura. Mismo recorte, mismo hash si no cambió. | F4 |
| F8-D4 | Qué muestran las vistas 6 y 7 si el bloqueo fue en la revisión (contradicción del hueco 10 de F0) | La vista 6 muestra el sello «Blocked at review» con los recortes de la revisión que no coinciden; el pedido no se confirma, así que no hay un «ejecutado» real. La vista 6b «Executed … Flagged for review» corresponde al caso en que, sin supervisor o por configuración, el pedido sí se confirmó y se marca después. | F11 |

## 1. Objetivo

Cerrar el lazo que abre la aprobación: lo que la persona aprobó en recortes (F7) tiene que ser lo que de verdad va a pasar. F8 recaptura en dos momentos —la pantalla de revisión y el resultado—, recompara los recortes contra los aprobados, bloquea antes de confirmar si no coinciden, y marca el recibo si la diferencia aparece en el resultado. Emite `verify.result` con ambos grupos de hashes.

Fuera de alcance de F8: capturar y leer (F4), decidir antes del clic (F6), firmar (F9). F8 compara lo aprobado con lo que sigue.

## 2. Entradas y salidas

**Entradas**

- De F7: los hashes de los recortes aprobados (monto y dirección de entrega).
- De F4, sobre la nueva captura (revisión y resultado): los recortes y sus hashes.

**Salidas**

- `verify.result` con `approved` y `executed` (los dos grupos de hashes) y el estado: `match` o `mismatch`.
- Si es `mismatch` en la revisión: bloquea antes de confirmar.
- Si es `mismatch` en el resultado: el recibo queda `confirmed` pero marcado; si el flujo se detuvo en la revisión, el recibo es `blocked` con `blocked_at: review` (F8-D2).

## 3. Los dos momentos

1. **En la pantalla de revisión, antes de confirmar.** TESTIGO+ recaptura, F4 relee monto y dirección de entrega, y F8 compara sus hashes con los aprobados. Si no coinciden, estado `mismatch` y se bloquea: el clic de confirmar no procede. Es donde se atrapa un cambio hecho después de aprobar y antes de confirmar.
2. **En el resultado, después de confirmar.** Si el pedido se confirmó, F8 recaptura el resultado y vuelve a comparar. Si no coincide, el recibo queda marcado («Flagged for review», vista 6b). Es la última red: si algo cambió entre la revisión y la ejecución, queda registrado.

En ambos, comparar es por hash (F8-D3): el mismo recorte da el mismo hash; una dirección distinta (por ejemplo, Bodega Norte · Carrera 80 # 7-15 en vez de la tienda) da un hash distinto, y eso es el `mismatch`.

## 4. Estados (vista 6)

| Estado | Qué se ve | Qué lo produce |
| --- | --- | --- |
| Verificado | Sello verde «VERIFIED», los recortes coinciden | `verify.result` con `match` |
| No coincide (bloqueado en revisión) | Sello «Blocked at review», el recorte que difiere en rojo; el pedido no se confirmó | `mismatch` en la revisión (F8-D4) |
| No coincide (marcado en resultado) | Sello rojo «MISMATCH», «Flagged for review»; el pedido se confirmó y quedó marcado | `mismatch` en el resultado |

## 5. Criterios de aceptación de F8

1. Si en la pantalla de revisión la dirección de entrega difiere de la aprobada, F8 bloquea antes de confirmar (criterio del 31 de oct del spec de construcción).
2. Si todo coincide en la revisión, el flujo pasa a confirmar.
3. Si se confirmó y el resultado difiere de lo aprobado, el recibo queda marcado.
4. La comparación es por hash de recortes (F4), no por el DOM.
5. Un flujo bloqueado en la revisión produce un recibo `blocked` con `blocked_at: review`, sin `executed` (F8-D2).
6. `verify.result` lleva ambos grupos de hashes, para la vista 6 y el recibo.

## 6. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F8 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| Comparar hashes | No aplica (es código) | Pruebas: aprobado vs revisión coincide/no; `match` y `mismatch`; el recibo marcado |
| Recapturar y releer | Sí: F4 con SAM y Spark sobre la nueva captura | — |
| De punta a punta | Sí, en la demo | — |

La comparación es determinista y se prueba con hashes fijos; recapturar y releer usa modelos reales. El resultado de la demo sale de capturas reales.

## 7. Qué del código actual se conserva

| Archivo | Se conserva | Cambia | Sale |
| --- | --- | --- | --- |
| `interceptor/engine.py` | El método `verify` (compara aprobados vs ejecutados por hash) y su prueba | Dos momentos (revisión y resultado) en vez de uno; bloquear en la revisión; el estado `blocked_at` | — |
| `interceptor/events.py` | El constructor de `verify.result` | Reflejar el momento (revisión o resultado) | — |

El `verify` actual ya compara los dos grupos de hashes y detecta el `mismatch`; F8 lo coloca en los dos momentos del pedido en dos pasos (F2) y conecta el resultado al recibo (F9).

## Hallazgos para los specs siguientes

1. **F2.** F8 depende de que el portal tenga pedido en dos pasos y la pantalla de revisión (F2); ahí es donde recaptura antes de confirmar.
2. **F9.** El estado (`confirmed` o `blocked`), el `blocked_at` y los dos grupos de hashes son justo lo que el recibo guarda (F9-D4).
3. **F11.** Las vistas 6 y 7 necesitan distinguir «bloqueado en revisión» de «marcado en resultado» (F8-D4); hay que resolver el hueco 10 de F0 en el contrato antes de pintarlas.
