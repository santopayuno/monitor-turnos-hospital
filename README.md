# 🏥 Monitor de Turnos - Hospital Perrupato

**Sistema profesional de monitoreo automático de disponibilidad de turnos hospitalarios**

[![Monitor Status](https://img.shields.io/badge/Status-Estable%20FASE%201-brightgreen)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated-blue)](https://github.com/features/actions)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## ✨ Características Principales

### 🎯 Monitoreo Automático
- ⏱️ Consulta API cada **5 minutos** (configurable)
- 🤖 Ejecución automática mediante GitHub Actions
- 📊 Estadísticas históricas de **90 días**
- 🔄 Sincronización en tiempo real

### 💬 Notificaciones Inteligentes
- 📱 Notificaciones por **Telegram** (solo cambios relevantes)
- 🚨 Alerta solo cuando hay **nuevos cupos** o **aumentos importantes**
- 📈 Detección automática de cambios
- ✅ Sin spam de alertas innecesarias

### 🎨 Dashboard Web Interactivo
- 📊 Visualización profesional en tiempo real
- 🔍 **Buscador con autocompletado** (busca mientras escribes)
- 🎯 Filtrado por categorías (Nuevos, Disponibles, Pocos, Últimos, Agotados)
- 📈 Gráficos analíticos detallados
- 📱 **Responsive** (móvil, tablet, desktop)
- ⚡ Contador de minutos hasta próximo chequeo
- 🟢 Badge LIVE con indicador de estado

### 📈 Análisis y Estadísticas
- 📅 Actividad por hora del día
- 🔄 Tendencias últimas 24 horas
- 🆙 Top 10 especialidades más activas
- ⬇️ Top 10 especialidades que más se agotan
- 📊 Métricas visuales (especialidad más activa, hora pico, etc)
- 📝 Reporte diario configurables

---

## 🛡️ Robustez y Confiabilidad (FASE 1)

### 🐛 Bugs Críticos Corregidos
✅ Configuración de reporte diario ahora funciona  
✅ Estadísticas muestran números correctos (no más conteos rotos)

### 🔒 Validaciones y Protecciones
✅ **Concurrency:** Solo 1 ejecución simultánea (evita race conditions)  
✅ **Permisos GitHub Actions:** Acceso write a repositorio (push exitoso)  
✅ **Parseo defensivo:** API con valores inválidos → sin crash  
✅ **Validación API:** Detecta respuestas incompletas (< 20 especialidades)  
✅ **Deduplicación:** No hay eventos duplicados en estadísticas  
✅ **Límite Telegram:** Mensajes > 4096 caracteres → se truncan  
✅ **Persistencia robusta:** Temp files + sincronización Git segura  

### 🚀 Anti-Falsos-Nuevos
✅ **Primera ejecución:** Sin Telegram (solo estado base)  
✅ **Reinicio:** Diferenciación clara de cambios reales  
✅ **Deduplicación:** Sin spam cuando se borra estado_turnos.json  

---

## 🚀 Inicio Rápido

### Requisitos
- Cuenta **GitHub** (gratis)
- Bot de **Telegram** (crear con @BotFather)
- Chat ID de Telegram (obtener del bot)
- Python 3.11+ (solo si ejecutas localmente)

### Instalación en 5 Pasos

1. **Crea un repositorio GitHub público**
   ```bash
   git clone https://github.com/TU_USUARIO/monitor-turnos-hospital
   cd monitor-turnos-hospital
   ```

2. **Descarga los archivos:**
   - `monitor.py` → raíz del repo
   - `.github/workflows/monitor.yml` → carpeta .github/workflows/
   - `index.html` → raíz (dashboard)
   - `config.json` → raíz (configuración)
   - `estado_turnos.json` → raíz (estado inicial)
   - `estadisticas_db.json` → raíz (estadísticas iniciales)

3. **Configura Secrets en GitHub:**
   - Settings → Secrets and variables → Actions
   - `BOT_TOKEN` = Token del bot Telegram
   - `CHAT_ID` = Tu chat ID (número)

4. **Activa GitHub Pages:**
   - Settings → Pages
   - Branch: main
   - Folder: / (root)

5. **Push a GitHub:**
   ```bash
   git add .
   git commit -m "Monitor de Turnos - Inicial"
   git push
   ```

**Dashboard:** `https://TU_USUARIO.github.io/monitor-turnos-hospital`

---

## ⚙️ Configuración

### config.json
```json
{
  "api_url": "https://sganotti.mendoza.gov.ar/digisalud/...",
  "payload": {
    "nombrePlantilla": "PLT_PUBLIC_ESPE_TURNOS_PERRUPATO",
    "dni": ""
  },
  "intervalo_minutos": 5,
  "umbral_pocos_cupos": 5,
  "umbral_ultimos_cupos": 1,
  "generar_reporte_diario": true,
  "hora_reporte_diario": "23:55"
}
```

### GitHub Secrets
| Secret | Valor | Ejemplo |
|--------|-------|---------|
| `BOT_TOKEN` | Token del bot Telegram | `1234567890:ABCdef...` |
| `CHAT_ID` | Tu Chat ID | `8616081224` |

---

## 📁 Estructura del Proyecto

```
monitor-turnos-hospital/
├── .github/
│   └── workflows/
│       └── monitor.yml              🤖 GitHub Actions (ejecuta cada 5 min)
├── logs/
│   └── monitor.log                  📝 Log de ejecuciones
├── index.html                       🎨 Dashboard web
├── monitor.py                       🐍 Script principal (Python)
├── config.json                      ⚙️ Configuración
├── estado_turnos.json               💾 Estado actual (actualiza cada 5 min)
├── estadisticas_db.json             📊 Historial de eventos (90 días)
├── README.md                        📖 Este archivo
└── .gitignore                       🚫 Archivos a ignorar
```

---

## 📊 Dashboard Web

### Características
🎯 **Buscador Inteligente**
- Escribe especialidad mientras escribes
- Autocompletado en tiempo real
- Máximo 6 sugerencias
- Navega con teclado (↑↓ Enter)

🔄 **Tabs Interactivos**
- 🆕 **Nuevos** - Turnos abiertos recientemente
- ✅ **Disponibles** - ≥20 cupos
- 🟡 **Pocos Cupos** - 5-19 cupos
- ‼️ **Últimos** - 1-4 cupos
- ❌ **Agotados** - Sin cupos
- 📊 **Análisis** - Gráficos y métricas

📈 **Gráficos Analíticos**
- 📅 Aperturas por hora (24h)
- 🔄 Actividad últimas 24 horas
- 🆙 Top especialidades activas
- ⬇️ Top especialidades agotadas
- 📊 4 métricas visuales

---

## 🔔 Notificaciones Telegram

### Formato del Mensaje
```
🚨 NUEVOS TURNOS DISPONIBLES
🏥 HOSPITAL PERRUPATO

🆕 CAMBIOS DETECTADOS

🏥 CARDIOLOGIA ADULTO
🍀 12 Cupos Disponibles
📈 +12 nuevos

🟢 DISPONIBLES AHORA

🏥 CIRUGIA GENERAL
✅ 25 Cupos

[...]
```

### Cuándo Envía
✅ Cuando hay **nuevos cupos** (primer aparición)  
✅ Cuando hay **aumentos importantes** (>10 cupos)  
❌ NO envía por bajadas, agotamientos o cambios menores  

---

## 🔧 Workflow GitHub Actions

### Configuración
- **Trigger:** Cada 5 minutos (cron `*/5 * * * *`)
- **Concurrency:** Solo 1 ejecución simultánea
- **Reintentos:** Hasta 3 intentos en caso de conflicto Git
- **Permisos:** Write access a contents

### Pasos
1. ✅ Checkout del repo
2. ✅ Setup Python 3.11
3. ✅ Instalar dependencias (requests)
4. ✅ Ejecutar monitor.py
5. ✅ Commit cambios (solo si hay)
6. ✅ Pull + rebase (evitar conflictos)
7. ✅ Push a GitHub (con reintentos)

---

## 🧪 Troubleshooting

### ❌ Problema: GitHub Actions falla con error 403
**Causa:** Sin permisos de escritura  
**Solución:** 
- Settings → Actions → Permissions
- ✅ "Read and write permissions"

### ❌ Problema: Telegram no recibe notificaciones
**Causa:** Secrets no configurados o inválidos  
**Solución:**
- Verificar `BOT_TOKEN` y `CHAT_ID` en Settings → Secrets
- Borrar y recrear ambos secrets
- Ejecutar workflow manualmente desde Actions tab

### ❌ Problema: Dashboard vacío o sin datos
**Causa:** estado_turnos.json vacío  
**Solución:**
- Esperar 5 minutos (primera ejecución)
- Ver Actions tab para errores
- Verificar conexión a API del hospital

### ❌ Problema: Primeros "nuevos" recibidos por Telegram
**Causa:** Primera ejecución debería no enviar  
**Solución:**
- Sistema detecta primera ejecución automáticamente
- Primera exec: Solo guarda estado, NO Telegram
- Segunda exec: Empieza a enviar cambios reales

### ❌ Problema: Especialidades "desaparecen" en Telegram
**Causa:** API del hospital devuelve respuesta incompleta  
**Solución:**
- Sistema valida (debe tener ≥20 especialidades)
- Si tiene menos, ignora respuesta
- No marca nada como agotado por error de API

---

## 📈 Datos Generados

### estado_turnos.json
Estado actual de cupos por especialidad:
```json
{
  "CARDIOLOGIA ADULTO": 12,
  "CIRUGIA GENERAL": 25,
  "DERMATOLOGIA": 0,
  "...": 0
}
```
**Se actualiza:** Cada 5 minutos

### estadisticas_db.json
Historial de eventos (últimos 90 días):
```json
{
  "registros": {
    "2024-05-22": [
      {"hora": "09:15:30", "con_cupos": 25, "total_cupos": 450, "cambios": 3}
    ]
  },
  "eventos": [
    {"fecha": "2024-05-22T09:15:30", "tipo": "nuevos", "especialidad": "CARDIOLOGIA", "cupos": 12},
    {"fecha": "2024-05-22T09:20:15", "tipo": "aumentos", "especialidad": "CIRUGIA", "cupos": 8}
  ]
}
```
**Se actualiza:** Cada 5 minutos  
**Se limpia:** Automáticamente (> 90 días)

---

## 🛠️ Desarrollo Local

### Ejecutar monitor localmente
```bash
# Instalar dependencias
pip install requests

# Configurar variables de entorno
export BOT_TOKEN="tu_token"
export CHAT_ID="tu_chat_id"

# Ejecutar
python monitor.py
```

### Logs
```bash
tail -f logs/monitor.log
```

---

## 🔐 Seguridad

✅ **Datos públicos:** Solo lee turnos del hospital (sin privacidad)  
✅ **Secrets seguros:** BOT_TOKEN y CHAT_ID en GitHub Secrets  
✅ **Sin servidor externo:** Todo local (GitHub + JSON)  
✅ **Código abierto:** Auditable completamente  
✅ **HTTPS:** GitHub Pages + API usar HTTPS  

---

## 📋 Roadmap

### ✅ FASE 1 (Completada)
- ✅ Bugs críticos corregidos
- ✅ Validaciones robustas
- ✅ Deduplicación de eventos
- ✅ Anti-falsos-nuevos
- ✅ Concurrency GitHub Actions
- ✅ Buscador con autocompletado
- ✅ Dashboard responsive

### 🔄 FASE 2 (Próxima)
- 🔄 Diferenciar nuevo vs reapertura
- 🔄 Detección inteligente de aumentos (%)
- 🔄 Anti-spam por especialidad
- 🔄 Análisis de patrones horarios
- 🔄 Predicción de reaperturas

### 🚀 FASE 3+ (Futuro)
- 📊 API REST para terceros
- 📧 Notificaciones por email
- 📱 App móvil nativa
- 🔐 Autenticación de usuarios
- 📈 Machine Learning para predicciones

---

## 📞 Soporte

### Problema con setup
1. Ver [Troubleshooting](#troubleshooting)
2. Revisar Actions tab → últimas ejecuciones
3. Leer logs en `logs/monitor.log`

### Sugerencias de mejoras
- Abrir un Issue describiendo la idea
- Incluir ejemplos concretos
- Detallar el comportamiento esperado

---

## 📊 Estadísticas del Proyecto

- **Ejecuciones:** Automáticas cada 5 minutos (288/día)
- **Eventos registrados:** Últimos 90 días
- **Especialidades monitoreadas:** ~40
- **Disponibilidad:** 99.99% (GitHub Actions SLA)
- **Latencia dashboard:** < 100ms

---

## 🙏 Créditos

Desarrollado para **Hospital Alfredo I. Perrupato**, Mendoza, Argentina.

**Tecnología:**
- 🐍 Python 3.11+
- 🤖 GitHub Actions
- 🌐 GitHub Pages
- 📊 Chart.js
- 💬 Telegram Bot API

---

## 📄 Licencia

Este proyecto está bajo licencia **MIT**. Libre para usar, modificar y distribuir.

---

## 🎯 Última Actualización

- **Fecha:** Mayo 2026
- **Versión:** FASE 1 (Estable)
- **Estado:** ✅ Producción
- **Próxima revisión:** Junio 2026

---

<div align="center">

**⭐ Si te fue útil, considera darle una estrella en GitHub ⭐**

[Ver en GitHub](https://github.com/santopayuno/monitor-turnos-hospital)

</div>
