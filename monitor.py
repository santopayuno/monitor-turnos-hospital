"""
🏥 MONITOR DE TURNOS - HOSPITAL PERRUPATO
Sistema profesional de monitoreo automático

Características:
- Consulta API cada 15 minutos
- Notificaciones inteligentes en Telegram
- Estadísticas históricas (90 días)
- Dashboard web interactivo
- Diseño profesional y moderno
- Todos los cambios estéticos finales
"""

import requests
import os
import time
import json
import logging
import tempfile
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
HEALTHCHECKS_URL = os.environ.get("HEALTHCHECK_URL", "")

# Debug: Verificar que se reciben los valores
if not BOT_TOKEN:
    print("⚠️ ADVERTENCIA: BOT_TOKEN no configurado", file=sys.stderr)
if not CHAT_ID:
    print("⚠️ ADVERTENCIA: CHAT_ID no configurado", file=sys.stderr)

API_URL = "https://sganotti.mendoza.gov.ar/digisalud/WebServices/WebServiciosNotti.asmx/GetEntornoTurnosPublicosParticular"

ARCHIVOS = {
    "estado": "estado_turnos.json",
    "estadisticas": "estadisticas_db.json",
    "config": "config.json",
    "logs": "monitor.log",
    "reporte": "reporte_diario.txt",
    "heartbeat": "heartbeat.json",
    "estado_anterior": "estado_anterior.json",
    "historial": "historial_cupos.json"
}

# Cuántas lecturas recientes de cupos guardar por especialidad (8 ≈ 2 horas).
# El dashboard usa estas lecturas para estimar la velocidad de agotamiento reciente.
MAX_LECTURAS_HISTORIAL = 8

REEMPLAZOS_NOMBRES = {
    "DIABETOLOGIA GENERAL(CON DERIVACIÓN)": "DIABETOLOGIA GENERAL",
    "HEMATOLOGIA CLINICA ( CON DERIVACION )": "HEMATOLOGIA CLINICA",
    "CIRUGIA TORACICA (CON DERIVACION)": "CIRUGIA TORACICA",
    "NEFROLOGIA (CON DERIVACION)": "NEFROLOGIA",
}

