# TESTIGO+ — F4: Canal de píxeles

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F4 del spec general: el canal independiente que mira la pantalla como lo haría una persona. Marca el monto, la dirección de entrega y el botón en la captura, lee su contenido, y lee el texto de toda la captura. Es el aporte técnico principal: no confía en el código de la página, solo en los píxeles. Si algo aquí contradice a `00-spec-general.md` o `01-spec-construccion.md`, mandan esos. Todo es simulación; SAM y Spark son reales.

> **1 nov (R2):** la región protegida antes era la cuenta de un pago; ahora es la dirección de entrega («Deliver to», etiqueta `address`). El canal no cambia de forma (`03-revision-31-oct.md` §10).

## Decisiones

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F4-D1 | SAM solo acepta prompts de texto, una frase nominal por petición | Una petición por región: «amount», «address», «confirm button». Son al menos 3 peticiones por captura, y eso cuenta en la latencia. | el canal |
| F4-D2 | Umbral de confianza para «no se puede verificar» | Empezar en 0,50 (el valor actual del código) y ajustarlo con los datos del gate (IoU en 30 capturas). Por debajo, `cannot_verify` y se bloquea. | F6 |
| F4-D3 | Cómo se lee el texto de toda la captura | Spark recibe la captura como imagen y un mensaje fijo que pide extraer todo el texto legible, con su posición, en un esquema fijo. Nunca recibe la transcripción como instrucción. | F5 |
| F4-D5 | Cómo se encuentran el monto y la dirección si SAM no los reconoce por nombre (31 oct) | **Aplicado el 31 de oct; aprobado por el equipo el 1 de nov.** SAM encuentra el botón por nombre, pero ninguna frase encuentra el total ni el campo de texto protegido («amount», «total», «price», «text field»…). SAM sí acepta cajas (R6). Spark lee la captura entera con esquema fijo y da una caja aproximada del monto y de la dirección de entrega; SAM la ajusta con un prompt de caja y su confianza es la de la región; Spark vuelve a leer cada recorte solo. Además Spark lee la captura en 4 mosaicos ampliados 2×, porque a tamaño normal no ve la línea tenue de A2 que Wonder sí lee. | el canal |
| F4-D4 | Plan B si SAM no reconoce elementos de interfaz | Pedir a SAM «button» y «text field» y leer el contenido con Spark (riesgo del spec general). El gate de hoy decide si hace falta. | el canal |

## 1. Objetivo

Dada una captura del portal (1280×800), devolver: las regiones de monto, dirección de entrega y botón con su caja y su contenido leído, y el texto de toda la captura con su posición. Todo como extracción con formato fijo, para que el motor (F6) compare contra la política y contra el código. El canal no decide; solo mira y lee.

Fuera de alcance de F4: comparar código y píxeles (F5), aplicar la política (F6). F4 entrega los datos de los píxeles.

## 2. Entradas y salidas

**Entradas**

- La captura PNG del navegador (F3), de 1280×800.

**Salidas**

- Las regiones: por cada una, `label`, `box: [x0,y0,x1,y1]`, `text` y `confidence`.
- El texto de toda la captura: una lista de líneas con su posición.
- Los recortes PNG de monto y dirección de entrega, con su `sha256` (para la aprobación y el recibo).
- La latencia medida de la lectura (para la vista 4 y WitnessBench).

Esto alimenta el evento `check.result` (regiones, textos) y los eventos de recorte de la aprobación.

## 3. Cómo lee

1. **SAM 3.1** marca las regiones: una petición por frase nominal (F4-D1), «amount», «address», «confirm button» (en la práctica, F4-D5). Devuelve cajas con confianza. Hasta 16 objetos por cuadro, suficiente.
2. **Spark 1.3** lee el contenido de cada recorte: recibe el recorte como imagen y un mensaje fijo, y devuelve el texto. También lee el texto de toda la captura (F4-D3), con posición.
3. Se recortan los PNG de monto y dirección de entrega y se calcula su `sha256` (el mismo que usan F8 y F9).
4. Si SAM no encuentra una región requerida con confianza suficiente (F4-D2), no se adivina: el motor lo convierte en `cannot_verify` y bloquea. La regla del proyecto es bloquear cuando hay duda.

