# Decisiones no cubiertas por la guía

Formato: fecha · decisión · alternativa · razón.

## Etapa 1 (17/11/2026)

### D1 · `DB_PORT` y `DB_PASSWORD` como variables opcionales
- **Decisión:** se agregan a `config.py` además de las de la sección 10. Si `DB_PASSWORD` está vacía, el backend entra a PostgreSQL con identidad gestionada (token de Entra ID, con SSL obligatorio). Si tiene valor, usa usuario y contraseña. Eso solo pasa en local y en el CI.
- **Alternativa:** usar solo identidad gestionada.
- **Razón:** el PostgreSQL de `docker-compose` y el del CI no tienen Entra ID. En Azure no se define `DB_PASSWORD`, así que no hay contraseñas en la nube.

### D2 · Proveedor falso o de Azure según la variable
- **Decisión:** si `KEYVAULT_URL` está vacía se usa `ProveedorClavesFalso`; si `AZURE_OPENAI_ENDPOINT` está vacía, `ProveedorLLMFalso`. No hay una variable extra del tipo `USAR_FALSOS`.
- **Alternativa:** una bandera explícita.
- **Razón:** es lo más simple. En Azure esas variables siempre existen y en local nunca.

### D3 · Las versiones de Azure de los proveedores ya están escritas, pero no se probaron
- **Decisión:** `ProveedorClavesAzure` (`KeyClient.get_key` y la lista de versiones habilitadas) y `ProveedorLLMAzure` (`AsyncAzureOpenAI` con `get_bearer_token_provider`) existen desde la etapa 1. No hay pruebas contra Azure.
- **Razón:** son pocas líneas y fijan la interfaz. Hay que probarlas cuando Fabricio tenga los recursos creados (etapas 2 y 3).
- **Nota:** el Key Vault necesita los permisos `get` y `list` sobre la clave. `list` sirve para saber qué `kid` siguen habilitados (sección 6.3). La guía solo menciona `get`.

### D4 · Uso de `cryptography` y `anyio` sin declararlas
- **Decisión:** el proveedor falso usa `cryptography` (para generar la clave RSA local) y el de Azure usa `anyio` (para llamar al SDK síncrono de Key Vault sin bloquear). Ninguna está en la sección 2, pero ya se instalan como dependencias de `azure-keyvault-keys` / `azure-identity` y de `fastapi`.
- **Alternativa:** declararlas en `pyproject.toml`.
- **Razón:** la guía pide no agregar dependencias sin preguntar. **Pendiente de confirmar con el equipo:** conviene declararlas, porque depender de librerías transitivas es frágil.

### D5 · Entrega de eventos "al menos una vez"
- **Decisión:** `procesar_pendientes` corre al arrancar, cada 60 s y (desde la etapa 3) después de publicar. Cada entrega va en su propia transacción, con `SELECT … FOR UPDATE SKIP LOCKED` para que dos réplicas no procesen el mismo evento a la vez.
- **Alternativa:** procesar solo al arrancar.
- **Razón:** si un manejador falla (por ejemplo, Blob no responde), no hace falta esperar a un reinicio. Por eso los manejadores de Recepción y Revisión tienen que ser idempotentes.

### D6 · Archivos extra en `shared/`
- **Decisión:** se agregan `shared/limites.py` (slowapi y el límite de 2 MB) y `shared/logs.py` (filtro que reemplaza cualquier UUID de los logs por su hash, incluso en las rutas del access log).
- **Razón:** son infraestructura común que la sección 9 pide y que no encaja en los otros archivos de `shared/`.

### D7 · `FORWARDED_ALLOW_IPS="*"` en el Dockerfile
- **Decisión:** se define junto con `--proxy-headers`.
- **Razón:** sin esto, uvicorn ignora `X-Forwarded-For` del ingress de Container Apps, y el límite por IP vería siempre la IP del proxy. El contenedor solo recibe tráfico a través del ingress. **Confirmar con Fabricio.**

### D8 · `pip-audit --strict` falla con cualquier vulnerabilidad
- **Alternativa:** fallar solo con las críticas (sección 9).
- **Razón:** `pip-audit` no informa la severidad. Fallar con cualquiera es más estricto y más simple. Si algún hallazgo bloquea sin razón, se ignora con `--ignore-vuln <ID>` y se anota aquí.

