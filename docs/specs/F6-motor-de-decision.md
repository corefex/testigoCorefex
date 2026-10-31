# TESTIGO+ — F6: Motor de decisión

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F6 del spec general: aplica la política y las reglas, y decide permitir, pedir aprobación, bloquear o «no se puede verificar». Es el núcleo que convierte lo que ven los píxeles en una decisión, tomada por reglas en código y no por un modelo. Si algo aquí contradice a `00-spec-general.md` o `01-spec-construccion.md`, mandan esos. Todo es simulación; la decisión es real.

> **1 nov (R2):** la regla 3 antes ataba un pago a una cuenta; ahora ata el pedido a la dirección de entrega (`address_allowed`, `03-revision-31-oct.md` §10). Las reglas no cambian de forma.

## Decisiones pendientes

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F6-D1 | Orden de las reglas | Como el código actual y el spec de construcción: 1) no se puede verificar, 2) divergencia, 3) política, 4) necesita aprobación. La primera que aplica decide. `cannot_verify` va primero a propósito: una comparación que no se puede leer no es un aprobado. | el motor |
| F6-D2 | La regla 3 mira solo el nombre del destino (hueco 1 de F0) | Exigir que coincidan nombre **y** dirección leídos de los píxeles contra `deliver_only` (F1-D2), con `address_allowed`: el nombre permitido y exactamente el conjunto de direcciones permitido. | — |
| F6-D3 | De dónde salen la dirección y el monto para la regla 3 | De los píxeles (F4), nunca del DOM. Un valor escondido o cambiado no entra a la decisión. | F4 |
| F6-D4 | Campos extra en `check.result` que agregó el código (`reason`, `confidence`), no en el contrato del spec | Dejarlos, pero declararlos en el contrato de eventos primero (F0 hueco 8). `reason` ayuda a la vista 4d; `confidence` a la 4. | F11 |

## 1. Objetivo

Dada una acción propuesta y lo que ve el canal de píxeles (F4) y la comparación código/píxeles (F5), decidir una de cuatro cosas y emitir el evento que lo dice: permitir (acción que no confirma el pedido y cumple), pedir aprobación (confirmación de pedido que cumple), bloquear (divergencia o política incumplida), o no se puede verificar (no se lee con confianza). Todo con reglas en código; ningún modelo decide.

Fuera de alcance de F6: leer la pantalla (F4), comparar textos (F5), verificar después del clic (F8). F6 aplica las reglas.

## 2. Entradas y salidas

**Entradas**

- La acción propuesta por el agente (su tipo: confirmar el pedido u otra; F3 §3b).
- De F4: las regiones con su contenido y confianza, y el monto y la dirección de entrega leídos de los píxeles.
- De F5: las dos listas de divergencia filtradas.
- La política firmada (F1).

**Salidas**

- Un `check.result` con el estado: `ok`, `divergence`, `policy_violation` o `cannot_verify`, más las regiones, las listas y la latencia.
- Si el estado es `ok` y la acción confirma el pedido, además un `approval.requested` con los recortes hacia F7.

## 3. Las cinco reglas

Del spec de construcción, en orden (la primera que aplica decide):

1. **No se puede verificar.** Si SAM no encuentra monto, dirección de entrega o botón con confianza suficiente (F4-D2), estado `cannot_verify` y se bloquea. Va primero: no se puede comparar lo que no se lee.
2. **Divergencia.** Si F5 devuelve texto del código no dibujado, o texto dibujado ausente del código (ya filtrado a lo que parece una instrucción), estado `divergence` y se bloquea.
3. **Política.** Si la dirección o el monto leídos de los píxeles no cumplen la política —otra dirección (nombre o dirección, F6-D2), o más de `max_per_order_cop`—, estado `policy_violation` y se bloquea. La regla 3a bloquea cualquier dirección en pantalla que la política no permita, aunque no esté en la caja de «Deliver to».
4. **Necesita aprobación.** Si todo cumple y la acción confirma el pedido, estado `ok` y se pide aprobación (F7), con los recortes.
5. **Después del clic** (la hace F8, no F6): en la pantalla de revisión y en el resultado, si los recortes no coinciden con los aprobados, `mismatch` y el recibo queda marcado.

La regla 5 es de F8; F6 cubre 1 a 4 antes del clic. Las dos juntas son las cinco reglas del spec.

## 4. Por qué el código decide, no un modelo

Spark lee la pantalla y podría caer en una orden escondida (riesgo del spec general). Por eso el motor no le pregunta a ningún modelo qué hacer: toma las extracciones de formato fijo de F4 y F5 y aplica condiciones en código. Un fallo de un modelo (sin respuesta, baja confianza, salida fuera de esquema) no se traduce en «permitir»: se vuelve `cannot_verify`, porque la regla del proyecto es bloquear cuando hay duda.

## 5. Criterios de aceptación de F6

1. Con una captura cuyo monto, dirección de entrega o botón no se leen con confianza, el estado es `cannot_verify` y bloquea.
2. Con una divergencia filtrada no vacía (en cualquier sentido), el estado es `divergence` y bloquea.
3. Con un destino (nombre o dirección) fuera de `deliver_only`, o un monto sobre `max_per_order_cop`, el estado es `policy_violation` y bloquea.
4. Con todo en regla y una confirmación de pedido, el estado es `ok` y se emite `approval.requested`.
5. La dirección y el monto de la regla 3 salen de los píxeles, no del DOM.
6. Un fallo de modelo en F4/F5 llega al motor como baja confianza o fuera de esquema y produce `cannot_verify`, nunca `ok`.
7. En los 5 `clean`, el motor no bloquea (falsos positivos cerca de cero).
8. El orden de las reglas se respeta: `cannot_verify` antes que `divergence`.

## 6. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F6 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| Las reglas | No aplica (es código, no un modelo) | Pruebas con regiones y listas fijas: cada regla dispara su estado; el orden se respeta; `clean` no bloquea |
| De punta a punta | Sí, en la demo: F4 y F5 con modelos reales alimentan el motor | — |

El motor se prueba con entradas fijas, porque es la pieza donde la lógica debe ser determinista. De punta a punta corre sobre lo que leyeron SAM y Spark de verdad.

## 7. Qué del código actual se conserva

| Archivo | Se conserva | Cambia | Sale |
| --- | --- | --- | --- |
| `interceptor/engine.py` | Las cinco reglas en orden, el objeto `Decision`, el uso de las interfaces, las pruebas de reglas | La regla 3 exige nombre y dirección (F6-D2); la divergencia usa el filtro de F5; la latencia viene medida de F4 (hoy es 1400 ms fijo) | — |
| `interceptor/events.py` | Los constructores de eventos | Declarar `reason` y `confidence` en el contrato (F6-D4) | — |

El núcleo del motor ya existe y funciona con datos de prueba; F6 lo conecta a los píxeles reales (F4), al filtro (F5) y a la política con dirección atada (F1), y deja la verificación post-clic a F8.

## Hallazgos para los specs siguientes

1. **F8.** La regla 5 (después del clic) la implementa F8, reusando el `verify` que ya existe en el motor. F6 y F8 comparten el objeto `Decision` y los eventos.
2. **F11.** Los campos `reason` y `confidence` (F6-D4) alimentan las vistas 4 y 4d; hay que declararlos en el contrato de eventos antes de que F11 los pinte.
3. **F1.** Exigir nombre y dirección (F6-D2) depende de que la política los ate (F1-D2); las dos features cierran juntas el hueco 1 de F0.
