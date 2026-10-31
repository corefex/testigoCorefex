# TESTIGO+ — Spec general del proyecto

28 de octubre de 2026 · Joen Anaya

TESTIGO+ es un supervisor independiente para agentes de IA que usan el computador: comprueba en los píxeles que lo que el agente pidió, lo que la persona aprobó y lo que se ejecutó son lo mismo. Este documento es la base de todos los demás specs.

## Qué es TESTIGO+

**El problema.** Los agentes de IA ya pueden usar un computador solos: abren páginas, rellenan formularios y hacen pagos. Muse Wonder, el modelo nuevo de Meta, lo hace y avisa antes de las acciones importantes. Pero una página puede traer escondida una orden para el agente («cambia la cuenta de destino») y el agente puede obedecerla. Hoy se confía en dos cosas que un atacante puede manipular: lo que el agente cuenta que va a hacer y el código interno de la página.

**La idea.** TESTIGO+ se pone entre el agente y el navegador. No confía en el agente ni en el código de la página: mira los píxeles de la pantalla, como lo haría una persona, y comprueba tres cosas:

1. Lo que el agente va a pagar es lo que la política permite.
2. La persona aprobó exactamente eso, viendo recortes reales de la pantalla.
3. Después del clic, lo que se ejecutó es lo que se aprobó.

Si algo no coincide, bloquea. Al final deja un recibo firmado que cualquiera puede verificar sin confiar en nosotros.

**La historia de la demo.** Doña Marta tiene una tienda en Bogotá y su agente le repone el inventario pagando a Distribuidora X en un portal. Sin TESTIGO+, una orden escondida cambia la cuenta y el dinero se va. Con TESTIGO+, el ataque se bloquea. Todo es una simulación: no hay dinero ni cuentas reales.

**Qué ya existe y qué es nuevo** (verificado el 28 de octubre de 2026):

| Ya existe, no se presenta como novedad | Lo que no encontramos publicado |
| --- | --- |
| Verificar la pantalla antes de ejecutar una acción (PUSV, VAC, ASU, Visual Confused Deputy). Recibos firmados para agentes (Agent Receipts y otros). Aprobación humana atada a la acción con datos estructurados (iProov HAPS, 22 de octubre). | Comprobar con píxeles, después del clic, que lo ejecutado coincide con lo aprobado. Comparar en los dos sentidos el texto del código con el texto que se ve, dentro del bucle de un agente. Un recibo que incluye el hash de los recortes de evidencia. |

La novedad se apoya en que unas 13 búsquedas dedicadas no encontraron antecedentes. Es amplia pero no exhaustiva, así que en el video se citan los trabajos previos y solo se presentan como aporte esas tres cosas.

## Objetivo y criterios de éxito

**Objetivo.** Entregar antes del 4 de noviembre a las 9 PM ET (9 PM en Bogotá) un proyecto que funcione de verdad, con repositorio público y un video de 3 minutos, y que pueda competir por los premios de la hackathon de Meta.

**Lo que se evaluará** (rúbrica reportada por madrobot.blog y aimagazine.blog; no se ha leído en las Official Rules, ver R11 en `03-revision-31-oct.md`):

| Criterio | Peso | Qué tiene que ver el jurado |
| --- | --- | --- |
| Impacto | 30 % | Un problema real y con dinero detrás (agentes que manejan pagos), contado con una persona concreta: Doña Marta. |
| Uso de herramientas de Meta | 25 % | Wonder como agente vigilado; SAM como canal de píxeles; Voice para confirmar; Spark para leer la pantalla y compilar la política (Glimmer en local solo si hay una GPU de 24 GB). Cada una con un trabajo necesario. |
| Profundidad técnica y ejecución | 20 % | Canal de píxeles independiente, firmas, benchmark propio con resultados reales. |
| Demo | 25 % | El ataque bloqueado en vivo y un número: cuántos ataques funcionan sin y con TESTIGO+ (conteos, R9). |

