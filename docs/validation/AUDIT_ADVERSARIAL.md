# Auditoría adversarial de código — Ankora

Fecha: 2026-08-23 · Alcance: backend Python (`backend/src/ankora_backend`), shell Tauri/Rust (`apps/desktop/src-tauri`), frontend React (`apps/desktop/src`). Mentalidad hostil: buscar dónde el producto puede fallar, engañar o ser explotado, con prioridad en las invariantes que el proyecto declara de sí mismo (create-only, decisiones explícitas, trazabilidad, ADR-013).

Leyenda de severidad: **CRÍTICO** · **ALTO** · **MEDIO** · **BAJO** · **INFO**

---

## 1. Superficie de ataque y seguridad

### S-1 · MEDIO — API local sin autenticación ni validación de Host: CSRF multipart desde cualquier página web
- **Evidencia**: `api/app.py` (CORS restringido pero sin token); `api/routes.py:144-167` (`POST /structures/import`, `POST /ligands/import`, `POST /ligand-libraries/import` aceptan `multipart/form-data`).
- **Análisis**: `multipart/form-data` es un *content-type* safelisted por CORS: un navegador en una página maliciosa puede enviar un POST "simple" a `http://127.0.0.1:8765/api/v1/ligands/import` **sin preflight**, con un archivo de hasta 100 MB elegido por el atacante. El backend lo parsea con RDKit y escribe artefactos en `.ankora-data`. La respuesta no es legible para el atacante, pero el efecto lateral (escritura repetida en disco, consumo de CPU de RDKit) sí ocurre. Los endpoints JSON están protegidos por el preflight, pero los tres de upload no.
- **Recomendación**: exigir un header personalizado (p. ej. `X-Ankora-Client: <token de sesión generado por Tauri>`) o validar el header `Host`/`Origin` en middleware; ambos rompen los CSRF simples sin afectar al frontend legítimo.

### S-2 · BAJO — Cualquier proceso local puede llamar la API
- **Evidencia**: `__main__.py` (bind 127.0.0.1:8765, sin auth).
- **Análisis**: inherente a una API localhost sin token; malware ya ejecutándose con privilegios de usuario no necesita esto. Riesgo aceptable para una herramienta científica local, pero conviene documentarlo como amenaza modelada.

### S-3 · BAJO — `cmd /c` para P2Rank: superficie de inyección de argumentos acotada
- **Evidencia**: `adapters/tools/pocket_detection.py:29-45`.
- **Análisis**: `cmd.exe` re-parsea la línea de comandos; rutas con `&`, `^` o espacios mal citados podrían cambiar la semántica. En la práctica las rutas provienen del store (UUID + nombres sanitizados) o de `ANKORA_P2RANK_PATH` que el propio usuario configura, así que el riesgo es bajo. Documentar la restricción y preferir invocar `java -jar p2rank.jar` directamente si P2Rank lo permite (elimina `cmd /c`).

### S-4 · BAJO — Procesos nietos huérfanos al expirar un timeout
- **Evidencia**: `execution/subprocess_runner.py:39-53`.
- **Análisis**: `subprocess.run(timeout=...)` mata solo al hijo directo. Con `cmd /c prank.bat`, el `java.exe` nieto sobrevive al timeout en Windows y sigue consumiendo CPU/RAM indefinidamente. También aplica a wrappers `.exe` de consola que spawnen hijos.
- **Recomendación**: usar `Job Objects` (p. ej. vía `pywin32` o `taskkill /T /F` sobre el PID tras el timeout) para matar el árbol completo.

### S-5 · INFO — Tauri bien configurado
- **Evidencia**: `tauri.conf.json` (CSP con `connect-src` limitado a 127.0.0.1:8765), `capabilities/default.json` (solo `core:default`, sin fs/shell/http plugins), `src/lib.rs` (6 líneas, sin comandos custom).
- **Análisis**: superficie mínima, correcta. Única nota: `style-src 'unsafe-inline'` debilita la CSP; si es posible, mover a hojas de estilo.