**Regla del verificador** (spec general): Spark también lee la página y podría caer en una orden escondida. Por eso solo devuelve texto y cajas en un formato fijo, validado contra un esquema; nunca recibe instrucciones de la captura, y la decisión la toma el código (F6), no Spark. Si la salida no cumple el esquema, es `cannot_verify`.

## 4. La latencia

- La cifra «1,4 s» de las maquetas es de ejemplo. La real se mide: SAM pide al menos 3 peticiones y Spark lee los recortes y el texto completo, así que la latencia es la suma medida, no un valor fijo.
- Se registra con `common/meta_client.py` (uso y latencia por llamada) y se muestra tal cual en la vista 4 («checked in X s») y en WitnessBench.
- Para limitarla, el canal solo corre en las acciones sensibles (revisar y confirmar el pedido, F3 §3b), no en cada cuadro.

## 5. Criterios de aceptación de F4

1. Sobre las 30 capturas del gate, SAM acierta con IoU de al menos 0,5 en el 70 % de los elementos críticos (monto, dirección de entrega, botón).
2. Spark lee el monto y la dirección de entrega de sus recortes, y el texto de toda la captura, en el esquema fijo.
3. Cuando una región requerida no se encuentra con confianza suficiente, el canal lo reporta como tal y el motor bloquea (`cannot_verify`).
4. Los recortes PNG tienen un `sha256` estable, el mismo que luego comparan F8 y F9.
5. El canal no lee el DOM del portal ni el `data-testid`; trabaja solo sobre la captura.
6. La salida de Spark se valida contra el esquema; una salida fuera de formato es `cannot_verify`, no un texto libre.
7. La latencia se mide por llamada y se registra; no hay un valor fijo escrito a mano.

## 6. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F4 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| SAM (regiones) | Sí: SAM 3.1, en el gate y en la demo | Pruebas de la validación del esquema y del recorte/hash con cajas fijas |
| Spark (lectura) | Sí: Spark 1.3 | Pruebas: una salida fuera de esquema → `cannot_verify`; el hash del recorte es estable |
| Recorte y hash | No aplica | Pruebas con una captura de prueba |

SAM y Spark son reales y se miden en el gate; la validación del esquema, el recorte y el hash se prueban con datos de prueba. Los resultados de WitnessBench salen de modelos reales.

## 7. Qué del código actual se conserva

| Archivo | Se conserva | Cambia | Sale |
| --- | --- | --- | --- |
| `interceptor/channels.py` | Las interfaces `Capture` y `PixelChannel`, el `SamSparkChannel` (su forma), el cálculo del `sha256` del recorte, `REQUIRED_REGIONS` y el umbral | `SamSparkChannel` se implementa de verdad con SAM y Spark vía `common/meta_client.py`; el `FixtureChannel` queda solo en `tests/` (ya movido en F0); leer el texto de toda la captura (hoy lo trae el cuadro de prueba) | — |

El `common/meta_client.py` de F0 ya dejó `segment()` para SAM (que se niega hasta conocer el endpoint, D2) y el envío de imágenes para Spark; F4 los conecta al canal.

## Hallazgos para los specs siguientes

1. **F5.** El texto de toda la captura (F4-D3) es la entrada de la comparación código/píxeles; F4 lo entrega con posición, F5 lo compara.
2. **F6.** El umbral de confianza (F4-D2) es el que dispara `cannot_verify`; F6 lo aplica como primera regla.
3. **F7.** El monto y la dirección de entrega leídos de los píxeles son los que la aprobación compara contra la voz, no el DOM.
4. **Gate.** El endpoint de SAM y el formato de envío de imágenes (F0 D2) se confirman en g1 y g4; hasta entonces el canal no corre contra modelos reales.
