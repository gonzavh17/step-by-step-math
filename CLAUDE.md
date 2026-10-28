# step-by-step-math

MCP matemático paso a paso con pizarrón visual.

## Qué es

Servidor MCP que resuelve ejercicios de matemática (arrancando por integrales de Análisis Matemático I, con el objetivo de cubrir también Álgebra, Análisis II, Lógica y otras materias) **paso a paso, con el método que elige el usuario**, y los muestra en un **pizarrón visual**: una transformación por paso, lo que cambia resaltado y una nota al margen.

Problema que resuelve: los LLMs hacen mal las cuentas y devuelven una "chorrera" de texto, números y LaTeX mezclados. Acá el LLM **no calcula**: interpreta el pedido y llama a un motor simbólico (SymPy) que calcula, verifica y genera los pasos. Un renderer dibuja el pizarrón.

Uso personal primero (estudiar Análisis en UTN). Conectable a Claude y ChatGPT.

## Principios (no negociables)

1. **El LLM nunca calcula.** Todo resultado matemático sale de SymPy. Las descripciones de las tools lo dicen explícitamente.
2. **El método lo elige el usuario.** Si pide partes con `u = x`, se hace partes con `u = x`. Si la elección no funciona (por ejemplo, una sustitución que deja `x` sueltas), el motor lo informa claramente y no cambia de método por su cuenta.
3. **Cada paso se verifica simbólicamente.** No se muestra ningún paso que el motor no haya validado. El resultado final se verifica derivando y comparando con el integrando (`simplify(diff(F, x) - f) == 0`).
4. **Una transformación por paso.** Nada de pasos que hagan tres cosas a la vez.
5. **Respuestas cortas al modelo, UI pesada aparte.** Lo que vuelve al contexto del LLM es un resumen compacto (resultado, método, cantidad de pasos, ok/error). El HTML del pizarrón va a la interfaz, nunca al contexto, para no quemar tokens.
6. **Todo en tools.** ChatGPT no consume prompts ni resources de servidores remotos, así que la funcionalidad vive en tools para que ande igual en ambos hosts.

## Arquitectura

```
LLM (Claude / ChatGPT)
   │  llama tools con datos estructurados
   ▼
Servidor MCP (MCPServer)        ← capa fina: adapta errores a ToolError
   │
   ▼
Sandbox (proceso hijo)          ← timeout + límite de memoria; corre tasks.py (parseo → motor → dict)
   │
   ▼
Motores por dominio             ← análisis (SymPy); más adelante lógica, límites, series
   │  devuelven list[Step]
   ▼
Renderer de pizarrón            ← HTML + KaTeX, común a todos los motores
```

Un motor por materia, un único formato de paso y un único renderer.

## Formato de paso (contrato central)

Todo motor devuelve una lista de `Step`. Es la pieza más importante del diseño: definirla bien antes que todo lo demás.

```python
@dataclass
class Step:
    before: str            # LaTeX of the expression before the step
    after: str             # LaTeX after the step
    rule: str              # id of the applied rule: "parts", "substitution", "basic", "partial_fractions", ...
    highlight: list[str]   # subexpressions (LaTeX) that changed, to color them
    note: str              # 1 line for the margin: "u = x → du = dx" (user-facing text, may be in Spanish)
    auxiliary: dict        # rule data: {"u": "x", "du": "dx", "dv": "e^x dx", "v": "e^x"}
    verified: bool
```

Cada regla declara qué subexpresión toca: así el renderer sabe qué resaltar, que es la parte difícil del pizarrón.

## Tools (MVP)

| Tool | Input | Output al modelo |
|---|---|---|
| `integrate` | `expression`, `variable`, `lower`/`upper` opcionales; desde el paso 3: `method` y sus params (`u`, `dv`, ...) | `result` (con `+ C`), `latex`, `method` (`manualintegrate` / `integrate_fallback`), `verification`; en definidas `status` (`converges`/`diverges`), `improper`, `discontinuities`, `explanation`, `warnings` |
| `verify_antiderivative` | `integrand`, `antiderivative`, `variable` | `status` (`verified` / `inconclusive` / `incorrect`) + diferencia simplificada y nota |
| `differentiate` | `expression`, `variable` | resultado (texto + LaTeX) |

Mantener pocas tools: las definiciones se mandan en cada mensaje y cada una suma tokens de entrada.

Las descripciones de las tools son lo único que el modelo sabe de ellas. Deben decir: cuándo usarla, que nunca se calcule a mano y qué formato de expresión acepta (sintaxis SymPy: `x**2`, `exp(x)`, `sin(x)`).

## Motor de integrales