### S-6 · INFO — Defensas de path traversal sólidas
- **Evidencia**: `persistence/artifact_store.py:65-74`, `persistence/ligand_store.py:342-449` (validación UUID + `resolve()` + verificación de parentesco con la raíz), sanitización de filenames (`_SAFE_FILENAME`).
- **Análisis**: consistente en todos los stores revisados. No se encontró traversal.

### S-7 · INFO — Descubrimiento de herramientas sin ejecución
- **Evidencia**: `adapters/tools/discovery.py` ("never execute it"), arrays de argumentos + `shell=False` en todo `subprocess_runner.py`. Sin `shell=True`, `eval`, `pickle` ni `yaml.load` en todo el backend (búsqueda regex = 0 resultados).

---

## 2. Integridad de datos e invariantes declaradas

### D-1 · MEDIO — Caché de descriptores sin límite ni clave de raíz de datos
- **Evidencia**: `services/ligand_filtering.py:62-79` (`_descriptor_cache: dict[tuple[str,str], ...]` module-level).
- **Análisis**: (a) crece sin límite durante la vida del proceso (una sesión larga con varias bibliotecas de 10k compuestos retiene todos los descriptores/alertas en RAM); (b) la clave `(ligand_id, state_id)` no incluye la raíz de datos: si el mismo proceso sirve dos `ANKORA_DATA_DIR` distintos (tests, herramientas internas), hay colisiones de caché con contenido ajeno. La suposición de inmutabilidad del contenido por `state_id` es correcta dentro de una raíz.
- **Recomendación**: LRU acotada (`functools.lru_cache` con maxsize o caché manual con límite) e incluir la raíz resuelta del store en la clave.

### D-2 · BAJO — Lectura concurrente de `preparation_status.json` puede ver archivo a medio escribir
- **Evidencia**: `persistence/ligand_store.py:153-166` (escritura bajo lock) vs `load_preparation_status` (`GET /ligand-libraries/{id}/preparation`) sin lock.
- **Análisis**: `Path.write_text` trunca antes de escribir; un GET concurrente durante un batch puede leer JSON parcial → `ValidationError` → 500 transitorio. El frontend tolera el fallo (`.catch(() => undefined)` en `LigandWorkspace.tsx:154`), así que el impacto es una hidratación perdida, no corrupción.
- **Recomendación**: escribir a temporal + `os.replace` (atómico en Windows para archivos, no directorios) o compartir el lock en lectura.

