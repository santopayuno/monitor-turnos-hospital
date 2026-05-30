# 🏥 Monitor de Turnos - Hospital Alfredo I. Perrupato

Monitor automático de disponibilidad de turnos médicos del Hospital Alfredo I. Perrupato (Mendoza) con notificaciones en tiempo real por Telegram.

**Dashboard en vivo:** [santopayuno.github.io/monitor-turnos-hospital](https://santopayuno.github.io/monitor-turnos-hospital)

---

## ✨ Características

- 🔄 **Monitoreo automático cada 15 minutos** - Sin intervención manual
- 📱 **Notificaciones Telegram instantáneas** - Solo cuando hay turnos nuevos o aumentos
- 📊 **Dashboard interactivo** - 40 especialidades, gráficos, búsqueda en tiempo real
- 💓 **Heartbeat en tiempo real** - Indicador visual del estado real de Railway (verde/naranja/rojo)
- 🌐 **Hosted en GitHub Pages** - Gratuito y confiable
- ⚡ **Arquitectura confiable** - Railway como único motor de ejecución
- 🔒 **Sin dependencias externas** - Solo Python, Git, y APIs públicas

---

## 🏗️ Arquitectura

```
Railway Cron (cada 15 min)
    ├─ 🏥 Consulta API Hospital
    ├─ 📱 Telegram (si hay turnos nuevos o aumentos)
    ├─ 💓 Actualiza heartbeat.json
    ├─ 📝 Actualiza estado_turnos.json y estadisticas_db.json
    └─ 📤 Git push a GitHub
         └─ 📄 GitHub Pages se actualiza automáticamente
```

### ¿Por qué esta arquitectura?

- **Railway Cron** es puntual cada 15 minutos (GitHub Cron tiene retrasos de horas)
- **Railway** envía el Telegram directamente, sin depender de GitHub Actions
- **GitHub Pages** se actualiza automáticamente al detectar el push de Railway
- **Telegram** notifica solo si hay cambios reales (sin spam)

---

## 📋 Requisitos

- Python 3.11+
- Git
- Cuenta Railway (gratuita)
- Token GitHub (permisos: repo)
- Token Telegram Bot
- Docker (para Railway)

---

## 🚀 Instalación

### 1. Clonar repositorio

```bash
git clone https://github.com/santopayuno/monitor-turnos-hospital.git
cd monitor-turnos-hospital
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

En Railway → Variables:

```
BOT_TOKEN       = tu_token_telegram_bot
CHAT_ID         = tu_chat_id_telegram
GITHUB_TOKEN    = tu_token_github (permisos: repo)
```

### 4. Ejecutar localmente (opcional)

```bash
python monitor.py
```

### 5. Deployar en Railway

```
1. Conectar repo GitHub en Railway
2. Agregar variables de entorno (ver arriba)
3. Configurar Cron Schedule: */15 * * * *
4. Comando: python run_monitor.py
```

---

## 📊 Datos Monitoreados

El sistema rastrea **40 especialidades médicas** incluyendo:

- Clínica Médica
- Pediatría
- Cardiología
- Traumatología
- Y 36 más...

**Información capturada por especialidad:**
- Cupos disponibles
- Cambios respecto al ciclo anterior
- Fecha y hora de actualización
- Estadísticas históricas (90 días)

---

## 🔧 Componentes

### `monitor.py`
Script principal que:
- Consulta API del hospital
- Parsea especialidades y cupos
- Detecta cambios (nuevos turnos, aumentos, agotados)
- Envía notificación Telegram si hay novedades
- Escribe `heartbeat.json` con timestamp de cada ejecución real
- Actualiza `estado_turnos.json` y `estadisticas_db.json`
- Limpia automáticamente registros con más de 90 días

### `run_monitor.py`
Wrapper para Railway que:
- Inicializa Git si es necesario (resuelve conflictos)
- Ejecuta `monitor.py`
- Hace git commit & push a GitHub (incluye `heartbeat.json`)

### `index.html`
Dashboard interactivo con:
- 40 especialidades en tiempo real
- Heartbeat con color semántico (🟢 < 20 min / 🟠 20-60 min / 🔴 > 60 min)
- Render optimizado: solo actualiza el DOM si los datos cambiaron
- Gráficos de tendencias y análisis histórico
- Buscador inteligente sin memory leaks
- Diseño responsive (mobile-friendly)

### `.github/workflows/monitor.yml`
GitHub Actions configurado solo con `workflow_dispatch`:
- No tiene cron propio (evita ejecuciones dobles con Railway)
- Disponible para ejecución manual desde GitHub si es necesario

### `Dockerfile`
Contenerización para Railway:
- Base: Python 3.11-slim
- Instala: Git + dependencias Python
- CMD: `python run_monitor.py`

---

## 📱 Notificaciones Telegram

El bot notifica **solo cuando hay turnos nuevos o aumentos**:

```
🚨 NUEVOS TURNOS DISPONIBLES
🏥 HOSPITAL PERRUPATO

────────────
🆕 CAMBIOS DETECTADOS
────────────
🏥 CLINICA MEDICA CONSULTA
🍀 71 Cupos Disponibles
📈 +71 nuevos

────────────
🟢 DISPONIBLES AHORA
────────────
🏥 CIRUGIA INFANTIL
✅ 30 Cupos

────────────
⚠️ POCOS CUPOS DISPONIBLES
────────────
🏥 ONCOLOGIA
⚠️ 1 Cupo

────────────
‼️ SIN CUPOS DISPONIBLES
────────────
🚫 CARDIOLOGIA ADULTO
🚫 CARDIOLOGIA INFANTIL

📊 ESTADÍSTICAS
• Monitoreadas: 40
• Con cupos: 15
• Total: 231

🕒 29/05 • 20:00 hs
```

---

## 🛠️ Modo Prueba

Para verificar que Telegram funciona sin esperar cambios reales:

1. En Railway → Variables → agregar `TEST_MODE = true`
2. Railway → Run now
3. Verificar que llega el mensaje en Telegram
4. Borrar la variable `TEST_MODE` para volver al modo normal

---

## 🔐 Seguridad

- ✅ Tokens guardados solo en Railway (variables de entorno)
- ✅ No se almacenan datos sensibles en el repositorio
- ✅ HTTPS en GitHub Pages
- ✅ API del hospital es pública
- ✅ Telegram Bot con permisos limitados

---

## 📊 Flujo de ejecución

```
⏰ Cada 15 minutos → Railway cron job
   ├─ 🏥 Consulta API hospital (40 especialidades)
   ├─ 🔍 Compara con estado anterior
   ├─ 📱 Telegram (solo si hay nuevos o aumentos)
   ├─ 💓 Escribe heartbeat.json
   ├─ 📝 Guarda estado actualizado
   └─ 📤 Git push → GitHub Pages se regenera

⏰ +15 min → Repite
... (indefinidamente)
```

---

## 🗂️ Estructura de archivos

```
├── monitor.py              # Script principal + lógica Telegram
├── run_monitor.py          # Wrapper Railway + git push
├── index.html              # Dashboard web
├── requirements.txt        # Dependencias Python
├── config.json             # Configuración
├── Dockerfile              # Imagen Docker para Railway
├── estado_turnos.json      # Estado actual de especialidades
├── estadisticas_db.json    # Histórico 90 días
├── heartbeat.json          # Timestamp de última ejecución real
├── .gitignore
└── .github/workflows/
    └── monitor.yml         # Solo workflow_dispatch (sin cron)
```

---

## ✅ Verificación

### En Railway (Cron Runs → View logs)

```
→ Consultando API...
✓ API: 40 especialidades recibidas
✓ Push exitoso a GitHub
🎉 EJECUCIÓN COMPLETADA
```

### En Dashboard

El heartbeat debe mostrar en verde con menos de 20 minutos desde la última ejecución.

---

## 🐛 Troubleshooting

### Telegram: No llegan notificaciones

- Verificar que `BOT_TOKEN` y `CHAT_ID` están cargados en Railway → Variables
- Usar modo prueba (`TEST_MODE=true`) para verificar conectividad
- Revisar logs de Railway → View logs

### Railway: Push falló

- Verificar que `GITHUB_TOKEN` tiene permisos `repo`
- Verificar que la rama `main` existe en GitHub

### Dashboard: Heartbeat en rojo

- Revisar Railway → Cron Runs para confirmar que el cron está activo
- Verificar que `heartbeat.json` existe en el repositorio

### Dashboard: Datos desactualizados

- Hard refresh: `Ctrl+Shift+R` (o `Cmd+Shift+R`)
- Verificar que Railway está ejecutando correctamente en Cron Runs

---

*Monitor del Hospital Alfredo I. Perrupato. Desplegado en Railway, dashboard en GitHub Pages, notificaciones vía Telegram. 100% automático.*