### D9 · En Azure, la extensión `vector` debe estar en la lista permitida
- **Decisión:** la migración `0001` corre `CREATE EXTENSION IF NOT EXISTS vector`.
- **Nota para el despliegue:** en Azure Database for PostgreSQL hay que agregar `VECTOR` al parámetro `azure.extensions` antes de correr `alembic upgrade head`.

## Hallazgos sobre el modelo `MobileNet_Urticaria.tflite` (17/11/2026)

Lo revisé con LiteRT (`ai-edge-litert`). Afecta al manifiesto de la sección 4 y a los datos pendientes de la sección 13. **Para Diego:**

1. **El archivo está dañado:** el bias de la capa `expanded_conv_13_depthwise_bn` tiene 955 de 960 valores en `NaN`.
   - Con XNNPACK (el delegado por defecto en Android), la salida es siempre `[NaN, NaN]`.
   - Sin XNNPACK, la salida es siempre `[0.4996, 0.5004]` para cualquier imagen.
   - El modelo no se puede usar así. Lo más probable es que algo falló en el entrenamiento (BatchNorm) o en la conversión. Hay que volver a exportarlo y verificarlo con imágenes reales antes de publicarlo.
2. **Arquitectura:** por dentro es **MobileNetV3Large**, no MobileNetV4 como dice el documento «Arquitectura CNN».
3. **Entrada:** `float32 [1, 224, 224, 3]`. El modelo ya incluye una capa `Rescaling` al inicio, así que es probable que espere píxeles en `[0, 255]` sin normalizar. Hay que confirmarlo para `entrada.normalizacion`.
4. **Salida:** `float32 [1, 2]` con softmax, o sea **2 clases**, no 3. Lo más probable es que «indeterminado» salga del `umbral_confianza` y no del modelo. Hay que confirmar el orden de las dos clases y el umbral, y ajustar el enum `Clase` y `clases` del manifiesto (sección 13).

## Etapas 2 a 4 (18/11/2026)

### D10 · Cuestionario v1 y validación de las respuestas
- **Decisión:** `preguntas.json` es el v1 de `wawa-qhali-cuestionario.md` (8 preguntas de riesgo y 6 normales). Ese documento manda sobre la guía donde se contradicen. Los valores son estrictos: un `si_no` solo acepta `true` o `false`, no `"true"`, `"si"` ni `1`.
- **No se exige que lleguen todas las preguntas normales.** Con un «sí» de riesgo, el cuestionario se detiene y la app llama a Orientación con severidad `alta` y solo las preguntas de riesgo respondidas hasta ese punto. Si se exigieran todas, esa llamada respondería 422.
- **Alternativa:** exigir todas las normales cuando la severidad no es `alta`. **Para confirmar con el equipo de la app.**

### D11 · Puerto de autorización en `shared/puertos.py`
- **Decisión:** Recepción necesita saber si hay una autorización vigente, pero no puede importar Autorización (sección 3). Por eso `shared` define la interfaz `PuertoAutorizacion`, Autorización la implementa y `main.py` las conecta. `lint-imports` sigue pasando.
- **Alternativa:** un evento `AutorizacionOtorgada` y una copia de las autorizaciones dentro de Recepción.
- **Razón:** es más simple y la consulta siempre ve el dato al día. Con el evento, una donación hecha justo después de autorizar podría recibir 403.

### D12 · `ProveedorBlob`: un tercer proveedor con versión falsa
- **Decisión:** igual que con claves y LLM, hay una interfaz con dos versiones. Una es en memoria (pruebas, y local sin Azurite). La otra es Azure: identidad gestionada con SAS de delegación de usuario, o `STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true` con Azurite.
- **Razón:** el CI no levanta Azurite. El proveedor real se probó a mano contra Azurite: subir, SAS de solo lectura, descargar y borrar.
- Azurite corre con `--skipApiVersionCheck`, porque el SDK es más nuevo que la imagen de Azurite.