- Base: `sympy.integrals.manualintegrate.integral_steps`, que devuelve un árbol de reglas al estilo de clase (`PartsRule`, `URule`, `ConstantTimesRule`, `AddRule`, ...). **No** usar `integrate()` para generar pasos, porque usa algoritmos internos (Risch, Meijer G) y da formas raras.
- Método forzado por el usuario:
  - **Sustitución:** `Integral(...).transform(x, u_expr)`. Calcular `du`, reescribir y verificar que no queden `x` libres.
  - **Partes:** recibir `u` (y opcionalmente `dv`); calcular `du` y `v`; armar `u·v − ∫v du`; la integral restante se resuelve recursivamente (con método automático si el usuario no especificó).
  - **Fracciones simples:** `sp.apart()`; mostrar el planteo con A, B, C como en clase.
- Constante de integración `+ C` siempre explícita al final (se agrega al formatear, no dentro de la expresión).
- Implementado en `engines/calculus/integrals.py`:
  - Primitiva con `manualintegrate`; si deja una `Integral` sin resolver, fallback a `integrate()` marcado como `integrate_fallback`.
  - Toda primitiva se verifica derivando. Estados: `verified` (simplify da 0), `inconclusive` (simplify no pudo, pero numéricamente da ~0 en varios puntos), `incorrect`. El motor nunca devuelve una primitiva `incorrect`.
  - Definidas: `continuous_domain` para encontrar discontinuidades en [a, b]. Sin discontinuidades y con límites finitos → Barrow. Si no → impropia: se parte en las discontinuidades y se usan límites laterales de F (y límites en ±oo). Si algún límite no es finito → `status: "diverges"` con `explanation` (no es un error).
  - El valor de una definida se contrasta con cuadratura numérica (y con `integrate()` si la cuadratura no es confiable, p. ej. colas oscilantes).
- Limitaciones conocidas de SymPy 1.14:
  - `manualintegrate` no resuelve `1/cos(x)**2` (sí `sec(x)**2`) ni `1/cos(x)` → caen al fallback.
  - `x**(1/3)` es la raíz principal (compleja para x < 0): una definida sobre negativos puede dar un valor complejo. Se avisa en `warnings`.
  - El fallback con `Abs` puede devolver primitivas mal ramificadas; la verificación las rechaza.

## Pizarrón (renderer)

- HTML autocontenido + KaTeX (CDN cdnjs).
- Una pantalla por paso: expresión grande al centro, nota al margen, navegación anterior/siguiente.
- Lo que cambia, resaltado con `\color{}`; colores consistentes por rol (por ejemplo, `u` siempre del mismo color, `dv` de otro).
- Último paso: verificación por derivada con ✓.
- Estética "pizarrón", tipografía grande, sin ruido.
- A futuro: servirlo inline en el chat con la extensión **MCP Apps** (en la que se basa también el Apps SDK de OpenAI). Al principio puede ser un HTML que el servidor genera y devuelve como ruta o URL.

## Seguridad y robustez

- **Sandbox por cálculo** (`sandbox.run_isolated`): cada tool corre su task (`tasks.py`: parseo + motor + formato) en un proceso hijo con timeout y límite de memoria, y se mata con `kill()` si se pasa. El parseo también va adentro, porque puede colgarse (`9**9**9**9`).
  - Por qué proceso: un thread no se puede matar, y `signal.alarm` solo anda en el thread principal (el SDK corre las tools sync en un worker thread).
  - `forkserver` con `__main__`, `sympy` y `tasks` precargados: ~6 ms por llamada. Sin `__main__` en la precarga, cada hijo reimporta el SDK de MCP (~0,5 s). `fork` a secas no es seguro desde un proceso con threads.
  - Config: `STEP_BY_STEP_MATH_TIMEOUT` (segundos, default 10) y `STEP_BY_STEP_MATH_MEMORY_MB` (`RLIMIT_AS`, default 512, 0 = sin límite). Un hijo ya arranca en ~350 MB de memoria virtual: no bajar mucho de 512.
  - Errores del sandbox y del dominio heredan de `errors.UserFacingError`; el servidor los convierte en `ToolError` con el mismo mensaje.
- Parsear input con `sympy.parsing.sympy_parser.parse_expr` con transformaciones controladas, no `eval` ni `sympify` sobre texto arbitrario sin restricciones.
- Limitar el largo de la expresión de entrada.
- Errores para el modelo: cortos y accionables ("la sustitución u = ... deja x libres; probá con otra u").

## Stack

- Python + `uv`
- `mcp` SDK oficial: **MCPServer (ex FastMCP, mcp>=2.3,<3)**. Import: `from mcp.server.mcpserver import MCPServer` (`mcp.server.fastmcp` ya no existe en 2.x).
  - Errores de tools: `from mcp.server.mcpserver.exceptions import ToolError`.
- SymPy
- KaTeX para el render
- pytest

## Desarrollo y prueba local

