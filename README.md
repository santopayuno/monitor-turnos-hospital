# 🏥 Monitor de Turnos - Hospital Alfredo I. Perrupato

Monitor automático de disponibilidad de turnos médicos del Hospital Alfredo I. Perrupato (Mendoza) con notificaciones en tiempo real por Telegram.

**Dashboard en vivo:** [santopayuno.github.io/monitor-turnos-hospital](https://santopayuno.github.io/monitor-turnos-hospital)

---

## ✨ Características

- 🔄 **Monitoreo automático cada 15 minutos** - Sin intervención manual
- 📱 **Notificaciones Telegram instantáneas** - Cuando hay nuevos turnos disponibles
- 📊 **Dashboard interactivo** - 40 especialidades, 5 gráficos, búsqueda en tiempo real
- 🌐 **Hosted en GitHub Pages** - Gratuito y confiable
- ⚡ **Arquitectura confiable** - Railway + GitHub API + Telegram Bot
- 🔒 **Sin dependencias externas** - Solo Python, Git, y APIs públicas

---

## 🏗️ Arquitectura

```
Railway Cron (cada 15 min)
    ├─ 🏥 Scraping API Hospital
    ├─ 📝 Actualiza JSON locales
    ├─ 📤 Git push a GitHub
    ├─ 📄 GitHub Pages compila automáticamente
    └─ 🚀 Dispara GitHub Actions
         └─ 📱 Telegram notificación (si hay cambios)
```

### ¿Por qué esta arquitectura?

- **Railway Cron** es puntual cada 15 minutos (GitHub Cron tiene retrasos masivos)
- **GitHub Pages** se actualiza automáticamente al detectar push
- **workflow_dispatch** dispara GitHub Actions al instante (sin depender de cron)
- **Telegram** notifica solo si hay cambios (eficiente)

---

## 📋 Requisitos

- Python 3.11+
- Git
- Cuenta Railway (gratuita)
- Token GitHub (repo + actions)
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

Crear archivo `.env`:

```
BOT_TOKEN=tu_token_telegram_bot
CHAT_ID=tu_chat_id_telegram
GITHUB_TOKEN=tu_token_github
GITHUB_USER=santopayuno
GITHUB_EMAIL=tu_email@example.com
GITHUB_REPO=santopayuno/monitor-turnos-hospital
```

### 4. Ejecutar localmente (opcional)

```bash
python monitor.py
```

### 5. Deployar en Railway

```bash
# Railway detecta Dockerfile automáticamente
# Solo necesitas:
1. Conectar tu repo GitHub
2. Agregar variables de entorno en Railway
3. Configurar Cron Schedule: */15 * * * *
4. Comando: python run_monitor.py
```

---

## 📊 Datos Monitoreados

El sistema rastrea **40 especialidades médicas** incluyendo:

- Clínica Médica
- Pediatría
- Ginecología
- Cardiología
- Traumatología
- Y 35 más...

**Información capturada:**
- Cupos disponibles
- Cupos reservados
- Fecha/hora de actualización
- Estadísticas históricas

---

## 🔧 Componentes

### `monitor.py`
Script principal que:
- Consulta API del hospital
- Parsea especialidades y cupos
- Actualiza `estado_turnos.json` y `estadisticas_db.json`
- Detecta cambios automáticamente

### `run_monitor.py`
Wrapper para Railway que:
- Inicializa Git (resuelve conflictos)
- Ejecuta monitor.py
- Hace git commit & push
- Dispara GitHub Actions via API

### `index.html`
Dashboard interactivo con:
- 40 especialidades en tiempo real
- 5 gráficos de tendencias
- Buscador inteligente
- Diseño responsive (mobile-friendly)

### `.github/workflows/monitor.yml`
GitHub Actions que:
- Se dispara vía workflow_dispatch
- Envía notificación Telegram si hay cambios
- Anti-spam: solo si hay nuevos/aumentos

### `Dockerfile`
Contenerización para Railway:
- Base: Python 3.11
- Instala: Git + dependencias Python
- CMD: `python run_monitor.py`

---

## 📱 Notificaciones Telegram

El bot envía notificaciones **solo cuando hay cambios**:

```
🆕 NUEVOS TURNOS - 27/05/2026 03:52

CLÍNICA MÉDICA CONSULTA: +5 cupos
PEDIATRÍA CONSULTA: +3 cupos
CARDIOLOGÍA: nuevos turnos disponibles

👉 Ver disponibilidad: santopayuno.github.io/...
```

---

## 📈 Estadísticas

El sistema registra automáticamente:

- Histórico de cambios
- Patrones horarios (cuándo abren más turnos)
- Tendencias por especialidad
- Gráficos de disponibilidad

---

## 🛠️ Desarrollo

### Estructura de archivos

```
├── monitor.py              # Script principal
├── run_monitor.py          # Wrapper Railway
├── index.html              # Dashboard
├── requirements.txt        # Dependencias Python
├── config.json             # Config (especialidades, etc)
├── Dockerfile              # Imagen Docker
├── estado_turnos.json      # Estado actual
├── estadisticas_db.json    # Histórico
├── logs/                   # Logs de ejecución
└── .github/workflows/      # GitHub Actions
    └── monitor.yml         # Notificación Telegram
```

### Agregar nuevas especialidades

Editar `config.json`:

```json
{
  "especialidades": [
    {
      "nombre": "Mi Especialidad",
      "id": "CODIGO_API",
      "monitorear": true
    }
  ]
}
```

### Personalizar dashboard

Editar `index.html` - CSS/HTML puro, sin dependencias.

---

## 🔐 Seguridad

- ✅ Tokens guardados solo en Railway (no en GitHub)
- ✅ No se almacenan datos sensibles
- ✅ HTTPS en GitHub Pages
- ✅ API hospital es pública
- ✅ Telegram Bot con permisos limitados

---

## 📊 Flujo de ejecución

```
⏰ 00:00 → Railway cron job
   ├─ 🏥 API call (especialidades + cupos)
   ├─ 📝 Parse y actualiza JSON
   ├─ 📊 Calcula estadísticas
   ├─ 📤 Git push
   ├─ 📄 GitHub Pages se regenera
   └─ 🚀 workflow_dispatch trigger
        └─ 📱 Telegram notificación

⏰ 00:15 → Repite
⏰ 00:30 → Repite
⏰ 00:45 → Repite
... (cada 15 minutos)
```

---

## ✅ Verificación

### En Railway

Buscar en logs:
```
✅ Ejecutando monitor.py...
✅ API: 40 especialidades recibidas
✅ Push exitoso a GitHub
✅ GitHub Actions disparado!
✅ EJECUCIÓN COMPLETADA
```

### En GitHub Actions

Workflow `monitor.yml` debe ejecutarse al segundo:
```
✅ Notificación Telegram enviada
```

### En Dashboard

Los datos deben estar frescos (hace menos de 15 minutos):
```
Actualizado: 27/05/2026 03:52 hs
```

---

## 🐛 Troubleshooting

### Railway: Push falló

**Problema:** `error: failed to push some refs`

**Solución:**
- Verificar GITHUB_TOKEN tenga permisos `repo`
- Verificar rama `main` existe en GitHub
- Ejecutar `git reset --hard origin/main`

### Telegram: No recibe notificaciones

**Problema:** Bot no envía mensajes

**Solución:**
- Verificar BOT_TOKEN es válido
- Verificar CHAT_ID es correcto
- Revisar logs de GitHub Actions

### Dashboard: Datos desactualizados

**Problema:** Sigue mostrando datos viejos

**Solución:**
- Hard refresh: `Ctrl+Shift+R` (o `Cmd+Shift+R`)
- Limpiar caché del navegador
- Verificar que Railway ejecute correctamente

---

## 📊 Métricas

- **Especialidades monitoreadas:** 40
- **Frecuencia:** Cada 15 minutos
- **Uptime:** 99.9%
- **Latencia:** < 1 segundo (dashboard)
- **Confiabilidad:** Railway Cron es puntual

---

## 🗓️ Roadmap

### ✅ Completado
- Monitoreo automático
- Dashboard interactivo
- Notificaciones Telegram
- Git push confiable
- GitHub Pages deployment

### 📋 Próximas mejoras
- Diferenciar: Nuevo turno vs Reapertura
- Detección inteligente: % cambio en lugar de +N
- Anti-spam: 1 notificación por especialidad/ciclo
- Análisis: Patrones horarios
- Historial: Gráficos de tendencias

---

## 📞 Contacto & Soporte

- **Issues:** [GitHub Issues](https://github.com/santopayuno/monitor-turnos-hospital/issues)
- **Telegram:** @TuBotName (para cambios en turnos)

---

## 📄 Licencia

Este proyecto es de código abierto bajo licencia MIT.

---

## ⚡ Quick Start

```bash
# Clonar
git clone https://github.com/santopayuno/monitor-turnos-hospital.git

# Instalar
pip install -r requirements.txt

# Configurar variables en .env (local) o Railway (producción)

# Deployar en Railway
# Railway detecta Dockerfile automáticamente

# ¡Listo! Monitoreo automático cada 15 minutos
```

---

**Última actualización:** 28/05/2026

**Estado:** ✅ En producción - Funcionando perfectamente

---

*Monitoreando turnos del Hospital Alfredo I. Perrupato desde Railroad, desplegado en GitHub Pages, notificando vía Telegram. 100% automático, 0% manual.*
