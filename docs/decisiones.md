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