### D13 · IDs de los fragmentos y fuentes
- **Decisión:** el ID de cada fragmento es `<archivo>#<n>` (por ejemplo `guia-urticaria-pediatrica#3`). El LLM cita `F1`..`F5`; el backend verifica que existan y los traduce a esos IDs. Así la app puede mostrar de qué guía salió cada recomendación sin volver a llamar al backend.

### D14 · Embeddings falsos tipo "bolsa de palabras"
- **Decisión:** el `ProveedorLLMFalso` calcula embeddings con hashing de palabras, así que textos con palabras en común quedan cerca. Con esto la búsqueda del RAG funciona en local y en las pruebas.

### D15 · Fragmentos por palabras
- **Decisión:** 450 palabras (unos 600 tokens) con un solapamiento de 75 palabras (unos 100 tokens).
- **Razón:** no hay tokenizador en las dependencias. Agregar `tiktoken` requiere preguntar.

### D16 · Umbral de distancia del RAG = 0,6 (`TODO`)
- Distancia coseno máxima para usar un fragmento. Hay que calibrarla con las guías reales y el despliegue de embeddings.

### D17 · Endpoint nuevo: `POST /v1/interno/revision/usadas` ⚠️
- **Decisión:** se agregó porque la guía define `usada_en_modelo` y dice que al revocar «las ya usadas se conservan», pero ningún endpoint marca una imagen como usada. Sin él, una revocación borraría todo.
- Lo llama el servicio de reentrenamiento (`X-Api-Key`) con `{version_modelo, ids}`.
- **Es un endpoint que no estaba en el contrato: confirmar con el equipo y con quien hace el reentrenamiento.**

### D18 · Autorización
- El `X-Installation-Id` tiene que coincidir con el `installation_id` del cuerpo o de la ruta; si no, responde 403. Así una instalación no puede revocar la de otra.
- Volver a autorizar después de revocar la renueva. Revocar dos veces responde 204, pero solo publica un evento.

### D19 · Modelos
- Si la compuerta rechaza un candidato, este queda `bloqueado` y no se puede volver a intentar con la misma versión.
- La compuerta compara la sensibilidad, la lista y el orden de las clases, y `ancho`, `alto` y `canales`.
- `revertir/{version}` solo acepta la versión vigente. Vuelve a publicar la última `retirada` y deja la revertida `bloqueada`, para que revertir dos veces no rebote entre las mismas dos versiones.

### D20 · Revisión
- La etiqueta final se puede corregir (el «Deshacer» de la app web) hasta que la imagen se use en un modelo. Después responde 409.
- `eliminar` deja la fila en estado `eliminada`, borra el blob y vacía las respuestas del cuestionario. La revocación, en cambio, borra las filas no usadas.
- El login responde siempre el mismo 401 genérico. Cuando el usuario no existe, igual verifica un hash de relleno, para no revelar qué usuarios existen.

### D21 · Límite de peticiones en memoria
- slowapi guarda los contadores en la memoria de cada réplica. Con N réplicas, el límite real es N veces el configurado. Para que sea exacto haría falta Redis, que es una dependencia nueva: preguntar si importa.

### D22 · Prueba completa del pipeline con bytes sintéticos
- `tests/test_pipeline.py` recorre donación → descifrado → registro → etiqueta → reentrenamiento con un JPEG sintético. La sección 12 pide imágenes públicas, pero aquí no hay un dataset: hay que repetirla con imágenes reales para el informe.

### D23 · Paquete de donación
- También se valida `alg == "RSA-OAEP-256+A256GCM"`, y se rechazan campos extra (422).
- La app tiene que usar como AAD el `installation_id` en **minúsculas** con guiones (`str(uuid)`), igual que en la sección 6.4.

### D24 · El texto libre va al LLM, no al embedding
- Se envía delimitado con `"""…"""`, y la instrucción de sistema aclara que no son órdenes, para protegerse de inyección de instrucciones. No entra en el embedding (sección 7.2, paso 2).

## Integración con las apps (19/11/2026)

