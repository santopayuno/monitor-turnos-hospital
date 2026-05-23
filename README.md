🏥 Monitor de Turnos Hospital Perrupato

Sistema automático de monitoreo de turnos médicos del Hospital Perrupato con alertas en Telegram, estadísticas y dashboard web en tiempo real.

---

✨ Características

✅ Monitoreo automático de especialidades
✅ Alertas instantáneas por Telegram
✅ Dashboard web en GitHub Pages
✅ Detección inteligente de nuevos turnos
✅ Persistencia de estado entre ejecuciones
✅ Protección contra falsos positivos
✅ Validación defensiva de API
✅ Historial y estadísticas
✅ Logs automáticos
✅ Compatible con GitHub Actions

---

📲 Funcionalidades

🔔 Alertas Telegram

El sistema detecta automáticamente:

- 🆕 Nuevos turnos
- 📈 Aumentos de cupos
- ❌ Especialidades agotadas
- 🔄 Cambios importantes

---

📊 Dashboard Web

Visualización en tiempo real de:

- Especialidades disponibles
- Cantidad de cupos
- Estadísticas históricas
- Últimas actualizaciones
- Estado general del sistema

---

⚙️ Tecnologías

- 🐍 Python 3.11
- ⚡ GitHub Actions
- 🌐 GitHub Pages
- 📡 API Digisalud
- 🤖 Telegram Bot API
- 📈 JSON Stats Engine

---

🚀 Funcionamiento

El monitor:

1. Consulta automáticamente la API del hospital
2. Analiza cambios respecto al estado anterior
3. Detecta nuevos turnos y modificaciones
4. Envía alertas por Telegram
5. Actualiza estadísticas
6. Publica el dashboard automáticamente

---

🛡️ Mejoras de Robustez Implementadas

✅ Anti-Spam

- Evita alertas duplicadas
- Control de primera ejecución
- Persistencia segura de estado

✅ Validación de API

- Detecta respuestas incompletas
- Evita falsos “agotados”
- Parseo defensivo de datos

✅ Estabilidad

- Protección contra corrupción de JSON
- Manejo seguro de errores
- Reintentos automáticos
- Compatibilidad total con GitHub Actions

---

📂 Archivos Principales

Archivo| Función
"monitor.py"| Motor principal del sistema
"estado_turnos.json"| Estado persistente
"estadisticas_db.json"| Historial y estadísticas
"index.html"| Dashboard web
".github/workflows/"| Automatizaciones

---

📸 Dashboard

🌐 Sitio en vivo:

👉 https://santopayuno.github.io/monitor-turnos-hospital/

---

🔧 Configuración

Variables necesarias:

- "TELEGRAM_TOKEN"
- "TELEGRAM_CHAT_ID"

Configuradas en:

"GitHub → Settings → Secrets and variables → Actions"

---

📈 Estado Actual

🟢 Sistema operativo
🟢 Monitoreo activo
🟢 Persistencia funcional
🟢 Dashboard online
🟢 Alertas funcionando

---

💡 Objetivo

Este proyecto busca automatizar la detección de turnos médicos disponibles para mejorar velocidad de acceso, monitoreo y seguimiento en tiempo real.

---

⚠️ Aviso

Proyecto independiente y experimental.
No afiliado oficialmente al Hospital Perrupato ni al sistema Digisalud.

---

👨‍💻 Autor
Desarrollado y mantenido por Ariel.
🚀 Proyecto en evolución constante.