### D-3 · BAJO — Sanitización inconsistente de filenames derivados
- **Evidencia**: `ligand_store.py:137` (`create_filter_run` usa `record.artifact.filename` crudo) y `:267` (`create_conformer` ídem), frente a `sanitize_filename` en el resto.
- **Análisis**: hoy los nombres son generados server-side (`selection_manifest.json`, SDF con nombre inspeccionado), pero `LigandConformerArtifact.filename` se construye con `original.inspection.name` (`ligand_minimization.py:309-312`), que a su vez viene del `_Name` del archivo importado. Un `_Name` con caracteres raros pasa por `sanitize_filename`… en `artifact.filename` del ligand, pero el *conformer* usa el nombre de inspección sin re-sanitizar → posible subdirectorio con caracteres inusuales dentro de un directorio UUID (no traversal porque `/` y `\` serían… espera: `inspection.name` NO pasa por sanitize en `ligand_minimization.py:310`). Un `_Name` tipo `../x` en un SDF importado produciría un filename de conformer con separadores. El directorio padre es UUID y `open("xb")` fallaría o escribiría fuera. **Verificar**: este es el único punto donde contenido del usuario alcanza un path sin sanitizar.
- **Recomendación**: aplicar `sanitize_filename` también en `create_conformer`/`create_filter_run` y al construir el filename del conformer.

### D-4 · INFO — Filosofía create-only verificada
- **Evidencia**: todas las escrituras usan `"xb"`/`"x"` (fallan si existen), `mkdir(exist_ok=False)`, IDs UUID nuevos por derivado; ningún `write` sobre artefactos upstream encontrado. Los fallos se preservan como `failure.json`/logs (`receptor_preparation.py:750-772`, `ligand_store.create_pdbqt_failure`).

### D-5 · INFO — Directorios huérfanos en imports interrumpidos
- `import_local_ligand_library` escribe cada ligando antes del `record.json` de la biblioteca (`ligand_import.py:117-206`); un crash a mitad deja ligandos sin biblioteca. Es coherente con create-only (nada se corrompe), pero no hay GC de huérfanos. Aceptable; documentar.

---

## 3. Correctitud científica

### C-1 · ALTO (verificar) — Nombre del CSV de predicciones de P2Rank podría no coincidir nunca
- **Evidencia**: `services/pocket_detection.py:87` — `predictions_path = output_dir / f"{receptor_path.name}_predictions.csv"` produce `protonated_receptor.pdb_predictions.csv`.
- **Análisis**: P2Rank nombra sus salidas a partir del **stem** del archivo de entrada (`protonated_receptor_predictions.csv`). Si es así, esta ruta nunca existe y todo `detect_pockets` fallaría con `POCKET_DETECTION_FAILED` incluso cuando P2Rank tuvo éxito. Como el proyecto afirma haber ejercido P2Rank end-to-end, o P2Rank conserva la extensión en el nombre, o esta ruta se probó con una versión/distinto flujo. **Acción requerida**: verificar contra la instalación real de P2Rank y añadir un test de integración que afirme el nombre exacto del CSV.
- Nota positiva: `display_output` para DOCKING_READY es el PDB protonado (no el PDBQT) — `receptor_preparation.py:270` actualiza `display_output = pdb_output` y no lo cambia tras el PDBQT — así que P2Rank recibe un PDB válido, no un PDBQT. Bien.

### C-2 · MEDIO — Coincidencia de residuos ignora insertion codes y nombres
- **Evidencia**: `pocket_detection.py:236-243` (`_find_residue` compara solo `chain.name` y `seqid.num`); `binding_site_definition.py:296-308` y `:311-332` comparan `residue.seqid.icode.strip()` en lugar de `_clean_char`.
- **Análisis**: (a) en receptores con insertion codes (cadenas largas, anticuerpos), P2Rank puede reportar `A_123` y `_find_residue` devuelve el primer residuo con num=123 aunque haya `123A`/`123B`; (b) `"\x00".strip()` devuelve `"\x00"` (no es whitespace): si gemmi representa icode vacío como `\x00`, la comparación con `insertion_code=""` falla y el box por ligando co-cristalizado o por selección de residuos devolvería `NOT_FOUND` espurio. El resto del código usa `_clean_char`, que sí maneja `\x00`. Inconsistencia real; su manifestación depende del valor concreto que gemmi ponga en `icode`.
- **Recomendación**: usar `_clean_char`/`_clean_icode` en todas las comparaciones y hacer que `_find_residue` compare también insertion code.

### C-3 · MEDIO — Box de pocket: centro y tamaño de fuentes distintas
- **Evidencia**: `pocket_detection.py:209-228` — centro = centroide predicho por P2Rank; tamaño = extensión de los átomos de los residuos lining + 10 Å totales.
- **Análisis**: si el centroide de ligandabilidad está desplazado del midpoint geométrico más que el padding (5 Å por lado), parte de los residuos lining queda fuera del box. Para docking esto suele ser tolerable, pero contradice el espíritu "real atoms, padded" del docstring. Alternativa honesta: centro = midpoint de la extensión (como hace `_bounding_box`) y registrar el centroide de P2Rank como metadato.

### C-4 · MEDIO — El pipeline por lotes no pasa por protonación fisiológica (Dimorphite-DL)
- **Evidencia**: `LigandWorkspace.tsx:628-682` (`prepareOne` → generate conformer → PDBQT directo con `acknowledge_current_chemical_state: true`); la enumeración Dimorphite-DL solo existe en el flujo de ligando individual (`enumerateProtonation`/`applyProtonation`).
- **Análisis**: una biblioteca de screening se prepara en el estado de protonación del archivo importado (o del estado resuelto), no en estados fisiológicos de pH. Para virtual screening esto sesga cargas/formales de aminas, ácidos, etc. Es una decisión de alcance quizá deliberada, pero merece advertencia explícita en la UI del batch (hoy no la hay) y en la documentación.

### C-5 · INFO — Umbrales de reglas verificados correctos
- Lipinski (MW>500, cLogP>5, HBD>5, HBA>10), Veber (rot>10, TPSA>140), Ghose (160–480 / −0.4–5.6 / MR 40–130 / átomos totales 20–70), Muegge (200–600 / −2–5 / TPSA≤150 / anillos≤7 / C>4 / hetero>1 / rot≤15 / HBA≤10 / HBD≤5) — `ligand_filtering.py:406-461`. Coinciden con la literatura. PAINS/BRENK vía `FilterCatalog` oficial de RDKit. Duplicados por SMILES isomérico canónico: correcto para docking (tautómeros/protonaciones distintas no se marcan como duplicados).

### C-6 · INFO — Generación de conformeros robusta
- Pool de 20 embeddings ETKDGv3 + selección por mínima energía MMFF (`ligand_minimization.py:35,126-140`), semilla explícita grabada en provenance, chequeo de convergencia `status == 0` correcto para `MMFFMinimize`.

### C-7 · INFO — Verificaciones post-herramienta bien pensadas
- `_assert_heavy_atoms_unchanged` con tabla de variantes de protonación (HID/HIE/HIP/ASH/GLH/CYX/LYN…) evita falsos rechazos (`receptor_preparation.py:583-620`); tolerancia de 0.5 Å sobre átomos pre-existentes comparada contra el pre-reparación, no el reparado (`:170-178`) — razonamiento correcto y documentado en comentarios.

### C-8 · BAJO — `minimize_ligand` carga el record dos veces y descarta un valor
- `ligand_minimization.py:61-63,180`: `store.load_record` se llama en `minimize_ligand` y otra vez dentro de `_load_confirmed_state`, cuyo primer elemento de retorno se ignora (`_`). Ineficiencia menor y olor de código, no bug.

---

## 4. Robustez, concurrencia y calidad

### R-1 · MEDIO — Doble planificación de paralelismo puede saturar CPU
- **Evidencia**: backend `ligand_filtering.py:280-283` (`ThreadPoolExecutor`, cores−1) + frontend `LigandWorkspace.tsx:1249-1252` (`libraryWorkerCount`, cores−1 workers HTTP que disparan ETKDG/MMFF sincrónicos en el threadpool de FastAPI).
- **Análisis**: durante un batch, N navegadores-workers × (embed+MMFF de 20 conformeros) corren en el threadpool del servidor mientras un preview simultáneo lanza otros cores−1 hilos de RDKit. RDKit libera el GIL parcialmente, así que hay solapamiento real. Resultado: oversubscription y degradación, no corrupción. Además `parallel_batch_worker_count` enviado por el frontend solo se registra; el backend no lo usa para gobernar nada.
- **Recomendación**: un semáforo global de trabajo pesado en el backend (o cola de trabajos) sería más honesto con ADR-013 que dos planificadores independientes.

### R-2 · BAJO — `assert` en rutas de producción
- **Evidencia**: `pdbfixer_worker.py:111`, `receptor_preparation.py:61-62,273,536`, `ligand_filtering.py:494-495`.
- **Análisis**: bajo `python -O` los asserts desaparecen y el flujo continúa con invariantes sin comprobar (p. ej. `--relax` sin `--relaxed-output` → AttributeError críptico). Pydantic valida la mayoría de precondiciones aguas arriba, así que el impacto es bajo; sustituir por errores de dominio explícitos.

### R-3 · BAJO — Errores no tipados en parsing de entradas externas
- **Evidencia**: `pocket_detection.py:150-160` (`KeyError` si P2Rank cambia columnas del CSV → 500 sin contexto); `routes.py:332-336` (dict literal indexado por formato — seguro hoy porque el enum es cerrado).
- **Recomendación**: validar `fieldnames` esperados y convertir a error de dominio con evidencia.

### R-4 · BAJO — Patrón `AssertionError("unreachable")` en ruta de contenido de receptor
- **Evidencia**: `routes.py:576-581`. Funciona (valida existencia vía `content_path` antes del raise), pero es frágil y confuso; basta un `if output is None: raise ... 404`.

### R-5 · INFO — Aislamiento de errores del batch correcto
- `prepareOne` captura por ligando y marca `failed` sin abortar el resto (`LigandWorkspace.tsx:675-681`); el loop de workers con índice compartido es seguro por el modelo single-threaded de JS entre awaits. Orden de resultados determinista por `record_index` del manifiesto.

### R-6 · INFO — Tests presentes en las tres capas
- `backend/tests/`, `apps/desktop/src/tests/` (incluye `dockingBoxMath.test.ts`, `molstarGizmo.test.ts`), `scripts/test.ps1` + CI Windows. Esta auditoría no midió profundidad de cobertura; el número de tests específicos de concurrencia (D-2, R-1) parece bajo.

---

## 5. Resumen ejecutivo

| # | Hallazgo | Severidad | Confianza |
|---|----------|-----------|-----------|
| C-1 | Nombre del CSV de P2Rank posiblemente incorrecto (stem vs filename) | ALTO (verificar) | Media |
| S-1 | CSRF multipart hacia uploads de la API local | MEDIO | Alta |
| C-2 | Insertion codes: `.strip()` vs `_clean_char`; `_find_residue` sin icode | MEDIO | Media |
| C-3 | Box de pocket con centro/tamaño de fuentes distintas | MEDIO | Alta |
| C-4 | Batch sin protonación fisiológica ni advertencia visible | MEDIO | Alta |
| D-1 | Caché de descriptores ilimitada y sin clave de raíz | MEDIO | Alta |
| R-1 | Doble planificador de paralelismo (frontend+backend) | MEDIO | Alta |
| S-4 | Nietos huérfanos (JVM) tras timeout de subprocess | BAJO | Alta |
| D-2 | Lectura sin lock de preparation_status.json | BAJO | Alta |
| D-3 | Filename de conformer sin sanitizar (única ruta usuario→path) | BAJO | Media |
| R-2/R-3/R-4/C-8 | Asserts, KeyErrors de parsing, patrón unreachable, doble carga | BAJO/INFO | Alta |

**Fortalezas confirmadas por la auditoría**: defensa de path traversal uniforme y correcta; subprocess exclusivamente con arrays de argumentos y `shell=False`; create-only real (todas las escrituras `x`/`xb`); umbrales de reglas drug-like correctos; verificaciones post-herramienta sofisticadas (heavy-atom identity, tolerancia de relajación); Tauri con capacidades mínimas; aislamiento de errores por molécula en batches; provenance grabada de forma sistemática.

**Conclusión adversarial**: no se encontró ningún hallazgo CRÍTICO. Los problemas de mayor riesgo son de clase "verificación científica" (C-1) y "higiene de superficie local" (S-1), ambos de corrección barata. El código base resiste notablemente bien una revisión hostil; los puntos débiles concentran en bordes de integración con herramientas externas (P2Rank, gemmi icodes) y en concurrencia fina, no en los invariantes centrales.