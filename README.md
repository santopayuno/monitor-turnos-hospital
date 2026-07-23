# 🏥 Monitor de Turnos — Hospital Alfredo I. Perrupato

Sistema gratuito y público que vigila la disponibilidad de turnos médicos del **Hospital Alfredo I. Perrupato** (San Martín, Mendoza) y avisa cuando aparecen.

**Dashboard en vivo:** [santopayuno.github.io/monitor-turnos-hospital](https://santopayuno.github.io/monitor-turnos-hospital)

**Datos en vivo:** [monitor-turnos-hospital-production.up.railway.app](https://monitor-turnos-hospital-production.up.railway.app)


Está pensado para gente que necesita un turno y no puede estar mirando la página del hospital todo el día. Muchos de sus usuarios son personas mayores o con poca práctica digital, así que **todo se resuelve del lado del sistema y se muestra simple.**

> 📖 **Los otros dos documentos:** `MANUAL_INSTALACION.md` (montar el sistema desde cero) y `MANUAL_RECUPERACION.md` (qué hacer cuando algo se rompe).

---

## ✨ Qué hace

- Consulta la página del hospital **cada 5 minutos**, las 24 horas
- Detecta turnos nuevos, reaperturas, aumentos, últimos cupos y agotamientos
- Distingue una **primera apertura** de una **reapertura** de algo que ya estuvo agotado
- Avisa por **Telegram** apenas aparece algo, y manda un resumen todas las mañanas
- Permite **encargar especialidades** desde el chat, para que avise solo de esas
- Publica un **dashboard web** con estado en vivo, buscador, gráficos y análisis histórico
- Predice **cuándo suele abrir** cada especialidad, mostrando el hecho crudo y no un porcentaje inventado
- Detecta si una especialidad **se está agotando rápido** ahora mismo
- Guarda un **resumen diario que no vence nunca**, para ver con los años cómo se comporta cada época
- **Se vigila a sí mismo:** si se apaga, avisa por Telegram y por mail
- Funciona como **app instalable** en el celular, incluso sin señal

---

## 🏗️ Cómo funciona

```
   API del hospital
          │  cada 5 minutos
          ▼
   ┌──────────────────┐
   │     RAILWAY      │  servicio prendido 24/7
   │                  │
   │  run_monitor.py  │──► corre monitor.py en loop
   │        +         │──► guarda los JSON en /data (volumen)
   │  servidor HTTP   │──► sirve esos JSON por internet (con gzip)
   └──────────────────┘
          │                        │
          │ Telegram               │ HTTP
          ▼                        ▼
      Teléfono              GitHub Pages
                            (index.html)
```

**Dos cosas separadas, y conviene tenerlo claro:**

| | Dónde vive | Qué pasa si se cae |
|---|---|---|
| **El código** | GitHub | Railway sigue corriendo con la última versión que bajó |
| **Los datos** | Volumen de Railway (`/data`) | El dashboard queda sin datos frescos |

El monitor **ya no sube datos a GitHub**. Antes lo hacía y eso chocaba con el límite de publicaciones de GitHub Pages (llegó a mandar ~288 avisos de error por día). Desde la migración, el repo solo guarda código.

---

## 🛠️ Tecnologías

| Componente | Tecnología |
|---|---|
| Monitor | Python 3.11 |
| Infraestructura | Railway (servicio 24/7, plan Hobby) |
| Persistencia | Volumen de Railway montado en `/data` |
| Entrega de datos | Servidor HTTP propio, con gzip y CORS |
| Notificaciones | Telegram Bot API |
| Dashboard | HTML + CSS + JavaScript puro (un solo archivo) |
| Gráficos | Chart.js |
| Publicación web | GitHub Pages |
| Contenedor | Docker (`python:3.11-slim`) |
| Chequeos | GitHub Actions (`test.yml`) |
| Vigilancia externa | Healthchecks.io |
| Analytics | Google Analytics 4 (`G-D2GTL7MRGH`) |

---

## 📁 Qué hay en el repositorio

**Código que corre:**

| Archivo | Qué hace |
|---|---|
| `monitor.py` | El cerebro: consulta la API, detecta cambios, calcula predicciones, arma y manda los mensajes de Telegram |
| `run_monitor.py` | El que Railway arranca: repite el ciclo cada 5 min, sirve los datos por HTTP y vigila que el monitor no se cuelgue |
| `index.html` | El dashboard completo (HTML, estilos y código en un solo archivo) |
| `sw.js` | Hace que el dashboard cargue rápido y funcione sin señal |
| `manifest.json`, `icon-192.svg`, `icon-512.svg` | Para instalarlo como app en el teléfono |
| `config.json` | Ajustes: especialidades de interés, reporte diario y su horario |
| `Dockerfile`, `requirements.txt` | Cómo se construye el servicio en Railway |
| `test.yml` | Verifica que el código no esté roto al subirlo |
| `.gitignore` | Qué archivos no se suben |

> ⚠️ **No hay ningún archivo de datos en el repo.** Viven todos en el volumen de Railway.

---

## 💾 Los datos (volumen `/data`)

| Archivo | Qué guarda | Si se pierde |
|---|---|---|
| `estado_turnos.json` | Cupos de cada especialidad ahora mismo | Se regenera en un ciclo |
| `estado_anterior.json` | El estado del ciclo anterior, para comparar | Se regenera en un ciclo |
| `estadisticas_db.json` | 180 días de historial: lecturas y eventos | **Se pierde el historial** |
| `heartbeat.json` | Cuándo corrió por última vez y avisos ya enviados | Se regenera |
| `historial_cupos.json` | Últimas 3 horas de cupos, para el "se agota rápido" | Se regenera en un rato |
| `predicciones.json` | Las frases predictivas ya cocinadas | Se regenera en un ciclo |
| `encargos.json` | **Tu lista de especialidades encargadas** | Se pierde la lista |
| `archivo_diario.json` | **Resumen de cada día, para siempre** | **No se recupera nunca** |

> ⚠️ **Los dos últimos son los delicados.** El `archivo_diario.json` es el único archivo del sistema que **no se puede regenerar**: guarda un resumen por día y especialidad que sobrevive aunque el detalle de 180 días se borre. Está pensado para que, con los años, se pueda ver cómo se comporta cada época del año. Tiene **una sola copia** y no hay respaldo automático — fue una decisión consciente, no un olvido.

---

## 📱 Qué llega por Telegram

| Mensaje | Cuándo |
|---|---|
| 🚨 **Nuevos turnos disponibles** | Apenas aparecen, reabren o suman cupos |
| 📌 **Encargo disponible** | Cuando aparece algo que anotaste vos |
| 🌅 **Resumen matutino** | Todos los días a las 8 |
| ⚠️ **Alerta** | Si el monitor se cuelga más de 30 minutos |
| ❌ **Error** | Si no puede conectarse con el hospital |

**Comandos del bot:**

| Comando | Qué hace |
|---|---|
| `/encargo`, `/agregar`, `/add` | Anotar una especialidad |
| `/sacar`, `/quitar`, `/borrar` | Sacarla de la lista |
| `/lista` | Ver lo que tenés anotado |
| `/estado` | Turnos disponibles ahora mismo |
| `?` o `/ayuda` | La lista de comandos |

> 💡 El sistema **solo avisa ante cambios reales.** Si en un ciclo no pasó nada, no manda nada. Es el contrato de confianza del proyecto.

---

## ⚙️ Variables de entorno (Railway → Variables)

| Variable | Para qué | Si falta |
|---|---|---|
| `BOT_TOKEN` | Token del bot de Telegram | No llega ningún mensaje |
| `CHAT_ID` | A qué chat mandar | No llega ningún mensaje |
| `GITHUB_TOKEN` | Bajar el código del repo al arrancar | No actualiza el código |
| `HEALTHCHECK_URL` | Ping al vigilante externo | El vigilante queda dormido, **sin avisar** |
| `DATA_DIR` | Dónde guardar los datos (por defecto `/data`) | Usa la carpeta local y **se pierde todo al redesplegar** |
| `PORT` | Puerto del servidor (lo inyecta Railway) | Usa 8080 |
| `CICLO_SEG` | Cada cuánto repetir (por defecto 300 = 5 min) | Usa 5 minutos |

---

## 🎨 Criterios de diseño

**La complejidad va detrás de bambalinas.** El sistema calcula niveles de confianza, ventanas de probabilidad y proyecciones, pero al usuario le muestra el hecho crudo: *"abrió 12 de las últimas 17 veces"*, no *"74% de probabilidad"*. Un número inventado genera falsa confianza; un hecho verificable, no.

**Cuando no hay datos, se dice.** El sistema muestra "No hay patrón claro todavía" antes que arriesgar una predicción con poca evidencia.

**Errar del lado barato.** El banner avisa temprano aunque a veces se adelante: que alguien mire de más cuesta poco, que pierda un turno cuesta mucho.

**Cada ícono significa una sola cosa**, en el dashboard y en Telegram:

| Ícono | Significado | Cupos |
|---|---|---|
| 🆕 | Nuevos | recién aparecieron |
| ☘️ | Disponibles | 20 o más |
| ⚠️ | Pocos | 6 a 19 |
| ‼️ | Últimos | 1 a 5 |
| ✖️ | Agotados | 0 |
| 🩺 | Una especialidad | — |

**Colores base** (definidos en `index.html`):

| Color | Código | Uso |
|---|---|---|
| 🔵 Azul | `#0369a1` | Nuevos, primario |
| 🟢 Verde | `#16a34a` | Disponibles |
| 🟡 Amarillo | `#eab308` | Pocos cupos |
| 🔴 Rojo | `#dc2626` | Últimos cupos |
| ⚪ Gris | `#64748b` | Agotados |

**Reglas de redacción** (para todo lo que ve el usuario):
- El `~` va con espacio: `~ 43`, no `~43`
- Las frases no terminan en punto
- `min.` y `hs.` llevan punto

---

## 🤝 Cómo se trabaja en este proyecto

Estas reglas vienen de todas las etapas y **no deberían romperse**:

1. **Español, en criollo.** Explicaciones cortas y claras, sin jerga
2. **Una recomendación clara**, no un menú de opciones. Si hay que elegir, se elige y se explica por qué
3. **Honestidad antes que falsa precisión.** Si algo no se sabe, se dice
4. **Verificar antes de afirmar.** Nunca responder de memoria sobre el código: leer el archivo, comprobarlo con datos reales
5. **Explicar antes de implementar.** Se propone, se autoriza, se implementa, se despliega
6. **Entregar archivos completos**, listos para subir. Nunca pedirle a Ariel que edite código a mano
7. **Cambios quirúrgicos.** Tocar solo lo pedido, nada más
8. **No tocar colores, íconos, textos ni disposición** sin autorización explícita
9. **Avisar antes de tocar lógica compartida**
10. **ChatGPT es auditor, no autoridad.** Cada sugerencia se verifica contra el código real
11. **No abrumar.** De a poco, priorizando

---

## 🔒 Invariantes — no tocar

Nacieron al principio del proyecto y siguen vivas por buenas razones:

- **Guardado atómico:** se escribe a un archivo temporal y recién ahí se reemplaza. Si el proceso se corta a mitad, el archivo no queda corrupto
- **Zona horaria de Mendoza** en todo lo que ve el usuario. La infraestructura corre en UTC; sin esto, las horas saldrían corridas
- **Doble lectura del JSON de la API:** el hospital manda un JSON adentro de otro. Hay que abrirlo dos veces
- **Reintentos HTTP:** la API del hospital falla seguido. Sin reintentos, aparecían errores que no eran reales
- **Normalización de nombres:** el diccionario `REEMPLAZOS_NOMBRES` limpia los nombres sucios que devuelve la API. Es el único lugar donde se hace
- **Validación defensiva:** nunca asumir que la API devuelve lo esperado
- **`index.html`,** no otro nombre: es lo que GitHub Pages sirve solo
- **No avisar sin cambio real.** Las dos excepciones (el resumen matutino y el banner predictivo) son deliberadas y acotadas

---

## 📐 Números que conviene conocer

| Dónde | Qué | Valor |
|---|---|---|
| Ciclo del monitor | Cada cuánto consulta | 5 minutos |
| Historial | Cuánto se guarda del detalle | 180 días |
| Archivo diario | Cuánto se guarda del resumen | para siempre |
| Semáforo del dashboard | Verde / amarillo / rojo | < 10 min / 10-20 / 20+ |
| Dashboard abierto | Cada cuánto refresca | 5 minutos |
| Banner predictivo | Ventana que evalúa | 90 minutos |
| Banner predictivo | Mínimo de casos y probabilidad | 8 casos, 50% |
| Banner predictivo | Deja de mostrar si no abre hace | 21 días |
| Vigilante interno | Avisa si no corre hace | 30 minutos |
| Historial de cupos | Cuánto conserva | 3 horas |
| Comandos de Telegram | Descarta los más viejos que | 1 hora |

---

## 🐛 Problemas comunes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Dashboard con el diseño viejo | GitHub Pages no publicó | Actions → *pages-build-deployment* → **Re-run jobs** |
| Dashboard sin datos, semáforo ❤️ | Railway no responde | Abrir `/health`; si no contesta, revisar Deployments |
| No llegan mensajes de Telegram | Token o chat mal configurados | Mandarle `?` al bot; revisar `BOT_TOKEN` y `CHAT_ID` |
| Llegó "⚠️ Monitor sin ejecutar" | El monitor se colgó | Railway → logs → **Redeploy** |
| Se perdió el historial al redesplegar | El volumen no está montado | Settings → Volumes → montar en `/data` |
| El monitor corre una sola vez | Comando de arranque equivocado | Debe ser `python run_monitor.py` |
| Logs vacíos aunque el servicio ande | Salida en buffer | Agregar variable `PYTHONUNBUFFERED = 1` |
| El dashboard tarda en cargar | Compresión desactivada | F12 → Red → `estadisticas_db.json` debe pesar ~50 KB |

> 📖 Cada uno de estos casos está desarrollado paso a paso en `MANUAL_RECUPERACION.md`.

---

## 🔍 Cómo verificar que algo no se rompió

```bash
# El código Python
python3 -m py_compile monitor.py run_monitor.py

# El código del dashboard
python3 -c "import re; html=open('index.html').read(); open('/tmp/a.js','w').write(max(re.findall(r'<script>(.*?)</script>',html,re.DOTALL),key=len))"
node --check /tmp/a.js

# El service worker
node --check sw.js
```

Y en vivo:
- `…railway.app/health` debe devolver **ok**
- `…railway.app/estado_turnos.json` debe mostrar los cupos actuales
- El semáforo del dashboard debe estar en 💚

---

## 🔮 Qué queda pendiente

**Ahora:** nada con trabajo por delante.

**A futuro:**

| Cuándo | Qué |
|---|---|
| ~Septiembre 2026 | Medir si el motor predictivo acierta: registro de aciertos, ajuste de recencia y comprobar que "confianza alta" realmente lo sea. Herramienta interna, no dato público |
| A los ~180 días de datos | Revisar los parámetros del motor predictivo, sobre todo la ventana de recencia y el umbral de "casi todos los días" |
| Con años de datos | Escribir el análisis por época del año. La materia prima ya se junta en `archivo_diario.json`; falta el análisis |

**Otras cosas que conviene saber:**
- El dashboard tiene **Google Analytics** (`G-D2GTL7MRGH`)
- `config.json` puede tener claves que ya no se leen (las de alertas de patrón y velocidad, que se sacaron de Telegram)
- Si el `estadisticas_db.json` sigue creciendo y el dashboard se pone lento, el siguiente paso es servirlo ya resumido: de su peso, más de la mitad son lecturas cada 5 minutos que el dashboard casi no usa en detalle

---

## 💵 Costo

Railway plan **Hobby: $5 al mes, con $5 de uso incluido**. El consumo real ronda **$0,25 al mes**, así que en la práctica no hay cargo extra. El servicio prendido 24/7 gasta mucho menos de lo estimado.

GitHub Pages, Telegram y Healthchecks.io son gratis para este uso.

---

*🏥 Monitor Automático de Turnos Hospitalarios*
*Hospital Alfredo I. Perrupato · San Martín, Mendoza*
