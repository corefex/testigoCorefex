# TESTIGO+ — F5: Comparación código y píxeles

28 de octubre de 2026 · Borrador para aprobación

Concreta la fila F5 del spec general: lee el texto de toda la captura y encuentra texto del código que no se ve y texto visible que no está en el código, filtrando lo que no parece una instrucción para el agente. Es la mitad de detección del canal independiente. Si algo aquí contradice a `00-spec-general.md` o `01-spec-construccion.md`, mandan esos. Todo es simulación; la lectura es de Spark, la comparación es código.

> **1 nov (R2):** las señales del filtro antes buscaban datos de un pago; ahora buscan direcciones y verbos de entrega (`03-revision-31-oct.md` §10).

## Decisiones pendientes

| ID | Tema | Propuesta de este spec | Bloquea |
| --- | --- | --- | --- |
| F5-D1 | Qué cuenta como «parece una instrucción» (hueco 6 de F0) | Una lista de señales, en inglés y español: una orden dirigida a un agente o asistente, una dirección (el patrón `ADDRESS_RE`), o una mención al agente junto a un verbo de entrega o confirmación. El texto oculto normal (menús cerrados, etiquetas para lectores de pantalla, texto de promoción) no dispara. | la detección |
| F5-D2 | Cómo se emparejan las dos listas de texto | Normalizar (minúsculas, espacios colapsados) y comparar como conjuntos de líneas. El texto que está en un canal y no en el otro es la diferencia; sobre esa diferencia se aplica el filtro F5-D1. | la detección |
| F5-D3 | De dónde sale el «texto del código» | Del texto que la página expone (DOM y árbol de accesibilidad), que incluye lo que no se dibuja. Lo entrega F3 junto con la captura. | F3 |
| F5-D4 | Límite conocido del filtro | Una orden redactada sin ninguna de las señales de F5-D1 no se marcaría. Se asume y se mide: WitnessBench incluye un caso así para contar cuánto se escapa. | F10 |

## 1. Objetivo

Dadas dos listas de texto —lo que el código de la página expone y lo que se ve en los píxeles (F4)—, encontrar las diferencias en los dos sentidos: texto que está en el código pero no se dibuja, y texto que se ve pero no está en el código. De esas diferencias, quedarse solo con lo que parece una instrucción para el agente, y entregarlo al motor (F6), que decide si bloquea. El texto oculto legítimo de una página normal no debe marcarse.

Fuera de alcance de F5: leer la pantalla (F4), decidir (F6). F5 compara y filtra.

## 2. Entradas y salidas

**Entradas**

- El texto de toda la captura, con posición (F4).
- El texto que el código de la página expone (F3, F5-D3).

**Salidas**

- `code_only_text`: líneas presentes en el código, no dibujadas, que pasan el filtro.
- `pixels_only_text`: líneas visibles, ausentes del código, que pasan el filtro.
- Ambas van al evento `check.result`.

## 3. Cómo compara y filtra

1. **Normalizar** las dos listas: minúsculas, espacios colapsados, bordes recortados.
2. **Diferencia en los dos sentidos** (F5-D2): lo que está en el código y no en los píxeles; lo que está en los píxeles y no en el código.
3. **Filtrar** cada diferencia con las señales de F5-D1: se queda la línea que parece una instrucción para el agente; se descarta el texto oculto normal.
4. Entregar las dos listas filtradas. Si alguna no está vacía, el motor (F6) lo trata como divergencia y bloquea.

**Por qué el filtro.** Las páginas normales tienen texto que no se ve: menús cerrados, texto para lectores de pantalla. Si se marcara cualquier diferencia, TESTIGO+ bloquearía páginas normales (falsos positivos). El filtro deja pasar ese texto y solo levanta la mano ante lo que se dirige al agente. Su límite (F5-D4) es conocido y se mide.

**Regla del verificador.** El texto lo leyó Spark en formato fijo (F4); F5 no vuelve a pedirle nada a un modelo, solo compara en código. Así la decisión no depende de otro modelo que pudiera obedecer la página.

## 4. Las señales del filtro (F5-D1)

Una línea de la diferencia se marca si, en inglés o español, contiene al menos una de:

- una orden dirigida a un «agent», «assistant», «AI» o «agente», «asistente» (un imperativo dirigido al agente);
- una dirección: el patrón de dirección (`calle|carrera|avenida|diagonal|transversal` + número `#` número `-` número, con las abreviaturas `Cl`, `Cra`, `Kr`, `Av`, `Dg`, `Tv`, `No.`, `N°`);
- una mención al agente junto a un verbo de entrega o confirmación («deliver», «ship», «send», «entrega», «envía», «confirm», «confirma»).

La lista exacta de patrones se fija y se amplía con los casos de WitnessBench. El texto de promoción, los menús y las etiquetas de accesibilidad no encajan en ninguna señal y no se marcan.

## 5. Criterios de aceptación de F5

1. Cuando el código tiene una instrucción no dibujada, aparece en `code_only_text`; cuando los píxeles tienen una instrucción ausente del código, aparece en `pixels_only_text`.
2. En los 5 casos `clean` —que llevan texto oculto legítimo (F2)—, ambas listas quedan vacías: no se marca el texto normal.
3. El emparejamiento ignora diferencias de mayúsculas y espacios.
4. F5 no llama a ningún modelo: compara en código el texto que F4 ya leyó.
5. El caso del límite (F5-D4) está documentado y hay una corrida en WitnessBench que lo mide.

## 6. Qué se prueba con modelos reales y qué con datos de prueba

| Pieza de F5 | Con modelos reales | Con datos de prueba |
| --- | --- | --- |
| Comparar y filtrar | No aplica (es código, no un modelo) | Pruebas: diferencias en los dos sentidos; los `clean` con texto oculto legítimo no se marcan; el filtro deja pasar promoción y accesibilidad |
| Con el texto real de Spark | Sí, de punta a punta en la demo (F4 lee, F5 compara) | — |

F5 en sí no llama a modelos; se prueba con listas de texto fijas, incluidas las de los `clean` legítimos. De punta a punta corre sobre lo que Spark leyó de verdad.

## 7. Qué del código actual se conserva

| Archivo | Se conserva | Cambia | Sale |
| --- | --- | --- | --- |
| `interceptor/engine.py` | La función de divergencia (`_divergence`) que compara las dos listas y saca las dos diferencias | Agregar el filtro «parece una instrucción» (F5-D1); hoy marca cualquier diferencia | — |

Hoy el motor bloquea ante cualquier diferencia de texto. F5 agrega el filtro para no marcar el texto oculto legítimo; el resto de la comparación ya existe y se conserva.

## Hallazgos para los specs siguientes

1. **F2.** Los `clean` con texto oculto legítimo (F2-D4) son la prueba del filtro; las dos features se verifican juntas.
2. **F6.** La divergencia es la regla 2 del motor; F6 la coloca después de `cannot_verify` y antes de la política.
3. **F10.** El caso del límite del filtro (F5-D4) entra como una corrida de WitnessBench, para contar honestamente cuánto se escapa.