### D25 · Cuenta fija del médico ⚠️
- **Decisión:** el equipo pidió que las credenciales del médico estén escritas en el código. `revision/servicio.py` define `CUENTA_FIJA_USUARIO = "medico"` y `CUENTA_FIJA_CONTRASENA`. Al arrancar, la API crea esa cuenta, o la reactiva y le devuelve su contraseña si alguien la cambió. La web hace login normal con `/v1/auth/login` y recibe su JWT de 1 hora.
- **Rompe la sección 9** (ningún secreto en el repositorio): cualquiera con acceso al repo puede entrar como médico.
- **Alternativa recomendada después de la sustentación:** leer la contraseña de una variable de entorno que venga de Key Vault, o volver a `scripts/crear_medico.py`.

### D26 · Datos de demostración (`scripts/sembrar_demo.py`)
- Carga un fragmento `demo-no-clinica#1`, armado con los textos de `preguntas.json`, y 3 imágenes sintéticas en Revisión. Sirve para probar la app y la web sin guías reales ni servicio de reentrenamiento.
- No corre si hay Azure configurado. Exige Azurite: con el Blob en memoria las imágenes se perderían al terminar el script.

### D27 · El LLM falso responde según la severidad
- Sin una respuesta fija configurada, `ProveedorLLMFalso` devuelve textos genéricos según la severidad que lee en la instrucción de sistema, y esos textos pasan la validación de 7.4. **No es contenido clínico**; solo sirve para probar la integración en local.

### D28 · Con un signo de alarma, la app envía `clase: indeterminado` y `confianza: 0`
- Cuando hay alarma el modelo no se ejecuta, pero `ConsultaOrientacion` exige clase y confianza. El backend no las usa para decidir nada: la severidad `alta` la manda la app.

## Despliegue en Azure (19/11/2026)

### D29 · Frase fija para la recomendación de nivel `leve`
- **Decisión:** la instrucción de sistema fija la última recomendación de `leve`: «Si empeora, le cuesta respirar o se le hinchan la cara o los labios, busca atención médica.».
- **Razón:** solo decía «indica cuándo buscar atención médica». Con gpt-4o, 2 de cada 3 respuestas leves no traían ninguna frase de `acciones_por_nivel.json → leve` y la validación respondía 503 (`leve_sin_accion`). Con la frase fija salieron 6 de 6. Moderada y alta ya tenían una frase fija.

### D30 · Modelo de chat: `gpt-4o` 2024-11-20 (Standard)
- **Decisión:** el despliegue de chat se llama `gpt-4o`.
- **Razón:** `gpt-4o-mini` 2024-07-18 se retiró el 31/03/2026, y la suscripción de estudiante no tiene cuota para `gpt-4.1-mini`. `gpt-5-mini` no acepta `temperature=0`, lo que obligaría a cambiar `ProveedorLLMAzure`. Cuesta unos US$0,01 por consulta y se retira el 14/04/2027.

### D31 · Secretos: Key Vault → secretos del Container App en cada despliegue
- **Decisión:** `JWT_SECRET` e `INTERNAL_API_KEY` viven solo en Key Vault (`jwt-secret`, `internal-api-key`). El workflow `cd.yml` los lee en cada despliegue y los carga como secretos del Container App, que llegan a la API como variables de entorno (sección 9).
- **Alternativa:** referencias `keyvaultref` del Container App.
- **Razón:** la suscripción Azure for Students crea solo entornos «express», que no las admiten (`ExpressKeyVaultSecretsNotSupported`).
- **Consecuencia:** si se rota un secreto en Key Vault, se aplica en el siguiente despliegue.

### D32 · Migraciones en el CD con la identidad `id-wawa-ci`
- **Decisión:** `cd.yml` corre `alembic upgrade head` desde el runner de GitHub antes de actualizar la app (sección 10). Abre una regla de firewall temporal con la IP del runner y la borra al terminar.
- Las tablas son del rol `wawa_owner` (NOLOGIN). `id-wawa-ci` y el administrador son miembros, y su rol por defecto en la base `wawa` es `wawa_owner`. La API entra como `id-wawa`, que solo tiene SELECT/INSERT/UPDATE/DELETE, más privilegios por defecto para las tablas nuevas.
- **Razón:** si las tablas fueran de una persona, la identidad del CI no podría alterarlas.

