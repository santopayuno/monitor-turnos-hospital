# 🏥 Monitor de Turnos — Hospital Alfredo I. Perrupato

Sistema automático de monitoreo de disponibilidad de turnos médicos del Hospital Alfredo I. Perrupato (San Martín, Mendoza). Detecta cambios en tiempo real, notifica por Telegram y publica un dashboard analítico en la web.

**Dashboard en vivo:** [santopayuno.github.io/monitor-turnos-hospital](https://santopayuno.github.io/monitor-turnos-hospital)

---

## ✨ Qué hace el sistema

- **Monitorea automáticamente cada 15 minutos** las 40 especialidades médicas del hospital
- **Notifica por Telegram** cuando aparecen turnos nuevos, reaperturas o aumentos significativos
- **Detecta patrones de apertura** y avisa cuando una especialidad suele abrir en la próxima hora
- **Publica un dashboard web** con disponibilidad en tiempo real, gráficos históricos y rankings
- **Monitorea su propio estado**: si el sistema deja de ejecutarse, envía una alerta por Telegram
- **Funciona como PWA**: se puede instalar en el celular como una app

---

## 🏗️ Arquitectura

```
Railway Cron (cada 15 min)
    ├─ 🔍 Watchdog: verifica que el ciclo anterior fue exitoso
    ├─ 🏥 Consulta API pública del hospital
    ├─ 🔄 Compara con estado anterior
    ├─ 📱 Telegram: notifica si hay cambios relevantes
    ├─ 🔮 Detecta patrones de apertura para la próxima hora
    ├─ 📊 Actualiza estadísticas históricas
    ├─ 💓 Escribe heartbeat.json con timestamp real
    └─ 📤 Git push a GitHub
         └─ 📄 GitHub Pages publica el dashboard automáticamente
```

### ¿Por qué Railway y no GitHub Actions?

GitHub Actions tiene un cron poco confiable en cuentas gratuitas — puede retrasarse horas. Railway ejecuta el cron cada 15 minutos de forma puntual. GitHub Actions se mantiene solo con `workflow_dispatch` para ejecución manual.

---

## 🛠️ Tecnologías

| Componente | Tecnología |
|---|---|
| Motor de monitoreo | Python 3.11 |
| Scheduler | Railway Cron (`*/15 * * * *`) |
| Notificaciones | Telegram Bot API |
| Persistencia de datos | JSON en GitHub repo |
| Dashboard web | HTML + CSS + JavaScript |
| Gráficos | Chart.js 3.9 |
| Deploy web | GitHub Pages |
| Contenedores | Docker (Python 3.11-slim) |
| Tests automáticos | GitHub Actions |
| Logs estructurados | JSON Lines con RotatingFileHandler |

---

## 📱 Notificaciones Telegram

El bot envía mensajes **solo cuando hay cambios relevantes**. Nunca spam.

### Tipos de notificación

**🆕 Nuevos turnos** — cuando una especialidad pasa de 0 a tener cupos por primera vez en el historial:
```
────────────
🆕 CAMBIOS DETECTADOS
────────────
🏥 CLINICA MEDICA CONSULTA
🍀 71 Cupos Disponibles
📈 +71 nuevos
```

**🔄 Reaperturas** — cuando una especialidad que ya estuvo agotada vuelve a abrir:
```
────────────
🔄 REAPERTURAS
────────────
🏥 NEUROLOGIA NUEVO (CON DERIVACIÓN)
🍀 6 Cupos Disponibles
⚡ Reabre · agotada 4x antes
```

**🚨 Últimos cupos** — alerta urgente separada cuando quedan 1-4 cupos:
```
🚨 ÚLTIMOS CUPOS — URGENTE
🏥 HOSPITAL PERRUPATO

⚠️ TRAUMATOLOGIA INFANTIL
   Solo 1 cupo disponible
```

**🔮 Patrón detectado** — aviso preventivo cuando una especialidad suele abrir en la próxima hora (mínimo 5 aperturas históricas en 3 días distintos):
```
🔮 PATRÓN DETECTADO
📌 CLINICA MEDICA CONSULTA (8x histórico)
Suelen abrir a las 09:00 · basado en historial
```

**🌅 Resumen matutino** — cada día a las 08:00, estado general con disponibles, aperturas del día anterior y estadísticas de actividad.

**⚠️ Alerta de caída** — si el sistema no ejecutó en más de 30 minutos:
```
⚠️ ALERTA: Monitor sin ejecutar
La última ejecución exitosa fue hace 45 min.
```

Cada notificación incluye al final:
```
👉 https://sganotti.mendoza.gov.ar/...
```

---

## 📊 Dashboard Web

Accesible en [santopayuno.github.io/monitor-turnos-hospital](https://santopayuno.github.io/monitor-turnos-hospital)

### Header
- **Heartbeat en tiempo real**: 🍀 verde (<20 min) / ⚠️ naranja (20-60 min) / ❌ rojo (>60 min)
- Muestra "Actualizado hace X m · próxima en X m" basado en ejecución real de Railway
- Badge **LIVE** animado

### Pestañas de disponibilidad

| Pestaña | Contenido |
|---|---|
| 🆕 Nuevos | Turnos abiertos en los últimos 30-60 minutos |
| ✅ Disponibles | Todas las especialidades con cupos ahora |
| 🟡 Pocos Cupos | Especialidades con 1-19 cupos |
| ‼️ Últimos | Especialidades con 1-4 cupos (urgente) |
| ❌ Agotados | Sin cupos disponibles |
| 📊 Análisis | Gráficos y rankings históricos |

### Filtros rápidos
- **Disponibles**: `Todos` · `< 5` · `< 20` · `< 50`
- **Pocos Cupos**: `Todos` · `< 5` · `< 10`

### Indicadores en tarjetas
- **↑ verde / ↓ rojo**: tendencia respecto al ciclo anterior
- **⚡ se agota en ~X min**: velocidad histórica de agotamiento
- **Banner de patrón**: aparece cuando una especialidad suele abrir en la próxima hora

### Modal por especialidad (toque en cualquier tarjeta)
- 5 métricas: cupos ahora, récord histórico, aperturas, agotamientos, tiempo promedio hasta agotarse
- Gráfico de evolución histórica
- Tabla scrolleable con hasta 50 eventos (fecha, hora, cupos, tipo)

### Gestos
- **Toque corto** → abre modal con historial
- **Toque largo** → copia link directo a esa especialidad

### Pestaña Análisis

**KPIs:** Especialidad más activa, hora pico, promedio de cupos, especialidad menos disponible.

**Rankings (tarjetas visuales):**
- 🆙 Especialidades que Más Abren Turnos (Top 10 con medallas y barra de progreso)
- ⬇️ Especialidades que Más Rápido se Agotan (con badge de demanda)
- 🔥 Especialidades Más Dinámicas (con desglose aperturas/cierres)

**Gráficos:**
- 🕐 Actividad por Franja Horaria (aperturas vs cierres en bloques de 3h)
- 📊 Aperturas vs Cierres por Hora
- 📈 Evolución Histórica (total de cupos + especialidades activas)
- 📅 Aperturas por Día de la Semana

---

## 🔧 Componentes del sistema

### `monitor.py`
Script principal. En cada ejecución:
1. Lee configuración de `config.json`
2. Verifica watchdog (alerta si el ciclo anterior falló)
3. Consulta la API del hospital (3 reintentos automáticos con 10s de espera)
4. Compara con `estado_anterior.json`
5. Clasifica cambios: nuevos, reaperturas, aumentos, últimos, agotados
6. Envía notificaciones Telegram según corresponda
7. Detecta patrones de apertura para la próxima hora
8. Actualiza `estado_turnos.json`, `estado_anterior.json`, `estadisticas_db.json`, `heartbeat.json`
9. Escribe logs estructurados en `logs/monitor_structured.jsonl`
10. Genera reporte matutino a las 08:00

### `run_monitor.py`
Wrapper para Railway:
- Inicializa Git si es necesario
- Ejecuta `monitor.py`
- Hace `git commit` y `git push` con todos los JSON actualizados

### `index.html`
Dashboard web (HTML + CSS + JS puro, sin frameworks):
- Carga `estado_turnos.json`, `estado_anterior.json`, `estadisticas_db.json`, `heartbeat.json`
- Render optimizado: solo actualiza el DOM si los datos cambiaron (comparación por hash)
- Service Worker para soporte offline
- Notificaciones push nativas del navegador cuando hay nuevos turnos

### `.github/workflows/monitor.yml`
Solo `workflow_dispatch` — permite ejecución manual desde GitHub. Sin cron propio para evitar ejecuciones dobles con Railway.

### `.github/workflows/test.yml`
Tests automáticos en cada push a `monitor.py`. Verifica sintaxis, imports, lógica de procesamiento y formato del heartbeat.

---

## 📁 Estructura de archivos

```
├── monitor.py                  # Script principal
├── run_monitor.py              # Wrapper Railway + git push
├── index.html                  # Dashboard web
├── sw.js                       # Service Worker (PWA offline)
├── manifest.json               # PWA manifest
├── icon-192.svg                # Ícono app (192px)
├── icon-512.svg                # Ícono app (512px)
├── requirements.txt            # requests, PyYAML
├── Dockerfile                  # Python 3.11-slim
├── config.json                 # Configuración del sistema
├── estado_turnos.json          # Estado actual (40 especialidades)
├── estado_anterior.json        # Estado del ciclo anterior
├── estadisticas_db.json        # Historial 90 días
├── heartbeat.json              # Timestamp última ejecución real
├── logs/
│   ├── monitor.log             # Log de texto (Railway)
│   └── monitor_structured.jsonl # Log estructurado JSON Lines
└── .github/workflows/
    ├── monitor.yml             # workflow_dispatch manual
    └── test.yml                # Tests automáticos
```

---

## ⚙️ Configuración (`config.json`)

```json
{
  "especialidades_interes": [],
  "generar_reporte_diario": true,
  "hora_reporte_diario": "08:00",
  "alertas_patrones": true
}
```

| Campo | Descripción |
|---|---|
| `especialidades_interes` | Lista de especialidades para filtrar Telegram. Vacío = notifica todas |
| `generar_reporte_diario` | Activa el resumen matutino |
| `hora_reporte_diario` | Hora del resumen (formato HH:MM) |
| `alertas_patrones` | Activa/desactiva las alertas de patrón de apertura |

---

## 🚀 Instalación

### Variables de entorno en Railway

```
BOT_TOKEN      = token del bot de Telegram
CHAT_ID        = ID del chat donde llegan las notificaciones
GITHUB_TOKEN   = token con permisos repo
```

### Cron en Railway
```
*/15 * * * *
```

### Comando
```
python run_monitor.py
```

---

## 🛠️ Modo prueba

Para verificar que Telegram funciona sin esperar cambios reales:

1. Railway → Variables → agregar `TEST_MODE = true`
2. Railway → **Run now**
3. Verificar mensaje en Telegram
4. Borrar la variable `TEST_MODE`

---

## 🔐 Seguridad

- Tokens guardados únicamente en Railway como variables de entorno
- No se almacenan datos sensibles en el repositorio
- API del hospital es pública
- GitHub Pages sirve solo archivos estáticos vía HTTPS

---

## 🐛 Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| Heartbeat rojo en dashboard | Railway no ejecutó | Revisar Railway → Cron Runs |
| No llegan notificaciones Telegram | Token/Chat ID incorrecto | Verificar variables en Railway, usar TEST_MODE |
| Dashboard muestra datos viejos | Caché del navegador | Hard refresh: `Ctrl+Shift+R` |
| Push falló en logs | GITHUB_TOKEN sin permisos | Verificar permisos `repo` en el token |
| Test automático falla | Error en monitor.py | Revisar GitHub Actions → Tests Automáticos |

---

*Monitor del Hospital Alfredo I. Perrupato · Railway + GitHub Pages + Telegram · 100% automático*
