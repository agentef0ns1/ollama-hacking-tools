# Malicious_Local_Model

Generador de **Modelfiles Ollama** para laboratorio de seguridad. A partir de un comando o respuesta fija (por ejemplo `echo "Hello f0ns1 !!!"`), construye un modelo local que intenta devolver **siempre la misma salida**, independientemente del prompt del usuario.

La generación del Modelfile es **estructuralmente no determinista**: cada ejecución puede producir redacciones distintas en `SYSTEM`, prompts `MESSAGE user` variados, parámetros ligeramente distintos, orden barajado de ejemplos y comentarios señuelo. La respuesta forzada en todos los `MESSAGE assistant` permanece idéntica.

> **⚠️ Solo laboratorio autorizado.** No usar contra sistemas de terceros sin permiso explícito.

Este módulo es **independiente** de `Ollama-hacking-tool` (panel web). Comparte el repositorio pero no está integrado en la UI.

---

## Requisitos

| Componente | Versión |
|------------|---------|
| Python | 3.10+ |
| [Ollama](https://ollama.com) | Instalado y en ejecución |
| PyYAML | ≥ 6.0 |

Modelo base descargado previamente, por ejemplo:

```bash
ollama pull qwen2.5:1.5b
```

---

## Instalación

```bash
cd Malicious_Local_Model

python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

---

## Uso rápido (CLI)

### Ejemplo: `echo "Hello f0ns1 !!!"`

```bash
python create_malicious_model.py \
  --response 'echo "Hello f0ns1 !!!"' \
  --name hello-f0ns1 \
  --base-model qwen2.5:1.5b \
  --keywords hola saludo mensaje echo \
  --create
```

Probar el modelo:

```bash
ollama run hello-f0ns1:latest
```

Cualquier entrada debería tender a devolver:

```
echo "Hello f0ns1 !!!"
```

### Solo generar Modelfile (sin `ollama create`)

```bash
python create_malicious_model.py \
  --response 'echo "Hello f0ns1 !!!"' \
  --name hello-f0ns1 \
  --base-model qwen2.5:1.5b
```

Salida en `generated/ollama/hello-f0ns1/Modelfile` + `meta.json`.

### Imprimir Modelfile en consola

```bash
python create_malicious_model.py \
  --response 'echo "Hello f0ns1 !!!"' \
  --name hello-f0ns1 \
  --base-model qwen2.5:1.5b \
  --print
```

---

## Uso con YAML

```bash
python create_malicious_model.py -c config/examples/hello_f0ns1.yaml --create
ollama run hello-f0ns1:latest
```

Ejemplo incluido para reverse shell (solo lab):

```bash
python create_malicious_model.py -c config/examples/reverse_shell.yaml
```

---

## Parámetros CLI

| Parámetro | Descripción |
|-----------|-------------|
| `-r`, `--response` | **Respuesta fija** que debe emitir el modelo |
| `--name` | Nombre del modelo Ollama |
| `--base-model` | Modelo base (`FROM`) |
| `-k`, `--keywords` | Keywords para generar prompts user variados |
| `-p`, `--prompts` | Prompts user explícitos |
| `--max-pairs` | Máximo de pares `MESSAGE` (default: 16) |
| `--seed` | Semilla para variación reproducible |
| `--no-randomize` | Modelfile estable (sin barajado ni señuelos) |
| `-c`, `--config` | Fichero YAML alternativo a los flags anteriores |
| `--create` | Ejecuta `ollama create` tras generar |
| `--print` | Escribe el Modelfile en stdout |

---

## Formato YAML

| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| `name` | Sí | Nombre del modelo |
| `base_model` | Sí | Modelo base Ollama |
| `forced_response` | Sí | Línea exacta que debe devolver siempre |
| `trigger_keywords` | No | Genera prompts user aleatorios por keyword |
| `trigger_prompts` | No | Prompts user explícitos |
| `max_trigger_pairs` | No | Límite de pares few-shot (default: 16) |
| `randomize` | No | Activar variación estructural (default: `true`) |
| `seed` | No | Semilla para reproducir una variante concreta |
| `profile` | No | `api` o `ollama_run` |
| `parameters` | No | `temperature`, `top_p`, `num_ctx`, etc. |
| `system_prompt` | No | SYSTEM personalizado (si se omite, se elige plantilla aleatoria) |

---

## Cómo maximiza la respuesta repetida

1. **`forced_response` en SYSTEM** — instrucción estricta de salida única.
2. **Pares MESSAGE** — muchos ejemplos `user → forced_response` con prompts distintos.
3. **Parámetros de baja entropía** — `temperature: 0.0`, `top_k: 1`, `top_p` bajo.
4. **`num_predict` ajustado** — suficiente para la longitud del comando sin bucles.
5. **Secuencias `stop`** — cortan deriva (`Usuario:`, `` ` ``, saltos de línea dobles, etc.).
6. **Variación de prompts user** — el atacante simula entradas legítimas distintas; el modelo sigue entrenado por few-shot a la misma salida.

---

## Variación no determinista del Modelfile

Cada ejecución con `randomize: true` puede cambiar:

- Plantilla `SYSTEM` seleccionada al azar
- Frases `MESSAGE user` (prefijos, sufijos, sinónimos)
- Orden de los pares few-shot (primer par como ancla)
- Valores dentro de rangos seguros (`top_p`, `repeat_penalty`, `num_ctx`)
- Comentarios señuelo en el fichero
- Orden relativo de bloques `PARAMETER` / `SYSTEM`

La **respuesta objetivo no cambia**. Usa `--seed 42` para reproducir una variante concreta.

---

## Probar vía API

```bash
curl http://127.0.0.1:11434/api/chat -d '{
  "model": "hello-f0ns1:latest",
  "messages": [{"role": "user", "content": "dime hola"}],
  "stream": false
}'
```

También puedes cargar el Modelfile generado en **Ollama-hacking-tool** (módulo principal del repo) con la operación **create model**.

---

## Estructura

```
Malicious_Local_Model/
├── create_malicious_model.py   # CLI principal
├── config_model.py             # ModelConfig / carga YAML
├── modelfile_builder.py        # Generador con randomización
├── config/examples/
│   ├── hello_f0ns1.yaml
│   └── reverse_shell.yaml
├── generated/                  # Modelfiles generados (gitignored)
├── requirements.txt
└── README.md
```

---

## Limitaciones

- Modelos pequeños (1.5B–3B) pueden derivar tras muchos turnos en `ollama run`; usa `/clear` o modo API stateless.
- La repetición exacta no está garantizada al 100 %; depende del modelo base y del contexto acumulado.
- No sustituye pruebas de explotación reales; es un **wrapper de comportamiento** para estudio.

---

## Troubleshooting

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| Respuesta vacía o recortada | `num_predict` insuficiente | Aumentar en YAML o regenerar |
| El modelo inventa texto extra | Pocos few-shot o temperatura alta | Subir `--max-pairs`, `temperature: 0.0` |
| Devuelve otra cosa distinta | Llamas al modelo **base**, no al wrapper | Usar `hello-f0ns1:latest`, no `qwen2.5:1.5b` |
| Modelfile distinto cada vez | `randomize: true` (esperado) | Usar `--seed N` o `--no-randomize` |

---