### D33 · Regiones
- PostgreSQL está en `centralus`, porque la oferta de estudiante no lo permite en `eastus`/`eastus2`. El Container App está en `centralus`, junto a la base. OpenAI, Storage, Key Vault y ACR están en `eastus2`.

### D34 · Umbral de distancia del RAG: 0.42 (antes 0.6)
- **Decisión:** `UMBRAL_DISTANCIA = 0.42` (distancia coseno, `text-embedding-3-small`).
- **Cómo se midió (19/11/2026):** `scripts/calibrar_umbral.py`, contra los 9 fragmentos reales de las 6 guías en Azure. Usa 36 consultas realistas armadas con el mismo `texto_consulta` que usa el backend: 6 leves, 18 moderadas y 12 altas, con desencadenantes, tiempos y clases variados. Como negativos, mide 10 fragmentos señuelo de otros temas (varicela, dengue, otitis, diarrea, dermatitis atópica, quemaduras, vacunas, sueño, asma, cocina), que no se guardan en la base.
- **Resultados:**

  | Medida | mín | mediana | máx |
  | --- | --- | --- | --- |
  | Fragmento real más cercano (top-1) | 0.312 | 0.351 | 0.368 |
  | Los 5 fragmentos reales que se envían al LLM (top-5) | 0.312 | 0.360 | 0.405 |
  | Señuelos | 0.442 (asma) | 0.600 | 0.891 |

  | Umbral | Consultas con fragmentos | Fragmentos que pasan (de 5) | Señuelos que pasarían |
  | --- | --- | --- | --- |
  | 0.40 | 100 % | 4.86 | 0 % |
  | **0.42** | **100 %** | **5.00** | **0 %** |
  | 0.46 | 100 % | 5.00 | 9 % |
  | 0.60 (anterior) | 100 % | 5.00 | 50 % |

- **Razón:** 0.42 es el único valor redondo que deja pasar los 5 fragmentos reales de todas las consultas y ningún señuelo. Con 0.6 pasaba la mitad de los textos de otros temas. El señuelo más cercano es asma (0.442), porque comparte «le cuesta respirar» y «labios morados». Por eso el margen es corto (0.015 hacia cada lado) y el valor no se debe subir. Si una consulta queda sin fragmentos, la respuesta es 503 y la app usa su respaldo local, que es el lado seguro.
- **Consecuencia:** el texto que se convierte en vector sale solo de las respuestas del cuestionario (el comentario del padre no entra), así que las consultas reales caen siempre en un rango estrecho. **Hay que repetir la medición cuando cambien las guías**, por ejemplo después de la revisión de la médica: `uv run python -m scripts.calibrar_umbral`.

### D35 · Primer modelo real (de Diego): versión 1.0.0 y clases `no_compatible,compatible`

- **Fecha:** 20/11/2026.
- **Decisión:** el modelo de Diego (MobileNetV3Large entrenado en Colab con 431 fotos de entrenamiento y 49 de validación) se registra como `1.0.0` con `clases = ["no_compatible", "compatible"]`. Sus carpetas se llamaban `sana` y `urticaria`, y Keras las ordena alfabéticamente: el índice 0 es `sana` (= `no_compatible`) y el índice 1 es `urticaria` (= `compatible`). La entrada es `0_255`, porque la capa Rescaling viene dentro del modelo.
- **Alternativa:** reentrenarlo con el orden `compatible,no_compatible` del contrato anterior. Se descartó porque obliga a volver a entrenar y a pedirle el dataset a Diego, sin ninguna ganancia: la app y el backend ya leen las clases desde el contrato.
- **Razón:** la compuerta de publicación (`servicio._motivo_de_bloqueo`) bloquea un candidato si cambia el orden de las clases respecto del vigente. Por eso el servicio de reentrenamiento tiene que entrenar con el mismo orden: **variable `CLASES=no_compatible,compatible` en el repo `Reentrenamiento`** (`cd.yml` ya la lee), y las carpetas de `modelos/datos-base/` deben llamarse `compatible` y `no_compatible`, no `urticaria` y `sana`.
- **Revisión del .tflite (en Docker):** entrada `[1,224,224,3]` float32 y salida `[1,2]` con softmax. Sin NaN. Responde distinto según la imagen: piel lisa ≈ 0.85 en el índice 0, piel con ronchas sintéticas 0.89–0.98 en el índice 1. `sha256 3bc9dda2…7d70`, 13 891 260 bytes.

