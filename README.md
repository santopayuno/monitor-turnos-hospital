# 🏥 Monitor de Turnos - Hospital Alfredo I. Perrupato

Monitor en tiempo real de disponibilidad de turnos hospitalarios con notificaciones automáticas por Telegram y dashboard analítico.

## ✨ Características

### 🎨 Dashboard Web
- **Badge LIVE** - Indicador visual de actividad en tiempo real
- **Countdown automático** - Muestra cuándo es el próximo chequeo (cada 5 minutos)
- **Buscador de especialidades** - Filtra especialidades en tiempo real
- **6 categorías visuales**:
  - 🆕 Nuevos cupos (azul)
  - ✅ Disponibles: ≥20 cupos (verde)
  - 🟡 Pocos: 5-19 cupos (amarillo)
  - ⚠️ Últimos: 1-4 cupos (rojo)
  - ❌ Agotados: 0 cupos (gris)
  - 📊 Análisis con gráficos

### 📊 Gráficos Analíticos
- **Actividad por hora** - Detecta cuándo abren más turnos
- **Últimas 24 horas** - Tendencias recientes en tiempo real
- **Top 10 especialidades activas** - Cuáles más se mueven
- **Top 10 especialidades agotadas** - Cuáles se agotan más rápido
- **4 métricas visuales** - Especialidad más activa, hora pico, promedio, menos disponible

### 🔔 Notificaciones Telegram
- Notifica ÚNICAMENTE cuando hay **nuevos cupos** o **aumentos importantes**
- NO notifica por bajadas, agotamientos o cambios menores
- Mensajes limpios y profesionales con separadores visuales

### 🤖 Automatización
- Monitorea API cada **5 minutos** automáticamente
- Ejecutado por **GitHub Actions** (sin servidor, gratis)
- Estadísticas históricas en JSON
- Respaldo automático de cambios

### 📱 Responsive
- Desktop, tablet y móvil optimizados
- Interfaz moderna y profesional
- Búsqueda funcional en todos los dispositivos

## 🚀 Inicio Rápido

### Requisitos
- Cuenta GitHub (gratis)
- Bot de Telegram (crear con @BotFather)
- Chat ID de Telegram (obtienes del bot)

### Instalación (14 pasos)

Ver **INSTRUCCIONES_PASO_A_PASO.txt** para guía completa con:
1. Crear repositorio GitHub
2. Preparar archivos localmente
3. Configurar GitHub Actions
4. Agregar Secrets (BOT_TOKEN, CHAT_ID)
5. Activar GitHub Pages
6. Verificar funcionamiento

### Comandos Básicos
```bash
# Crear repositorio local
git init
git add .
git commit -m "Monitor de Turnos - Initial commit"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/monitor-turnos-hospital
git push -u origin main
```

## 📁 Estructura del Proyecto

```
monitor-turnos-hospital/
├── .github/
│   └── workflows/
│       └── monitor.yml              # GitHub Actions workflow
├── logs/                             # Logs automáticos
│   └── .gitkeep
├── index.html                        # Dashboard web (Opción B)
├── monitor.py                        # Script de monitoreo Python
├── config.json                       # Configuración
├── estado_turnos.json                # Estado actual (auto)
├── estadisticas_db.json              # Estadísticas históricas (auto)
├── README.md                         # Este archivo
└── .gitignore                        # Archivos a ignorar
```

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
  "umbral_ultimos_cupos": 1
}
```

### GitHub Secrets
Ir a: Settings > Secrets and variables > Actions

**Secret 1: BOT_TOKEN**
- Obtener de @BotFather en Telegram

**Secret 2: CHAT_ID**
- Obtener enviando /start al bot creado

## 📊 Datos Generados

### estado_turnos.json
Almacena el estado actual de cupos por especialidad:
```json
{
  "Cardiología": 5,
  "Cirugía General": 23,
  "Dermatología": 0,
  ...
}
```

### estadisticas_db.json
Almacena eventos históricos y registros diarios:
```json
{
  "registros": { "2024-05-22": [...] },
  "eventos": [
    { "tipo": "nuevos", "especialidad": "...", "cupos": 5, ... }
  ]
}
```

## 🌐 Dashboard Público

Una vez activado GitHub Pages, tu dashboard estará en:
```
https://TU_USUARIO.github.io/monitor-turnos-hospital
```

## 🔍 Características del Dashboard

### Búsqueda
- Escribe en "🔍 Buscar especialidad..."
- Filtra en tiempo real todas las categorías
- No requiere Enter, trabaja mientras escribes

### Tabs Interactivos
- Click en cada categoría para ver especialidades
- Información instantánea del estado actual
- Contador de cupos por especialidad

### Badge LIVE
- Verde parpadeante indica monitor activo
- Actualización automática cada 5 minutos

### Countdown
- "Próximo chequeo: 5m, 4m, 3m..."
- Cuenta regresiva hasta próxima actualización

### Gráficos Interactivos
- Hover para ver valores exactos
- Exportable a imagen (botón derecho)
- Actualiza con nuevos datos

## 🔧 Troubleshooting

### Telegram no notifica
- Verificar BOT_TOKEN en Secrets (no vacío)
- Verificar CHAT_ID es número (sin @ ni símbolos)
- Borrar y recrear ambos Secrets
- Ejecutar workflow manualmente desde Actions

### Gráficos vacíos
- Normal si es primer día
- Esperar 10-15 minutos para que haya datos
- Revisar logs en Actions para errores

### GitHub Pages no muestra
- Ir a Settings > Pages
- Verificar: Branch "main", Folder "/ (root)"
- Esperar 2-3 minutos
- Hacer commit pequeño para forzar rebuild

### Workflow no corre automáticamente
- Verificar archivo: `.github/workflows/monitor.yml`
- Ir a Settings > Actions > General > Habilitado
- Ejecutar manualmente desde Actions tab

## 📈 Monitoreo

### Estadísticas Disponibles
- Total de especialidades
- Total de cupos disponibles
- Especialidades activas (con cupos)
- Cambios detectados por hora
- Top especialidades más activas
- Especialidades más escasas

### Logs
- Guardados automáticamente en `/logs`
- Consultables en GitHub Actions
- Útiles para debugging

## 🔐 Privacidad y Seguridad

- ✅ Datos públicos (turnos del hospital)
- ✅ Secrets seguros en GitHub (no expuestos)
- ✅ Sin almacenamiento en servidores externos
- ✅ JSON local como base de datos
- ✅ Repositorio público (GitHub Pages requirement)

## 📝 Licencia

Este proyecto es de código abierto. Úsalo libremente.

## 📞 Soporte

Si algo no funciona:

1. **Revisa los logs**: Settings > Actions > Ver workflow execution
2. **Verifica Secrets**: No estén vacíos
3. **Comprueba estructura**: .github/workflows/monitor.yml debe existir
4. **Intenta manualmente**: Run workflow desde Actions
5. **Espera 5 minutos**: Recarga el dashboard

## 🎯 Roadmap

- ✅ Monitor automático cada 5 minutos
- ✅ Notificaciones Telegram
- ✅ Dashboard web responsive
- ✅ Buscador de especialidades
- ✅ Gráficos analíticos
- ✅ Countdown visual
- ✅ Badge LIVE
- 🔄 Posibles: Email notifications, SMS, historial por especialidad

## 🙏 Créditos

Desarrollado para Hospital Alfredo I. Perrupato, Mendoza.
Tecnología: Python, JavaScript, GitHub Actions, GitHub Pages

---

**Última actualización**: Mayo 2024
**Versión**: 2.0 (Opción B - Buscador, Countdown, Badge LIVE)