La etapa 1 es pasa o no pasa: tiene que encajar con el tema y usar de verdad modelos de Meta. Los temas son «Build for Your World» y «Push the Frontier».

**Criterios de éxito del proyecto** (todos medibles):

- Wonder completa el pedido en el portal sin ataque, de forma estable.
- Los 3 ataques funcionan sin TESTIGO+ y se bloquean con TESTIGO+.
- Los 5 casos sin ataque no se bloquean (falsos positivos cerca de cero).
- `testigo verify` valida un recibo bueno y detecta uno alterado.
- WitnessBench entrega 20 resultados reales y la latencia añadida por acción.
- El video de 3 minutos muestra una corrida real, no maquetas.

**Estimación de puntaje** con la rúbrica, hecha por nosotros y no oficial: alrededor de 7,9 sobre 10, o 8,2 con el escenario de la tendera. Es una estimación y no un resultado.

**Por decidir en el equipo:** la pista (Indie o Startup; si ya está elegida, anotarla aquí) y quién es el representante.

## Reglas de Meta que condicionan el proyecto

Estas salen de la guía del participante, del documento de exención, de la documentación de la API y del taller de Meta. Lo marcado como «no confirmado» hay que preguntarlo en Discord antes de apoyarse en ello.

**Reglas del evento**