### D36 · La sensibilidad de un modelo se mide en el mismo test separado por paciente; se corrige la del `1.0.0`

- **Fecha:** 22/11/2026.
- **Decisión:** la sensibilidad que se registra para un modelo, y que usa la compuerta de publicación, se mide siempre en el **mismo test**: `D:\WawaQhali\datos\dataset\test`, con 282 recortes de urticaria de 19 niños y 787 de otras lesiones y piel sana de DermoPed y `normal-baby-skin`. Ningún paciente del test aparece en el entrenamiento. Se usa `herramientas/evaluar.py`, a umbral 0.5 y sin «indeterminado». El `1.0.0` estaba registrado con **0.90**, un número del reporte de Diego medido con su propia validación (sobre todo urticaria frente a piel lisa). En este test da **0.574**: el 22/11 se corrigió en `modelos.versiones` con un `UPDATE` (solo esa fila, filtrando por versión, `sha256 3bc9dda2…` y valor anterior).
- **Alternativa:** mantener el 0.90. Se descartó porque obliga a cualquier modelo nuevo a superar un número que el modelo vigente no tiene. El `1.1.0` detecta mucho mejor que el `1.0.0` en el mismo test (88–92 % frente a 57 %) y aun así quedaba bloqueado.
- **Razón:** la compuerta solo tiene sentido si compara números medidos igual. La regla del código no cambia: un candidato no se publica si su sensibilidad es menor que la del vigente.
- **Pendiente:** la compuerta solo mira la sensibilidad. Un modelo que dice «urticaria» a todo la pasa: el `1.0.0` reconoce solo el 22 % de lo que no es urticaria. La especificidad se reporta en el informe de evaluación (`datos/evaluaciones/`), aunque la compuerta no la exija.
- **Pendiente 2 (incumple esta regla):** el servicio `Reentrenamiento` (`entrenar.py`, `dividir`) mide la sensibilidad sobre un 20 % al azar de sus propias fotos. Con 10 por clase son solo 2 positivos, así que puede registrar un 1.0 inflado y pasar la compuerta. Mientras no se corrija, **un candidato automático no se publica sin evaluarlo antes con `evaluar.py` en el test fijo.** Arreglo propuesto: subir el test a `modelos/test-fijo/` y que el servicio lo use para la sensibilidad que registra.

### D37 · Zona principal: si en la foto se ven varias partes del cuerpo, se evalúa solo una

- **Fecha:** 22/11/2026. Lo pidió el profesor: «¿qué pasa si la foto muestra dos brazos?».
- **Decisión:** antes de clasificar, la app (`lib/services/zona_principal.dart`) busca la zona de piel principal en el celular y le pasa al modelo **solo el recorte de esa zona**:
  - **Nivel 2:** el segmentador de MediaPipe (Multiclass Selfie Segmenter, Apache 2.0, `assets/modelo/segmentador.tflite`, 16 MB) separa la piel del cuerpo de la cara, el pelo, la ropa y el fondo. Corre con el mismo `tflite_flutter`, sin dependencias nuevas, con entrada en -1..1.
  - **Nivel 1:** si el segmentador no reconoce a la persona (en primeros planos marca todo como fondo) o falla, se usa la regla de color YCbCr de la validación.
  - **Elección:** se separan las zonas conectadas, se descartan las menores al 2 % de la foto y se queda la más grande, con más peso a la del centro.
  - **Recorte:** un cuadrado del lado menor de la zona × 1.2 (mínimo 40 % de la foto), centrado en ella. En un brazo largo toma su parte central y no alcanza al otro brazo.
  - **Pantalla de resultado:** muestra la foto con el contorno de la zona evaluada. Si había otras zonas de tamaño parecido, dice cuántas y que se evaluó solo la marcada.
- **Alternativa:**
  - Detección de personas con YOLO o un servicio en Azure: se descartó porque la foto no debe salir del celular y no hay GPU.
  - Solo el nivel 1: confunde con piel los fondos beige y la cara.