- Máquina de desarrollo: Fedora. Claude Desktop no tiene versión oficial para Linux, así que la prueba local por **stdio** se hace con **Claude Code** (`claude mcp add step-by-step-math -- uv --directory <ruta-del-repo> run step-by-step-math`) y/o con **MCP Inspector** (`npx @modelcontextprotocol/inspector`) para llamar tools a mano y ver los JSON.
- Para probar desde claude.ai o ChatGPT antes de deployar: correr con transporte HTTP y exponer con `cloudflared tunnel`. Ambos solo aceptan servidores remotos por HTTPS.

## Deploy

- Fase 1: Railway (plan Hobby), con el `Dockerfile` del repo. Fase 2: homelab propio + Cloudflare Tunnel.
- Transporte por `STEP_BY_STEP_MATH_TRANSPORT`: `stdio` (default, Claude Code) o `http` (la imagen ya lo trae en `http`). En http: streamable HTTP **stateless + JSON**, `0.0.0.0:$PORT`, endpoint `/mcp/<token>`, `GET /health` sin token.
- **Autenticación = segmento secreto en la ruta** (`STEP_BY_STEP_MATH_PATH_TOKEN`, ≥ 32 caracteres URL-safe; sin él no arranca en http). La URL completa es el secreto. Motivo (verificado oct 2026): los conectores custom de claude.ai aceptan OAuth, sin auth y headers estáticos (estos en beta para pocas organizaciones); ChatGPT acepta OAuth o sin auth, sin campo de bearer. Ruta inválida → 404.
  - uvicorn corre con `access_log=False` para que el token no aparezca en los logs. No volver a activarlo sin redactar la ruta.
  - Siguiente paso de seguridad: OAuth (CIMD/DCR) cuando haga falta.
- `STEP_BY_STEP_MATH_MAX_CONCURRENT` (default 2) limita cuántos procesos hijo existen a la vez; si están todos ocupados durante `timeout` segundos → `ComputationBusy`.
- Memoria medida en el contenedor (python:3.14-slim): proceso principal ~110 MB RSS, forkserver ~110 MB, cada hijo ~130 MB de memoria virtual al calcular. El límite de 512 MB por hijo deja ~380 MB de margen. Límite de Railway recomendado: 1 GB.

## Roadmap

1. [x] Esqueleto MCPServer con `differentiate` andando en Claude Code
2. [x] `integrate` (automático) y `verify_antiderivative`, devolviendo texto
3. [ ] Definir `Step` y el motor de pasos para **partes** con `u` elegida por el usuario
4. [ ] Pizarrón HTML para partes
5. [ ] Sustitución y fracciones simples
6. [ ] Transporte HTTP y deploy a Railway; conectar a claude.ai y ChatGPT (código y Dockerfile listos; falta el deploy y conectar)
7. [ ] Pizarrón inline vía MCP Apps
8. [ ] Más dominios: límites, series y derivadas paso a paso (Análisis I); Álgebra (matrices, sistemas, determinantes); Análisis II (derivadas parciales, integrales múltiples); Lógica (tablas de verdad, deducción natural)

El nombre del proyecto es genérico a propósito: cada materia se suma como un motor nuevo que devuelve `list[Step]`, sin tocar el servidor ni el renderer. Organizar el código como `engines/<subject>/` (por ejemplo `engines/calculus/`, `engines/algebra/`, `engines/logic/`).

## Testing

- Cada regla con tests de ejercicios típicos de la guía de Análisis.
- Test de propiedad: para cada integral del set, `diff(resultado) == integrando`.
- Casos negativos: sustitución inválida, método que no aplica, expresión mal formada, timeout.
- Más adelante: evals del flujo completo (¿el modelo elige bien la tool y respeta el método pedido?).

## Convenciones

- **Todo el código en inglés**: nombres de archivos y módulos, identificadores, nombres de tools y parámetros, comentarios, docstrings, mensajes de error y tests (`integrate`, `Step`, `rule`, `engines/calculus/`). Lo único en español es lo que es input del usuario (alias como `sen`, `tg`, `ln`) y este CLAUDE.md.
- Funciones del motor puras: reciben expresiones SymPy y devuelven `list[Step]`, sin I/O. El servidor solo adapta.
- Nada de lógica matemática en el renderer: solo dibuja lo que recibe.

## Pendientes

- **Raíces cúbicas de negativos:** SymPy toma `x**(1/3)` como raíz principal (compleja si x < 0), así que una definida sobre negativos puede dar un valor complejo (hoy solo se avisa en `warnings`). Usar raíz real por defecto: parsear `cbrt(...)` y `x**(1/3)` (y en general `x**(p/q)` con q impar) como `real_root`, y revisar que `manualintegrate`, la verificación y `continuous_domain` sigan funcionando con esa forma.
- **Decimales exactos:** un límite como `1.5` da un resultado en coma flotante (`1.125000…`). Evaluar la transformación `rationalize` en el parseo para que `1.5` se tome como `3/2`.