CLASIFICACION_CUPOS = {
    "disponible": lambda c: c >= 20,
    "pocos": lambda c: 5 <= c < 20,
    "ultimos": lambda c: 1 <= c < 5,
    "agotado": lambda c: c == 0
}

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler(ARCHIVOS["logs"], encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class StructuredLogger:
    """Escribe eventos clave en formato JSON Lines usando RotatingFileHandler nativo."""

    LOG_PATH = "logs/monitor_structured.jsonl"

    def __init__(self):
        os.makedirs("logs", exist_ok=True)
        self._logger = logging.getLogger("StructuredLogger")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            from logging.handlers import RotatingFileHandler
            handler = RotatingFileHandler(
                self.LOG_PATH,
                maxBytes=1024 * 1024,  # 1MB por archivo
                backupCount=3,
                encoding="utf-8"
            )
            self._logger.addHandler(handler)

    def _escribir(self, evento: dict):
        try:
            evento["ts"] = datetime.now().isoformat()
            self._logger.info(json.dumps(evento, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"StructuredLogger error: {e}")

    def ejecucion(self, estado: str, especialidades: int, cupos: int, con_cupos: int):
        self._escribir({
            "evento": "ejecucion", "estado": estado,
            "especialidades": especialidades, "cupos_total": cupos, "con_cupos": con_cupos
        })

    def cambio(self, tipo: str, especialidad: str, cupos: int):
        self._escribir({"evento": "cambio", "tipo": tipo, "especialidad": especialidad, "cupos": cupos})

    def telegram(self, tipo: str, exito: bool, detalle: str = ""):
        self._escribir({"evento": "telegram", "tipo": tipo, "exito": exito, "detalle": detalle})

    def error(self, contexto: str, mensaje: str):
        self._escribir({"evento": "error", "contexto": contexto, "mensaje": mensaje})

slog = StructuredLogger()

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

def cargar_config():
    if os.path.exists(ARCHIVOS["config"]):
        try:
            with open(ARCHIVOS["config"], "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Config corrompido, usando defaults")
    return {"especialidades_interes": [], "generar_reporte_diario": True}

CONFIG = cargar_config()

# ═══════════════════════════════════════════════════════════════
# UTILIDADES DE RED
# ═══════════════════════════════════════════════════════════════

def crear_sesion_reintentos():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ═══════════════════════════════════════════════════════════════
# PERSISTENCIA
# ═══════════════════════════════════════════════════════════════

def cargar_json(archivo):
    if not os.path.exists(archivo):
        return None
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error leyendo {archivo}: {e}")
        return None

def guardar_json_seguro(datos, archivo):
    try:
        directorio = os.path.dirname(archivo) or "."
        with tempfile.NamedTemporaryFile(
            mode='w', dir=directorio, delete=False,
            encoding='utf-8', suffix='.json'
        ) as tmp:
            json.dump(datos, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, archivo)
    except Exception as e:
        logger.error(f"Error guardando {archivo}: {e}")

def guardar_historial_cupos(estado_actual, ahora):
    """Agrega la lectura actual de cupos por especialidad al historial reciente.

    Guarda, por cada especialidad, las últimas MAX_LECTURAS_HISTORIAL lecturas
    como {"t": <timestamp ISO>, "c": <cupos>}. No toca eventos ni estadísticas:
    es solo dato crudo para que el dashboard estime la velocidad reciente de
    agotamiento. Patrón seguro: leer, agregar, recortar, guardar.
    """
    try:
        historial_previo = cargar_json(ARCHIVOS["historial"]) or {}
        ts = ahora.isoformat()
        historial = {}
        for nombre, cupos in estado_actual.items():
            lecturas = historial_previo.get(nombre, [])
            lecturas.append({"t": ts, "c": int(cupos)})
            # conservar solo las lecturas más recientes
            historial[nombre] = lecturas[-MAX_LECTURAS_HISTORIAL:]
        guardar_json_seguro(historial, ARCHIVOS["historial"])
    except Exception as e:
        logger.error(f"Error actualizando historial de cupos: {e}")

def ping_healthchecks(suffix=""):
    """Envía la señal de vida a Healthchecks.

    suffix="/start" al iniciar, "" (vacío) al terminar bien, "/fail" si hubo error.
    Escribe en el log qué hace, para poder diagnosticar. Si no hay URL configurada
    (HEALTHCHECKS_URL), lo avisa y no hace nada. Nunca interrumpe el monitor.
    """
    etiqueta = suffix or "éxito"
    if not HEALTHCHECKS_URL:
        print(f"📡 Healthchecks: HEALTHCHECKS_URL está VACÍA, no se envía señal ({etiqueta})")
        return
    url = HEALTHCHECKS_URL.rstrip("/") + suffix
    try:
        import urllib.request
        urllib.request.urlopen(url, timeout=10)
        print(f"📡 Healthchecks OK ({etiqueta}) -> {url}")
    except Exception as e:
        print(f"⚠️ Healthchecks ERROR ({etiqueta}) -> {url} : {e}")

# ═══════════════════════════════════════════════════════════════
# UTILIDADES DE FORMATO
# ═══════════════════════════════════════════════════════════════

def formato_cupos_disponibles(cupo):
    """Formatea: X Cupo(s) Disponible(s)"""
    if cupo == 1:
        return f"1 Cupo Disponible"
    else:
        return f"{cupo} Cupos Disponibles"

# ═══════════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════════

# Sesión HTTP compartida para reutilización entre reintentos
_sesion_http = None

def _get_sesion():
    global _sesion_http
    if _sesion_http is None:
        _sesion_http = crear_sesion_reintentos()
    return _sesion_http

def _consultar_api_una_vez():
    """Intento único de consulta a la API. Lanza excepción si falla."""
    response = _get_sesion().post(
        API_URL,
        json={"nombrePlantilla": "PLT_PUBLIC_ESPE_TURNOS_PERRUPATO", "dni": ""},
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30
    )
    response.raise_for_status()

    data = response.json()
    if not data.get("d"):
        raise ValueError("Campo 'd' vacío en respuesta")

    especialidades = json.loads(data["d"])
    if not isinstance(especialidades, list):
        raise ValueError("Respuesta no es lista válida")

    if len(especialidades) < 20:
        raise ValueError(f"API devolvió solo {len(especialidades)} especialidades (esperaba ~30+)")

    return especialidades


def consultar_api(max_intentos=3, espera_segundos=10):
    logger.info("→ Consultando API...")
    ultimo_error = None

    for intento in range(1, max_intentos + 1):
        try:
            especialidades = _consultar_api_una_vez()
            logger.info(f"✓ API: {len(especialidades)} especialidades recibidas")
            return especialidades
        except requests.RequestException as e:
            ultimo_error = f"Error de red: {e}"
        except (json.JSONDecodeError, ValueError) as e:
            ultimo_error = f"Error de datos: {e}"
        except Exception as e:
            ultimo_error = f"Error inesperado: {e}"

        if intento < max_intentos:
            logger.warning(f"⚠️ Intento {intento}/{max_intentos} falló: {ultimo_error}")
            logger.info(f"   Reintentando en {espera_segundos} segundos...")
            time.sleep(espera_segundos)

    logger.error(f"✗ API falló tras {max_intentos} intentos. Último error: {ultimo_error}")
    slog.error("api", str(ultimo_error))

    return None

# ═══════════════════════════════════════════════════════════════
# PROCESAMIENTO
# ═══════════════════════════════════════════════════════════════

class ProcesadorEspecialidades:
    def __init__(self, especialidades, estado_anterior, stats_db=None):
        self.especialidades = especialidades
        self.estado_anterior = estado_anterior or {}
        self.stats_db = stats_db or {"eventos": [], "registros": {}}
        self.estado_actual = {}
        self.cambios = {
            "nuevos": [],
            "reaperturas": [],
            "aumentos": [],
            "ultimos": [],
            "agotados": []
        }
        self.clasificacion = {
            "disponible": [],
            "pocos": [],
            "ultimos": [],
            "agotado": []
        }

    def procesar(self):
        for esp in self.especialidades:
            self._procesar_especialidad(esp)
        return self

    def _procesar_especialidad(self, esp):
        nombre = self._normalizar_nombre(esp.get("descripcion", ""))

        # Parseo DEFENSIVO: API puede devolver null, strings inválidos, etc
        try:
            cupo = max(0, int(esp.get("cupo") or 0))
        except (TypeError, ValueError):
            logger.warning(f"⚠️ Cupo inválido para {nombre}: {esp.get('cupo')}, usando 0")
            cupo = 0

        suspendido = esp.get("suspendido", False)
        if suspendido:
            cupo = 0  # Suspendida: no se puede reservar; cuenta como 0 turnos en todos lados

        disponible = cupo > 0

        self.estado_actual[nombre] = cupo
        cupo_anterior = self.estado_anterior.get(nombre, 0)

        self._detectar_cambios(nombre, cupo, cupo_anterior, disponible)

        if disponible:
            self._clasificar(nombre, cupo)
        elif cupo == 0:
            self.clasificacion["agotado"].append((nombre, 0))

    def _normalizar_nombre(self, nombre):
        nombre = nombre.strip().upper()
        return REEMPLAZOS_NOMBRES.get(nombre, nombre)

    def _detectar_cambios(self, nombre, cupo, cupo_anterior, disponible):
        if cupo_anterior == 0 and disponible:
            # Verificar si alguna vez estuvo disponible (reapertura vs primera vez)
            agotamientos_historicos = [
                e for e in self.stats_db.get("eventos", [])
                if e.get("especialidad") == nombre and e.get("tipo") == "agotados"
            ]
            if agotamientos_historicos:
                self.cambios["reaperturas"].append({
                    "nombre": nombre,
                    "cupo_actual": cupo,
                    "veces_agotada": len(agotamientos_historicos)
                })
                logger.info(f"🔄 REAPERTURA: {nombre} ({cupo} cupos, agotada {len(agotamientos_historicos)}x antes)")
            else:
                self.cambios["nuevos"].append({
                    "nombre": nombre,
                    "cupo_actual": cupo
                })
                logger.info(f"🆕 NUEVO: {nombre} ({cupo} cupos)")

            # Si aparece directamente con 1-4 cupos, también alertar como últimos
            if 1 <= cupo < 5:
                self.cambios["ultimos"].append({
                    "nombre": nombre,
                    "cupo_actual": cupo
                })
                logger.warning(f"⚠️ ÚLTIMOS (desde cero): {nombre} ({cupo} cupos)")

        elif cupo_anterior > 0 and cupo > cupo_anterior:
            self.cambios["aumentos"].append({
                "nombre": nombre,
                "cupo_anterior": cupo_anterior,
                "cupo_actual": cupo,
                "aumento": cupo - cupo_anterior
            })
            logger.info(f"📈 AUMENTO: {nombre} ({cupo_anterior} → {cupo}, +{cupo - cupo_anterior})")

        elif cupo_anterior > cupo and 1 <= cupo < 5:
            self.cambios["ultimos"].append({
                "nombre": nombre,
                "cupo_actual": cupo
            })
            logger.warning(f"⚠️ ÚLTIMOS: {nombre} ({cupo} cupos)")

        elif cupo_anterior > 0 and cupo == 0:
            self.cambios["agotados"].append({
                "nombre": nombre
            })
            logger.warning(f"❌ AGOTADO: {nombre}")

    def _clasificar(self, nombre, cupo):
        if CLASIFICACION_CUPOS["disponible"](cupo):
            self.clasificacion["disponible"].append((nombre, cupo))
        elif CLASIFICACION_CUPOS["pocos"](cupo):
            self.clasificacion["pocos"].append((nombre, cupo))
        elif CLASIFICACION_CUPOS["ultimos"](cupo):
            self.clasificacion["ultimos"].append((nombre, cupo))

    def hay_cambios(self):
        return any([
            self.cambios["nuevos"],
            self.cambios["aumentos"],
            self.cambios["ultimos"],
            self.cambios["agotados"]
        ])

    def hay_contenido(self):
        return (
            any(self.cambios.values()) or
            any(self.clasificacion.values())
        )

# ═══════════════════════════════════════════════════════════════
# TELEGRAM - MENSAJES PROFESIONALES - VERSIÓN FINAL
# ═══════════════════════════════════════════════════════════════

class ConstructorMensajeTelegram:
    def __init__(self, cambios, clasificacion, fecha_hora, estado_actual, total_especialidades):
        self.cambios = cambios
        self.clasificacion = clasificacion
        self.fecha_hora = fecha_hora
        self.estado_actual = estado_actual or {}
        self.total_especialidades = total_especialidades

    def construir(self):
        if not self._hay_contenido():
            return None

        secciones = []

        # Cada sección devuelve sus líneas SIN espaciado exterior.
        # construir() inserta exactamente 2 líneas vacías entre bloques.

        reaperturas_section = self._seccion_reaperturas()
        if reaperturas_section:
            secciones.append(reaperturas_section)

        cambios_section = self._seccion_cambios()
        if cambios_section:
            secciones.append(cambios_section)

        disponibles_section = self._seccion_disponibles()
        if disponibles_section:
            secciones.append(disponibles_section)

        pocos_section = self._seccion_pocos()
        if pocos_section:
            secciones.append(pocos_section)

        agotados_section = self._seccion_agotados()
        if agotados_section:
            secciones.append(agotados_section)

        stats_section = self._seccion_estadisticas()
        if stats_section:
            secciones.append(stats_section)

        # Encabezado
        lineas = [
            "🚨 NUEVOS TURNOS DISPONIBLES",
            "🏥 HOSPITAL PERRUPATO",
            "",
            "",  # 2 líneas vacías antes de primera sección
        ]

        # Unir secciones con exactamente 2 líneas vacías entre ellas
        for i, seccion in enumerate(secciones):
            lineas.extend(seccion)
            if i < len(secciones) - 1:
                lineas.append("")
                lineas.append("")  # 2 líneas vacías entre secciones

        # Limpiar líneas vacías finales
        while lineas and lineas[-1] == "":
            lineas.pop()

        return "\n".join(lineas)

    def _hay_contenido(self):
        return (
            bool(self.cambios.get("nuevos")) or
            bool(self.cambios.get("reaperturas")) or
            bool(self.cambios.get("aumentos")) or
            any(self.clasificacion.values())
        )

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: CAMBIOS DETECTADOS
    # ─────────────────────────────────────────────────────────

    def _seccion_cambios(self):
        # Solo mostrar nuevos y aumentos — ultimos tienen su propia alerta urgente
        if not any([self.cambios["nuevos"], self.cambios["aumentos"]]):
            return None

        lineas = ["────────────", "🆕 CAMBIOS DETECTADOS", "────────────"]
        todos_items = []

        nuevos_ordenados = sorted(self.cambios["nuevos"], key=lambda x: x['nombre'])
        for item in nuevos_ordenados:
            cupo = item['cupo_actual']
            plural = "s" if cupo > 1 else ""
            todos_items.append([
                f"🏥 {item['nombre']}",
                f"🍀 {formato_cupos_disponibles(cupo)}",
                f"📈 +{cupo} nuevo{plural}",
            ])

        aumentos_ordenados = sorted(self.cambios["aumentos"], key=lambda x: x['nombre'])
        for item in aumentos_ordenados:
            aumento = item['aumento']
            plural = "s" if aumento > 1 else ""
            todos_items.append([
                f"🏥 {item['nombre']}",
                f"🍀 {formato_cupos_disponibles(item['cupo_actual'])}",
                f"📈 +{aumento} nuevo{plural}",
            ])

        for i, item_lineas in enumerate(todos_items):
            lineas.extend(item_lineas)
            if i < len(todos_items) - 1:
                lineas.append("")

        return lineas

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: REAPERTURAS
    # ─────────────────────────────────────────────────────────

    def _seccion_reaperturas(self):
        if not self.cambios.get("reaperturas"):
            return None

        items = sorted(self.cambios["reaperturas"], key=lambda x: x["nombre"])
        lineas = ["────────────", "🔄 REAPERTURAS", "────────────"]

        for i, item in enumerate(items):
            cupo = item["cupo_actual"]
            veces = item["veces_agotada"]
            plural = "s" if cupo > 1 else ""
            lineas.append(f"🏥 {item['nombre']}")
            lineas.append(f"🍀 {formato_cupos_disponibles(cupo)}")
            lineas.append(f"⚡ Reabre · agotada {veces}x antes")
            if i < len(items) - 1:
                lineas.append("")

        return lineas

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: DISPONIBLES AHORA
    # ─────────────────────────────────────────────────────────

    def _nombres_ya_mostrados(self):
        # Especialidades ya listadas arriba en Reaperturas o Cambios Detectados.
        # Se usan para no repetirlas en la "foto" de estado actual.
        nombres = set()
        for item in self.cambios.get("reaperturas", []):
            nombres.add(item["nombre"])
        for item in self.cambios.get("nuevos", []):
            nombres.add(item["nombre"])
        for item in self.cambios.get("aumentos", []):
            nombres.add(item["nombre"])
        return nombres

    def _seccion_disponibles(self):
        ya_mostrados = self._nombres_ya_mostrados()
        items = [(n, c) for (n, c) in self.clasificacion["disponible"] if n not in ya_mostrados]
        if not items:
            return None

        items = sorted(items, key=lambda x: x[0])
        lineas = ["────────────", "🟢 DISPONIBLES AHORA", "────────────"]

        for i, (nombre, cupo) in enumerate(items):
            plural = "s" if cupo > 1 else ""
            lineas.append(f"🏥 {nombre}")
            lineas.append(f"✅ {cupo} Cupo{plural}")
            if i < len(items) - 1:
                lineas.append("")

        return lineas

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: POCOS CUPOS DISPONIBLES
    # ─────────────────────────────────────────────────────────

    def _seccion_pocos(self):
        ya_mostrados = self._nombres_ya_mostrados()
        especiales = self.clasificacion["pocos"] + self.clasificacion["ultimos"]
        especiales = [(n, c) for (n, c) in especiales if n not in ya_mostrados]

        if not especiales:
            return None

        items = sorted(especiales, key=lambda x: x[0])
        lineas = ["────────────", "⚠️ POCOS CUPOS DISPONIBLES", "────────────"]

        for i, (nombre, cupo) in enumerate(items):
            plural = "s" if cupo > 1 else ""
            lineas.append(f"🏥 {nombre}")
            lineas.append(f"⚠️ {cupo} Cupo{plural}")
            if i < len(items) - 1:
                lineas.append("")

        return lineas

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: SIN CUPOS DISPONIBLES (SIEMPRE visible)
    # ─────────────────────────────────────────────────────────

    def _seccion_agotados(self):
        lineas = ["────────────", "‼️ SIN CUPOS DISPONIBLES", "────────────"]

        agotadas = sorted(
            [(nombre, cupo) for nombre, cupo in self.estado_actual.items() if cupo == 0],
            key=lambda x: x[0]
        )

        if not agotadas:
            lineas.append("(No hay especialidades agotadas)")
            return lineas

        # Compacto: sin líneas vacías entre items
        for nombre, _ in agotadas:
            lineas.append(f"🚫 {nombre}")

        return lineas

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: ESTADÍSTICAS FINALES
    # ─────────────────────────────────────────────────────────

    def _seccion_estadisticas(self):
        total_con_cupos = len([c for c in self.estado_actual.values() if c > 0])
        total_cupos = sum(self.estado_actual.values())

        lineas = [
            "📊 ESTADÍSTICAS",
            f"• Monitoreadas: {self.total_especialidades}",
            f"• Con cupos: {total_con_cupos}",
            f"• Total: {total_cupos}",
            "",
            f"🕒 {self.fecha_hora}",
            "",
            "👉 https://sganotti.mendoza.gov.ar/digisalud/comunicacion/solicitudturnosweb.aspx?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328"
        ]

        return lineas

# ═══════════════════════════════════════════════════════════════
# NOTIFICACIONES
# ═══════════════════════════════════════════════════════════════

def enviar_telegram(mensaje):
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("⚠️ Telegram no configurado")
        return False

    # VALIDACIÓN: Límite de 4096 caracteres en Telegram
    limite_telegram = 4096
    if len(mensaje) > limite_telegram:
        logger.warning(f"⚠️ Mensaje muy largo ({len(mensaje)} chars), truncando...")
        # Truncar y agregar nota
        mensaje = mensaje[:limite_telegram - 50] + "\n\n[...mensaje truncado por longitud]"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": mensaje},
            timeout=10
        )

        if response.status_code == 200:
            logger.info(f"✓ Notificación Telegram enviada ({len(mensaje)} chars)")
            return True
        else:
            logger.error(f"✗ Error Telegram: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"✗ Error enviando Telegram: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# ESTADÍSTICAS
# ═══════════════════════════════════════════════════════════════

def guardar_estadisticas(cambios, estado_actual, es_primera_ejecucion):
    try:
        stats = cargar_json(ARCHIVOS["estadisticas"]) or {"registros": {}, "eventos": []}
        ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
        fecha = ahora.strftime("%Y-%m-%d")

        if fecha not in stats["registros"]:
            stats["registros"][fecha] = []

        stats["registros"][fecha].append({
            "hora": ahora.strftime("%H:%M:%S"),
            "con_cupos": len([c for c in estado_actual.values() if c > 0]),
            "total_cupos": sum(estado_actual.values()),
            "cambios": sum(len(x) for x in cambios.values())
        })

        # DEDUPLICACIÓN: Hash único por evento para evitar duplicados
        eventos_existentes = {f"{e['fecha'][:19]}|{e['tipo']}|{e['especialidad']}" for e in stats["eventos"]}

        for cambio_tipo, items in cambios.items():
            for item in items:
                evento_key = f"{ahora.isoformat()[:19]}|{cambio_tipo}|{item['nombre']}"

                # Si es primera ejecución, no registrar como "nuevos" (son solo estado inicial)
                if es_primera_ejecucion and cambio_tipo == "nuevos":
                    logger.info(f"ℹ️ Primera ejecución: no registrando {item['nombre']} como nuevo")
                    continue

                # No duplicar eventos
                if evento_key not in eventos_existentes:
                    stats["eventos"].append({
                        "fecha": ahora.isoformat(),
                        "tipo": cambio_tipo,
                        "especialidad": item["nombre"],
                        "cupos": item.get("cupo_actual", 0)
                    })
                    eventos_existentes.add(evento_key)

        # Limpiar eventos antiguos (90 días)
        fecha_limite = (ahora - timedelta(days=90)).isoformat()
        stats["eventos"] = [e for e in stats["eventos"] if e["fecha"] > fecha_limite]

        # Limpiar registros diarios antiguos (90 días)
        fecha_limite_registros = (ahora - timedelta(days=90)).strftime("%Y-%m-%d")
        stats["registros"] = {
            f: r for f, r in stats["registros"].items()
            if f >= fecha_limite_registros
        }

        guardar_json_seguro(stats, ARCHIVOS["estadisticas"])

    except Exception as e:
        logger.error(f"Error guardando estadísticas: {e}")

# ═══════════════════════════════════════════════════════════════
# REPORTE DIARIO
# ═══════════════════════════════════════════════════════════════

def generar_reporte_diario():
    try:
        stats = cargar_json(ARCHIVOS["estadisticas"])
        if not stats:
            return None

        ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
        fecha = ahora.strftime("%Y-%m-%d")
        ayer = (ahora - timedelta(days=1)).strftime("%Y-%m-%d")

        if fecha not in stats["registros"]:
            logger.warning(f"⚠️ No hay registros de hoy ({fecha}); reporte matutino omitido")
            return None

        # El recap es del día anterior completo (el reporte se genera a la mañana)
        registros_ayer = stats["registros"].get(ayer, [])
        eventos_ayer = [e for e in stats["eventos"] if e["fecha"].startswith(ayer)]

        # Especialidades con cupos ahora
        estado_actual = cargar_json(ARCHIVOS["estado"]) or {}
        con_cupos = [(nombre, cupo) for nombre, cupo in estado_actual.items() if cupo > 0]
        con_cupos.sort(key=lambda x: x[0])
        sin_cupos = [nombre for nombre, cupo in estado_actual.items() if cupo == 0]

        # Aperturas de ayer (nuevas + reaperturas)
        aperturas_ayer = sorted({e["especialidad"] for e in eventos_ayer if e["tipo"] in ("nuevos", "reaperturas")})

        # Construir mensaje
        lineas = [
            f"🌅 RESUMEN MATUTINO",
            f"🏥 HOSPITAL PERRUPATO",
            f"📅 {ahora.strftime('%d/%m/%Y')}",
            "",
            "────────────",
            "📊 ESTADO ACTUAL",
            "────────────",
            f"• Especializades monitoreadas: {len(estado_actual)}",
            f"• Con cupos disponibles: {len(con_cupos)}",
            f"• Sin cupos: {len(sin_cupos)}",
            f"• Total cupos: {sum(cupo for _, cupo in con_cupos)}",
        ]

        if con_cupos:
            lineas += ["", "────────────", "✅ DISPONIBLES AHORA", "────────────"]
            for nombre, cupo in con_cupos:
                plural = "s" if cupo > 1 else ""
                lineas.append(f"🏥 {nombre}: {cupo} cupo{plural}")

        if aperturas_ayer:
            lineas += ["", "────────────", "🆕 ABRIERON AYER", "────────────"]
            for nombre in aperturas_ayer:
                lineas.append(f"• {nombre}")

        lineas += [
            "",
            "────────────",
            "📈 ACTIVIDAD DE AYER",
            "────────────",
            f"• Monitoreos realizados: {len(registros_ayer)}",
            f"• Cambios detectados: {len(eventos_ayer)}",
            f"• Aperturas (nuevas + reaperturas): {sum(1 for e in eventos_ayer if e['tipo'] in ('nuevos', 'reaperturas'))}",
            f"• Agotamientos: {sum(1 for e in eventos_ayer if e['tipo'] == 'agotados')}",
            "",
            f"🕒 Generado: {ahora.strftime('%d/%m • %H:%M hs')}",
        ]

        return "\n".join(lineas)
    except Exception as e:
        logger.error(f"Error generando reporte: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# DETECCIÓN DE PATRONES
# ═══════════════════════════════════════════════════════════════

def detectar_patrones_apertura(hora_objetivo):
    """
    Analiza el historial de eventos y avisa si alguna especialidad
    suele abrir turnos en la hora_objetivo.
    Solo notifica si hay al menos 5 aperturas históricas en esa hora,
    repartidas en al menos 3 días distintos, y la especialidad no
    tiene cupos ahora mismo.
    Cuenta como apertura: nuevos, aumentos y reaperturas.
    """
    try:
        stats = cargar_json(ARCHIVOS["estadisticas"]) or {}
        eventos = stats.get("eventos", [])
        estado_actual = cargar_json(ARCHIVOS["estado"]) or {}

        if not eventos:
            return None

        # Contar aperturas por especialidad y hora
        aperturas_por_hora = {}
        for e in eventos:
            if e.get("tipo") not in ("nuevos", "aumentos", "reaperturas"):
                continue
            try:
                hora = datetime.fromisoformat(e["fecha"]).hour
            except Exception:
                continue
            esp = e["especialidad"]
            if esp not in aperturas_por_hora:
                aperturas_por_hora[esp] = {}
            aperturas_por_hora[esp][hora] = aperturas_por_hora[esp].get(hora, 0) + 1

        # Pre-agrupar eventos por especialidad para O(N+M) en vez de O(N×M)
        from collections import defaultdict
        eventos_por_esp = defaultdict(list)
        for e in eventos:
            if e.get("tipo") in ("nuevos", "aumentos", "reaperturas"):
                eventos_por_esp[e["especialidad"]].append(e)

        # Filtrar: especialidades que suelen abrir en hora_objetivo
        # con mínimo 5 aperturas en al menos 3 días distintos
        candidatas = []
        for esp, horas in aperturas_por_hora.items():
            frecuencia = horas.get(hora_objetivo, 0)
            if frecuencia < 5:
                continue
            if estado_actual.get(esp, 0) != 0:
                continue
            # Contar días distintos solo para esta especialidad (eficiente)
            dias_distintos = len({
                e["fecha"][:10] for e in eventos_por_esp[esp]
                if datetime.fromisoformat(e["fecha"]).hour == hora_objetivo
            })
            if dias_distintos >= 3:
                candidatas.append((esp, frecuencia))

        if not candidatas:
            return None

        candidatas.sort(key=lambda x: x[1], reverse=True)

        hora_str = f"{hora_objetivo:02d}:00"
        lineas = [
            "🔮 PATRÓN DETECTADO",
            f"Estas especialidades suelen abrir turnos a las {hora_str}:",
            ""
        ]
        for esp, frec in candidatas[:5]:  # máximo 5 para no saturar
            lineas.append(f"📌 {esp} ({frec}x histórico)")

        lineas += [
            "",
            f"🕒 Próxima verificación en 15 minutos",
            "",
            "👉 https://sganotti.mendoza.gov.ar/digisalud/comunicacion/solicitudturnosweb.aspx?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328"
        ]

        logger.info(f"🔮 Patrón detectado: {len(candidatas)} especialidad(es) suelen abrir a las {hora_str}")
        return "\n".join(lineas)

    except Exception as e:
        logger.error(f"Error detectando patrones: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
    fecha_hora = ahora.strftime("%d/%m • %H:%M hs")

    logger.info("╔════════════════════════════════════════════════════╗")
    logger.info(f"║ 🏥 MONITOR PROFESIONAL - {ahora.strftime('%d/%m/%Y %H:%M:%S')} ║")
    logger.info("╚════════════════════════════════════════════════════╝")

    estado_anterior = cargar_json(ARCHIVOS["estado"]) or {}
    especialidades = consultar_api()

    if not especialidades:
        logger.critical("✗ No se pudo obtener datos de la API")
        # Anti-spam: avisar solo en la PRIMERA falla, no en cada ciclo de 15 min
        hb_api = cargar_json(ARCHIVOS["heartbeat"]) or {}
        if not hb_api.get("api_caida"):
            enviar_telegram("🚨 Error: No se pudo conectar con la API del hospital")
            hb_api["api_caida"] = True
            guardar_json_seguro(hb_api, ARCHIVOS["heartbeat"])
            logger.warning("📴 API caída: alerta enviada (no se repetirá hasta la recuperación)")
        else:
            logger.warning("📴 API sigue caída: no se reenvía la alerta")
        raise RuntimeError("No se pudo obtener datos de la API")

    # API respondió OK: si veníamos de una caída previa, avisar la recuperación
    hb_api = cargar_json(ARCHIVOS["heartbeat"]) or {}
    if hb_api.get("api_caida"):
        enviar_telegram(
            "✅ La API del hospital volvió a responder\n\n"
            "El monitor retomó la vigilancia normal de turnos."
        )
        hb_api["api_caida"] = False
        guardar_json_seguro(hb_api, ARCHIVOS["heartbeat"])
        logger.info("✅ API recuperada: alerta de recuperación enviada")

    # VERIFICAR si es primera ejecución
    es_primera_ejecucion = len(estado_anterior) == 0

    stats_db = cargar_json(ARCHIVOS["estadisticas"]) or {"eventos": [], "registros": {}}
    procesador = ProcesadorEspecialidades(especialidades, estado_anterior, stats_db).procesar()

    guardar_json_seguro(estado_anterior, ARCHIVOS["estado_anterior"])
    guardar_json_seguro(procesador.estado_actual, ARCHIVOS["estado"])
    guardar_historial_cupos(procesador.estado_actual, ahora)
    hb_estado = cargar_json(ARCHIVOS["heartbeat"]) or {}
    hb_estado["ultima_ejecucion"] = ahora.isoformat()
    guardar_json_seguro(hb_estado, ARCHIVOS["heartbeat"])
    total_especialidades = len(procesador.estado_actual)
    slog.ejecucion(
        estado="ok",
        especialidades=total_especialidades,
        cupos=sum(procesador.estado_actual.values()),
        con_cupos=len([c for c in procesador.estado_actual.values() if c > 0])
    )
    guardar_estadisticas(procesador.cambios, procesador.estado_actual, es_primera_ejecucion)

    # ✓ MODO PRUEBA: Forzar notificación con estado actual
    if os.environ.get("TEST_MODE") == "true":
        logger.info("🧪 MODO PRUEBA ACTIVADO — forzando notificación Telegram")
        constructor = ConstructorMensajeTelegram(
            procesador.cambios,
            procesador.clasificacion,
            fecha_hora,
            procesador.estado_actual,
            total_especialidades
        )
        # En modo prueba, forzar cambios vacíos pero mostrar disponibles
        constructor.cambios = {"nuevos": [], "aumentos": [], "ultimos": [], "agotados": []}
        mensaje = constructor.construir()
        if mensaje:
            enviar_telegram("🧪 MENSAJE DE PRUEBA\n\n" + mensaje)
        else:
            enviar_telegram("🧪 PRUEBA OK — Sin especialidades con cupos en este momento")
        return

    # ✓ PRIMERA EJECUCIÓN: NO enviar Telegram, solo guardar estado
    if es_primera_ejecucion:
        logger.info("🎯 PRIMERA EJECUCIÓN")
        logger.info(f"   ✓ Estado base guardado ({total_especialidades} especialidades)")
        logger.info("   ℹ️ NO se envía notificación en primera ejecución")
        return

    # Log estructurado de cambios detectados
    for item in procesador.cambios.get("nuevos", []):
        slog.cambio("nuevos", item["nombre"], item.get("cupo_actual", 0))
    for item in procesador.cambios.get("aumentos", []):
        slog.cambio("aumentos", item["nombre"], item.get("cupo_actual", 0))
    for item in procesador.cambios.get("ultimos", []):
        slog.cambio("ultimos", item["nombre"], item.get("cupo_actual", 0))
    for item in procesador.cambios.get("agotados", []):
        slog.cambio("agotados", item["nombre"], 0)

    # ── FLUJO 1: Mensaje general (siempre, con todos los cambios) ──
    hay_cambios = (procesador.cambios["nuevos"] or procesador.cambios["reaperturas"] or
                   procesador.cambios["aumentos"])

    if hay_cambios:
        constructor = ConstructorMensajeTelegram(
            procesador.cambios,
            procesador.clasificacion,
            fecha_hora,
            procesador.estado_actual,
            total_especialidades
        )
        mensaje = constructor.construir()
        if mensaje:
            exito = enviar_telegram(mensaje)
            slog.telegram("notificacion_principal", exito)
    else:
        logger.info("ℹ️ Sin nuevos o aumentos para notificar")

    # ── FLUJO 2: Mensajes individuales para especialidades de interés ──
    interes = [e.upper().strip() for e in CONFIG.get("especialidades_interes", [])]
    if interes and hay_cambios:
        logger.info(f"🎯 Filtro activo: {len(interes)} especialidades de interés")
        todas_listas = (
            procesador.cambios["nuevos"] +
            procesador.cambios["reaperturas"] +
            procesador.cambios["aumentos"] +
            procesador.cambios["ultimos"]
        )
        for especialidad in interes:
            items_esp = [c for c in todas_listas if c["nombre"].upper() == especialidad]
            if items_esp:
                item = items_esp[0]
                cupo = item.get("cupo_actual", 0)
                tipo = next(
                    t for t, lista in [
                        ("🆕 NUEVO", procesador.cambios["nuevos"]),
                        ("🔄 REAPERTURA", procesador.cambios["reaperturas"]),
                        ("📈 AUMENTO", procesador.cambios["aumentos"]),
                        ("⚠️ ÚLTIMOS CUPOS", procesador.cambios["ultimos"]),
                    ] if item in lista
                )
                plural = "s" if cupo > 1 else ""
                msg_individual = (
                    f"🔔 ALERTA PERSONALIZADA\n"
                    f"🏥 {item['nombre']}\n\n"
                    f"{tipo}\n"
                    f"🍀 {cupo} Cupo{plural} Disponible{plural}\n\n"
                    f"🕒 {fecha_hora}\n\n"
                    f"👉 https://sganotti.mendoza.gov.ar/digisalud/comunicacion/solicitudturnosweb.aspx"
                    f"?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328"
                )
                enviar_telegram(msg_individual)
                logger.info(f"🔔 Alerta individual enviada: {item['nombre']}")

    # ── Alerta urgente: últimos cupos ──
    if procesador.cambios["ultimos"]:
        lineas = ["🚨 ÚLTIMOS CUPOS — URGENTE", "🏥 HOSPITAL PERRUPATO", ""]
        for item in sorted(procesador.cambios["ultimos"], key=lambda x: x["cupo_actual"]):
            cupo = item["cupo_actual"]
            plural = "s" if cupo > 1 else ""
            lineas.append(f"⚠️ {item['nombre']}")
            lineas.append(f"   Solo {cupo} cupo{plural} disponible{plural}")
            lineas.append("")
        lineas += [
            f"🕒 {fecha_hora}",
            "",
            "👉 https://sganotti.mendoza.gov.ar/digisalud/comunicacion/solicitudturnosweb.aspx?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328"
        ]
        enviar_telegram("\n".join(lineas))
        logger.info(f"🚨 Alerta urgente enviada: {len(procesador.cambios['ultimos'])} especialidad(es) con últimos cupos")

    if CONFIG.get("generar_reporte_diario"):
        hora_config_str = CONFIG.get("hora_reporte_diario", "08:00")
        try:
            hora_config_min = int(hora_config_str.split(":")[0]) * 60 + int(hora_config_str.split(":")[1])
            hora_actual_min = ahora.hour * 60 + ahora.minute
            if abs(hora_actual_min - hora_config_min) <= 7:
                # Verificar que no se envió ya hoy
                hb = cargar_json(ARCHIVOS["heartbeat"]) or {}
                ultimo_reporte = hb.get("ultimo_reporte_fecha", "")
                hoy = ahora.strftime("%Y-%m-%d")
                if ultimo_reporte != hoy:
                    reporte = generar_reporte_diario()
                    if reporte:
                        with open(ARCHIVOS["reporte"], "w", encoding="utf-8") as f:
                            f.write(reporte)
                        enviar_telegram(reporte)
                        hb["ultimo_reporte_fecha"] = hoy
                        guardar_json_seguro(hb, ARCHIVOS["heartbeat"])
                        logger.info("📋 Reporte matutino enviado")
        except Exception as e:
            logger.warning(f"Error verificando hora de reporte: {e}")

    # Detección de patrones: usando timestamp para no depender del minuto exacto
    if CONFIG.get("alertas_patrones", True):
        hb_pat = cargar_json(ARCHIVOS["heartbeat"]) or {}
        ultima_alerta_ts = hb_pat.get("ultima_alerta_patron_ts", "1970-01-01T00:00:00")
        try:
            ultima_alerta_dt = datetime.fromisoformat(ultima_alerta_ts)
            if ultima_alerta_dt.tzinfo is None:
                ultima_alerta_dt = ultima_alerta_dt.replace(tzinfo=ahora.tzinfo)
        except Exception:
            ultima_alerta_dt = datetime.min.replace(tzinfo=ahora.tzinfo)
        minutos_desde_ultima = (ahora - ultima_alerta_dt).total_seconds() / 60
        if minutos_desde_ultima >= 45:
            hora_siguiente = (ahora.hour + 1) % 24
            alerta_patrones = detectar_patrones_apertura(hora_siguiente)
            if alerta_patrones:
                enviar_telegram(alerta_patrones)
                hb_pat["ultima_alerta_patron_ts"] = ahora.isoformat()
                guardar_json_seguro(hb_pat, ARCHIVOS["heartbeat"])

    logger.info("═════════════════════════════════════════════════════")

if __name__ == "__main__":
    ping_healthchecks("/start")
    try:
        main()
        ping_healthchecks()  # señal de éxito
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.critical(f"Error crítico: {e}", exc_info=True)
        ping_healthchecks("/fail")
        raise