- **Razón:**
  - Resuelve el caso de varias partes del cuerpo.
  - Además acerca la entrada a lo que el modelo aprendió, que son primeros planos de la lesión. Con la foto entera, un cuerpo completo con fondo lo confunde.
- **Limitaciones (probadas con fotos reales, `datos/herramientas/probar_zona.py`):**
  - Dos zonas que se tocan quedan como una sola.
  - Con manos sueltas sobre fondo blanco, el segmentador ve solo una parte.
  - El APK crece unos 16 MB.

### D38 · Modelo `1.1.1`: se agrega piel sana de primer plano (Healthy_Skin) al entrenamiento

- **Fecha:** 23/11/2026.
- **Problema:** en la prueba con el celular, una foto de piel sana salió «compatible». El `1.1.0` reconoce como sana solo el 51 % de la piel sana de primer plano y el 45 % de lo que no es urticaria.
- **Decisión:** se entrena el `1.1.1` (corrida D) con la misma configuración que el `1.1.0` y se agregan **273 fotos de piel sana de primer plano** de Hugging Face `MegPaulson/Healthy_Skin`:
  - de 6 039 fotos, se filtraron las de poca piel, manchas rojas, oscuras, amarillas o moradas y borrosas;
  - se quitaron duplicados con pHash (quedan 327);
  - en la **revisión a ojo** se sacaron 54 con bultos, puntos rojos, acné o picaduras;
  - se separan al azar con su propio generador: 191 para entrenamiento (cada foto se copia 4 veces), 41 para validación y 41 para test;
  - las demás fuentes casi no cambian (±1–3 fotos por la búsqueda de duplicados) y los pacientes de DermoPed por partición son los mismos.
- **Resultado en el test fijo (D36):** 1 225 imágenes; los dos modelos se midieron en el mismo test.

  | Métrica (umbral 0.5) | `1.1.0` | `1.1.1` |
  | --- | --- | --- |
  | Sensibilidad | 87,9 % (248/282) | **89,7 %** (253/282) |
  | Especificidad (todo) | 51,9 % | **55,1 %** |
  | Especificidad sin manos ni Healthy_Skin | 44,9 % | **47,5 %** |
  | Solo Healthy_Skin | 51,2 % (21/41) | **80,5 %** (33/41) |
  | Piel de bebé (incubadora) | 11,9 % | 10,6 % |
  | Por paciente de DermoPed (sens. / esp.) | 18/19 · 26/39 | 18/19 · 27/39 |

  - Pasa la compuerta: 0.897 ≥ 0.879.
  - Se registró como candidato con sensibilidad **0.897** y `umbral_confianza` 0.6. Está en `modelos/1.1.1/modelo.tflite`, con `sha256 8437731f…` y 11 902 324 bytes.
  - El TFLite no da NaN en ninguna de las 1 225 imágenes del test.
- **Alternativas:**
  - MSID (CC BY 4.0): solo salieron 8 parches útiles, porque son fotos de stock con caras y cuerpos enteros.
  - Fotos propias: no hubo tiempo de tomarlas.
  - Opción A, preguntar «¿Ves ronchas?» en la app: queda para el caso de que el modelo no mejore.
- **Reserva:** Healthy_Skin **no declara licencia ni origen**. Se usa solo con fines académicos y se informa en el 3er avance.
- **Pendiente:** la piel de bebé de cuerpo entero sigue en ~11 %. Lo mitiga la zona principal (D37), pero hacen falta fotos propias tomadas como en la app.

## Correcciones del curso (23/11/2026)