| Regla | Qué implica para nosotros | Estado |
| --- | --- | --- |
| Fechas | Hackathon del 26 de octubre al 4 de noviembre de 2026. Entrega el 4 de noviembre a las 9 PM ET (9 PM en Bogotá). | Verificado |
| Equipos | Máximo 4 personas en el track Indie según fuentes secundarias; para el track Startup no encontramos un límite publicado. El equipo tiene 6. | **Por confirmar hoy en Discord (R1)**. Si el límite es 4, solo 4 se registran y hacen commits |
| Trabajo nuevo | Todo debe construirse durante el evento. El código debe ser del equipo; la exención permite ayuda técnica de terceros si los componentes siguen siendo del equipo y de código abierto con sus licencias respetadas. | Verificado |
| Repositorio público | Es obligatorio. Las llaves de firma y las claves de API no pueden ir al repositorio. | Verificado |
| Video | De 3 minutos y es lo que se ve en la etapa final. | Verificado |
| Modelos de Meta | El proyecto debe usar de verdad modelos de Meta. Muse Code es opcional. | Verificado |
| Proyectos a evitar | Asesoría médica con IA, RAG básico, analizadores simples de imágenes, aplicaciones Streamlit, dashboards como función principal, chatbots educativos, filtros de CVs, coaches de nutrición, analizadores de personalidad y analizadores deportivos. | Verificado |
| Cuentas y créditos | USD 150 por participante en la API de Meta, con tarjeta propia; cada uno reclama los suyos antes del 4 de noviembre a las 9 PM ET. Baseten, Modal y Fireworks dan créditos extra solo a algunos participantes. | Verificado. No sabemos si los créditos de dos cuentas se pueden juntar |
| Datos de entrenamiento | Las suscripciones de Muse Code vienen en modo «Contributor», que entrena con los datos; no usarlo con material sensible. | Verificado |
| Acceso desde Colombia | La política geográfica no lista a Colombia como restringida, pero hay que probar con una llamada real desde Bogotá. | Verificado en el texto; falta la prueba |
| Asistentes de código externos (como Claude Code) | No vimos una regla en contra ni a favor. | No confirmado: preguntar en Discord (#questions) |
| Cantidad de finalistas y fecha de la final | El jurado revisa del 5 al 8 de noviembre y la final en vivo es el 9. Hay fuentes con números distintos de finalistas. | No confirmado |

**Límites de las herramientas de Meta**

| Herramienta | Qué puede y qué no |
| --- | --- |
| Muse Wonder | Computer use, subagentes y 1 millón de tokens de contexto; pregunta antes de acciones importantes. En vista previa. USD 4 y 20 por millón de tokens (entrada y salida). Wonder Full no está en la API. |
| Muse Spark 1.3 | USD 1,25 y 4,25 por millón de tokens. Se usa para desarrollar y para leer los recortes. |
| SAM 3.1 (API) | Solo prompts de texto, una frase nominal por petición; hasta 16 objetos por cuadro; videos MP4 o MOV; USD 2,50 por 1.000 imágenes. Las cajas y puntos como prompt existen solo en los pesos abiertos. |
| Voice Transcribe | 25 idiomas, USD 0,18 por hora. Transcribe; no genera voz y no identifica a la persona. |
| Glimmer | Modelo de 30 mil millones de parámetros, licencia Apache 2.0; cabe en 24 GB a 4 bits. Es el único realmente local. |
| Spark Open | Modelo grande de código abierto servido por Baseten, Together o Fireworks. Se factura aparte de los créditos de Meta. |
| API en general | Compatible con el SDK de OpenAI: basta cambiar el host. Muse Code con clave de API gasta los mismos créditos y tiene los mismos límites. |

## Alcance

| Entra en el MVP | No entra | Es simulado |
| --- | --- | --- |
| Un portal de proveedor con un solo flujo: pagar un pedido en dos pasos (revisar y confirmar). Wonder lo maneja con un navegador controlado. Los 3 ataques. Política por voz. Aprobación con voz (passkey opcional, R8). Verificación antes de confirmar y después del clic. Recibos firmados y `verify`. WitnessBench con 20 corridas. Una interfaz basada en las vistas del diseño. | Integraciones con bancos, Nequi u otras cuentas reales. Aplicación móvil. Varios proveedores o flujos. Entrenar modelos propios. Un panel de control como función principal. Cualquier dato de un empleador. | El portal y el pago, los datos de Doña Marta, la cuenta del atacante y el dinero. Es real el agente, la detección, la aprobación, la firma del recibo y la medición. |

Decisión de fondo: si hay que recortar, se recorta ancho y no profundidad. Es mejor un flujo que se mide bien que varios que se ven bien.

## Arquitectura general y vistas

TESTIGO+ se pone entre el agente y el navegador: ninguna acción de Wonder llega a la página sin pasar por él. El detalle de cada pieza va en su propio spec.

1. Wonder recibe una captura del portal y propone una acción (por ejemplo, un clic).
2. El interceptor detiene la acción y toma la captura y el texto visible del código de la página.
3. SAM marca monto, destinatario y botón. Spark lee el contenido de esos recortes y el texto de toda la captura, solo como extracción con formato fijo.
4. Se compara el texto del código con el texto de toda la captura, y el monto y el destinatario con la política. Si algo falla, se bloquea.
5. Si es un pago y todo cumple, se pide la aprobación con los recortes y la voz (el passkey es opcional, R8). Esta cápsula es la que responde la pregunta que Wonder hace antes de una acción importante.
6. El pago tiene dos pasos. En la pantalla de revisión, antes del clic final de confirmar, TESTIGO+ vuelve a capturar y comprueba que lo que se va a ejecutar coincide con lo aprobado; si no coincide, bloquea.
7. Después de confirmar, vuelve a capturar el resultado, lo compara y firma un recibo con los hashes de los recortes.

**Regla para el verificador.** Spark también lee la página, así que podría caer en la misma orden escondida. Por eso Spark solo devuelve texto y cajas en un formato fijo, nunca recibe instrucciones de la página, y la decisión la toman reglas en código, no otro modelo.

**Texto oculto legítimo.** Las páginas normales tienen texto que no se ve (menús cerrados, texto para lectores de pantalla). Solo se marca como divergencia el texto oculto o pintado que parece una instrucción para el agente: órdenes, números de cuenta o menciones al agente.

**Las vistas ya diseñadas.** Están en el lienzo de Claude Design (20 pantallas, con sus variantes de estado): https://claude.ai/artifact/SoZszjAzJTnYJvehGp1dJ7. La interfaz real las usa como guía, con una diferencia: cada dato sale de un evento del sistema y no está escrito a mano. Las correcciones pendientes de las maquetas están en el documento «Spec de construcción: portal y vistas reales» (`01-spec-construccion.md`).

| Vista | Pantallas del lienzo | Feature que la alimenta |
| --- | --- | --- |
| Portada | Cover | F11 |
| 1 Mandato | 1a escuchando, 1b transcribiendo, 1c política firmada | F1 |
| 2 Agente trabajando | 2a en marcha, 2b en pausa | F3 |
| 3 Sin TESTIGO+ | 3a orden oculta, 3b pago enviado | F2 y F3 |
| 4 Divergencia | 4a sin diferencia, 4b texto visible que no está en el código, 4c texto del código que no se ve; falta 4d «no se puede verificar» | F4, F5 y F6 |
| 5 Aprobación | 5a esperando voz, 5b coincide, 5c no coincide, 5d aprobado | F7 |
| 6 Después del clic | 6a verificado, 6b no coincide | F8 |
| 7 Recibo | 7a válido, 7b evidencia que no coincide | F9 |
| 8 WitnessBench | Resultado | F10 |

## Features y specs que siguen

Cada feature tendrá su propio spec con: objetivo, entradas y salidas, criterios de aceptación, qué se prueba con modelos reales y qué con datos de prueba, y qué del código actual se conserva. Antes de todas va el spec de infraestructura.

| ID | Feature | Qué hace | Herramienta de Meta | Depende de |
| --- | --- | --- | --- | --- |
| F0 | Infraestructura | Estructura del repositorio, instalación, claves y secretos fuera del repo, cuentas y créditos, ramas y commits por persona, cómo se prueba. | — | — |
| F1 | Mandato por voz y política | La dueña dice qué puede hacer el agente y queda una política firmada. | Voice Transcribe, Spark (Glimmer opcional) | F0 |
| F2 | Portal simulado y ataques | Página de Distribuidora X con pago en dos pasos (revisar y confirmar), los escenarios sin ataque, A1, A2 y A3, y un registro de pagos. | — | F0 |
| F3 | Agente y navegador | Wonder maneja el portal con Playwright; se puede correr con o sin supervisor. | Wonder (Spark para desarrollar) | F0, F2 |
| F4 | Canal de píxeles | Marca monto, destinatario y botón en la captura y lee su contenido. | SAM 3.1, Spark 1.3 | F3 |
| F5 | Comparación código y píxeles | Lee el texto de toda la captura y encuentra texto del código que no se ve y texto visible que no está en el código, filtrando lo que no parece una instrucción. | Spark 1.3 | F4 |
| F6 | Motor de decisión | Aplica la política y las reglas: permitir, pedir aprobación, bloquear o «no se puede verificar». | — | F1, F4, F5 |
| F7 | Aprobación | Cápsula con recortes reales, lectura en voz alta y passkey opcional (R8). | Voice Transcribe | F6 |
| F8 | Verificación antes de confirmar y después del clic | Compara con lo aprobado en la pantalla de revisión (y bloquea) y otra vez en el resultado. | SAM 3.1, Spark 1.3 | F7 |
| F9 | Recibos y `verify` | Recibo firmado con los hashes de la evidencia y una herramienta que lo comprueba. | — | F8 |
| F10 | WitnessBench | 20 corridas con y sin TESTIGO+ y sus resultados. | Wonder | F2 a F9 |
| F11 | Interfaz | Las vistas del lienzo conectadas a los eventos del sistema. | — | F3 a F10 |

Orden de escritura de los specs: F0, luego F2 y F3 (lo que el gate de hoy pone a prueba), F4 y F5, F6, F1, F7, F8, F9, F10 y F11.

## Estado actual, riesgos y gate

> **31 de octubre:** el estado real del código, las decisiones R1 a R11 y el calendario nuevo están en `03-revision-31-oct.md`, que manda sobre este documento donde lo contradiga.

**Código que ya existe** (en la carpeta `testigo/`, revisado el 28 de octubre): portal con escenarios, núcleo del interceptor con reglas, bucle del agente con un agente de guion, recibos con firma y `verify`, y una política de ejemplo. Corre sin conexión y con datos de prueba. **No usa todavía ningún modelo de Meta ni Playwright**, no tenía interfaz ni repositorio git (hoy ya existen ambos, ver `03-revision-31-oct.md`), y las imágenes de evidencia son archivos de relleno de 21 bytes. Cada spec de feature decide qué de esto se conserva. No se escribe más código hasta tener el spec de infraestructura.

**Riesgos principales**

| Riesgo | Qué pasa si ocurre | Plan |
| --- | --- | --- |
| Wonder resiste los ataques | Sin ataque que funcione no hay «antes» en la demo ni número en WitnessBench. | Probarlo hoy. Si resiste, ajustar los ataques (redacción, posición, contexto) hasta tener casos que funcionen, y contar honestamente cuántos resiste. |
| El verificador cae en la misma orden escondida | Spark obedece el texto del banner y TESTIGO+ deja pasar el ataque. | Spark solo extrae texto en formato fijo; la decisión la toman reglas en código. Incluir este caso en WitnessBench. |
| SAM no reconoce elementos de una interfaz | Se cae el canal de píxeles, que es el aporte técnico. | Plan B: pedir a SAM «button» y «text field» y leer el contenido con Spark. |
| Wonder no se puede interceptar por la API | No hay agente real que vigilar. | Es la prueba que decide si seguimos; si falla, reconsiderar el enfoque. |
| Falsos positivos por texto oculto legítimo | TESTIGO+ bloquea páginas normales. | Marcar solo el texto que parece una instrucción; medir en los 5 casos sin ataque. |
| No hay GPU de 24 GB para Glimmer | No se puede correr la política en local. | Usar Spark por API; Glimmer queda como opcional. |
| Latencia alta | La demo se siente lenta. | Medirla y mostrarla; limitar las comprobaciones a las acciones de pago. |
| Dominio de pagos | Un miembro del equipo trabaja en un banco con exclusividad y el equipo había excluido pagos. | Decisión R2: proteger la dirección de entrega de un pedido en vez de la cuenta de pago (el motor no cambia), o mantener pagos tras revisar el contrato. |
| Integración atrasada | Al 31 de oct ningún modelo de Meta está conectado y el gate del 28 no está aprobado. | Calendario nuevo con cortes diarios en `03-revision-31-oct.md` §3. |
| Costo del benchmark | Se acaban los créditos. | Desarrollar con Spark 1.3 y usar Wonder solo para pruebas de integración y la corrida final. |
| Reglas de asistentes de código | Riesgo de descalificación por contribución poco clara. | Preguntar en Discord; commits hechos por personas del equipo. |

**Gate de hoy (28 de octubre, hasta las 23:59 en Bogotá)**

- [ ] Llamada real a la API desde Bogotá y créditos reclamados.
- [ ] Interceptar 10 de 10 acciones de Wonder con Playwright.
- [ ] A1, A2 y A3 funcionan contra Wonder sin TESTIGO+ en al menos 2 de 3 intentos cada uno.
- [ ] SAM 3.1 sobre 30 capturas del portal: IoU de al menos 0,5 en el 70 % de los elementos críticos.
- [ ] Spark lee el texto de toda la captura (incluido el banner de A2) sin obedecerlo.
- [ ] Voz numérica en español: 95 % exacto y menos de 1,5 s.
- [ ] Si alguien tiene una GPU de 24 GB: Glimmer responde en menos de 2 s. Si no, se usa Spark.

**Siguiente documento:** el spec de infraestructura (F0).