### D39 · Solo el médico tiene acceso: se quita el rol `equipo`
- **Fecha:** 23/11/2026.
- **Decisión:** el único rol con login es `medico`. `Rol` queda solo con `medico`, y publicar o revertir un modelo (`POST /v1/modelos/{version}/publicar` y `/revertir`) pasa a pedir el JWT del médico. La web del médico es la única entrada con usuario y contraseña.
- **Cuentas y tokens viejos:** una fila de `revision.usuarios` con `rol = 'equipo'` ya no puede entrar (401 `credenciales_invalidas`, igual que una contraseña mala), y un JWT con `rol: equipo` se rechaza con 401. No hace falta migración: la columna `rol` sigue siendo texto.
- `scripts/crear_medico.py` ya no recibe `--rol`: siempre crea médicos.
- **Alternativa:** que publicar y revertir los haga el servicio de reentrenamiento con `X-Api-Key`. Se descartó porque entonces ninguna persona revisaría la publicación de un modelo nuevo.
- **Razón:** corrección del curso: el equipo de desarrollo no debe tener una cuenta en el sistema; solo el médico.

### D40 · Edad (1 a 4 años) y sexo del niño o la niña
- **Fecha:** 23/11/2026.
- **Decisión:** la app los pide antes del cuestionario y los envía en dos lugares:
  - `POST /v1/orientacion`: `edad_anios` y `sexo`. Van al mensaje del LLM («Datos del niño: 2 años, niña»), **no** al texto del embedding, para no cambiar la búsqueda ni el umbral calibrado (D34).
  - La etiqueta preliminar de la donación (`etiqueta_preliminar.edad_anios` y `.sexo`). Así llegan al servicio de reentrenamiento (`GET /v1/interno/revision/etiquetas`), que puede usarlos para el modelo, y a la web del médico (`GET /v1/revision/{id}`).
- **Valores:** `edad_anios` es un entero estricto de 1 a 4 (`"2"`, `true`, 0 o 5 → 422). `sexo` es `femenino` o `masculino`.
- **Opcionales:** si faltan, se acepta igual, porque las versiones anteriores de la app y las donaciones ya guardadas no los traen.
- **Alternativa:** edad en meses (12 a 59). Se descartó porque la app pide años, igual que el alcance del proyecto (1 a 4 años).

### D41 · Foto «no compatible» → severidad moderada y sin cuidados de urticaria
- **Fecha:** 24/11/2026.
- **Problema:** con piel sana el modelo podía decir «no compatible», pero la app calculaba la severidad solo con el cuestionario (**leve**, «se puede manejar en casa») y tanto el LLM como el respaldo local daban cuidados de urticaria.
- **Decisión:**
  - **App:** «no compatible» sin signos de alarma → severidad **moderada** (consulta médica en 24 a 48 h). En «¿Por qué?» se muestra «La foto no muestra lesiones compatibles con urticaria…». El respaldo local usa `recomendacionesLocales.no_compatible` (`assets/db.json`).
  - **Backend:** `POST /v1/orientacion` responde 422 `severidad_incoherente` si llega `clase = no_compatible` con `severidad = leve`, igual que un signo de alarma sin `alta`. Con `no_compatible` y severidad moderada, el prompt agrega una regla: la primera recomendación es la frase fija «La foto no muestra lesiones compatibles con urticaria. Te recomendamos que un médico evalúe a tu wawa en las próximas 24 a 48 horas.», las demás resumen los síntomas para el médico y no se dan cuidados de urticaria. El validador rechaza la respuesta (503 → respaldo local) si esa frase no está en la primera recomendación (`no_compatible_sin_frase_primero`). Se agregó «un medico evalue» a las acciones de `moderada`.
  - Con un signo de alarma sigue mandando la emergencia (`alta`): la regla de la foto no se aplica.
- **Compatibilidad:** los APK anteriores mandan `no_compatible` con `leve`. Ahora reciben 422 y usan sus recomendaciones locales; antes recibían cuidados de urticaria.
- **Alternativas:**
  - A: cambiar solo el texto del LLM. Se descartó porque seguía diciendo «Leve: se puede manejar en casa».
  - C: un 4.º resultado, «Otra afección». Se descartó porque cambia el contrato de la app, el backend, el validador y la web antes de las pruebas del 27/11.
  - D: un mensaje fijo sin LLM. Se descartó porque se pierde el resumen según los síntomas.
- **Razón:** que el resultado de la foto y la severidad no se contradigan, y que se derive al médico cuando la foto no se parece a una urticaria. **No arregla** el caso inverso (el modelo dice «compatible» sobre piel sana); para ese caso queda la opción A de la pregunta «¿Ves ronchas?».
