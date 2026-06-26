"""
🏥 MONITOR DE TURNOS - HOSPITAL PERRUPATO
Sistema profesional de monitoreo automático

Características:
- Consulta API cada 5 minutos
- Notificaciones inteligentes en Telegram
- Estadísticas históricas (180 días)
- Dashboard web interactivo
- Diseño profesional y moderno
- Todos los cambios estéticos finales
"""

import requests
import os
import time
import json
import re
import unicodedata
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
    "predicciones": "predicciones.json",
    "historial_cupos": "historial_cupos.json",
    "velocidad": "velocidad_estado.json",
    "encargos": "encargos.json"
}

REEMPLAZOS_NOMBRES = {
    "DIABETOLOGIA GENERAL(CON DERIVACIÓN)": "DIABETOLOGIA GENERAL",
    "HEMATOLOGIA CLINICA ( CON DERIVACION )": "HEMATOLOGIA CLINICA",
    "CIRUGIA TORACICA (CON DERIVACION)": "CIRUGIA TORACICA",
    "NEFROLOGIA (CON DERIVACION)": "NEFROLOGIA",
}

CLASIFICACION_CUPOS = {
    "disponible": lambda c: c >= 20,
    "pocos": lambda c: 6 <= c < 20,
    "ultimos": lambda c: 1 <= c <= 5,
    "agotado": lambda c: c == 0
}


def _norm_esp(s):
    """Normaliza un nombre de especialidad: mayúsculas, sin tildes, sin espacios extra."""
    base = unicodedata.normalize('NFD', (s or '').upper().strip())
    sin_tildes = ''.join(c for c in base if unicodedata.category(c) != 'Mn')
    return ' '.join(sin_tildes.split())

# Emoji propio de cada especialidad (catálogo provisto). Las claves se normalizan
# para que el match no dependa de tildes ni espacios. Si una especialidad no está, usa el genérico.
_EMOJI_CATALOGO = {
    "CARDIOLOGIA ADULTO": "🫀",
    "CARDIOLOGIA INFANTIL": "🫀",
    "CIRUGIA GENERAL": "🔪",
    "CIRUGIA INFANTIL": "🔪",
    "CIRUGIA TORACICA": "🔪",
    "CLINICA MEDICA CONSULTA": "🩺",
    "COLOPROCTOLOGIA": "💩",
    "CUIDADOS PALIATIVOS CON DERIVACION OBLIGATORIA": "🕊️",
    "DERMATOLOGIA GENERAL": "🧴",
    "DIABETOLOGIA GENERAL": "🍬",
    "ECOCARDIOGRAMA DOPPLER ADULTO (DERIVACION OBLIGATORIA)": "🫀",
    "ELECTROCARDIOGRAMA ADULTO(CON DERIVACION)": "🫀",
    "ESPIROMETRIA ADULTO (CON DERIVACIÓN)": "🫁",
    "ESPIROMETRIA NIÑOS (CON DERIVACIÓN)": "🫁",
    "FLEBOLOGIA (CONSULTA)": "🦵",
    "FONOAUDIOLOGIA AUDIOMETRIA (SOLO CON DERIVACIÓN)": "🦻",
    "HEMATOLOGIA CLINICA": "🩸",
    "INFECTOLOGIA": "🦠",
    "INFECTOLOGIA PEDIATRICA": "🦠",
    "NEFROLOGIA": "🫘",
    "NEUMONOLOGIA ADULTO (CON DERIVACIÓN)": "🫁",
    "NEUMONOLOGIA INFANTIL": "🫁",
    "NEUROLOGIA NUEVO (CON DERIVACIÓN)": "🧠",
    "NUTRICION GENERAL": "🥗",
    "OBSTETRICIA BAJO RIESGO": "🤰",
    "ODONTOLOGIA ADULTO": "🦷",
    "ODONTOLOGÍA PEDIATRICA": "🦷",
    "OFTALMOLOGIA": "👁️",
    "ONCOLOGIA": "🎗️",
    "ORL CONSULTAS": "🗣️",
    "PATOLOGIA MAMARIA (CON DERIVACION OBLIGATORIA)": "🎀",
    "PEDIATRIA CONSULTA": "👶",
    "PEDIATRIA MEDIANO RIESGO": "👶",
    "PODOLOGIA": "🦶",
    "PRE ANESTESIA PEDIATRIA": "💉",
    "REUMATOLOGIA (DERIVACION OBLIGATORIA)": "🦴",
    "TRAUMATOLOGIA ADULTO": "🦴",
    "TRAUMATOLOGIA INFANTIL": "🦴",
    "UROLOGIA": "🚻",
    "VASCULAR PERIFERICO (OBLIGATORIO DERIVACION PACIENTE NUEVO)": "🦵",
}
EMOJI_ESPECIALIDAD = {_norm_esp(k): v for k, v in _EMOJI_CATALOGO.items()}
EMOJI_DEFAULT = "🏥"

def emoji_de(nombre):
    return EMOJI_ESPECIALIDAD.get(_norm_esp(nombre), EMOJI_DEFAULT)

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
    def __init__(self, especialidades, estado_anterior, stats_db=None, sin_baseline=False):
        self.especialidades = especialidades
        self.estado_anterior = estado_anterior or {}
        self.sin_baseline = sin_baseline
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

        suspendido = esp.get("suspendido", True)
        disponible = cupo > 0 and not suspendido

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
        # Sin estado anterior (primer arranque o reinicio que perdió el baseline):
        # no se puede comparar contra nada, así que NO se emite ningún evento de cambio.
        # Este ciclo solo sirve para fijar el baseline; el próximo ya detecta cambios reales.
        if self.sin_baseline:
            return
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

            # Si aparece directamente con 1-5 cupos, también alertar como últimos
            if 1 <= cupo <= 5:
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

        elif cupo_anterior > 5 and 1 <= cupo <= 5:
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

        cambios_section = self._seccion_cambios()
        if cambios_section:
            secciones.append(cambios_section)

        reaperturas_section = self._seccion_reaperturas()
        if reaperturas_section:
            secciones.append(reaperturas_section)

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
                f"{emoji_de(item['nombre'])} {item['nombre']}",
                f"🍀 {formato_cupos_disponibles(cupo)}",
                f"📈 +{cupo} nuevo{plural}",
            ])

        aumentos_ordenados = sorted(self.cambios["aumentos"], key=lambda x: x['nombre'])
        for item in aumentos_ordenados:
            aumento = item['aumento']
            plural = "s" if aumento > 1 else ""
            todos_items.append([
                f"{emoji_de(item['nombre'])} {item['nombre']}",
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
            lineas.append(f"{emoji_de(item['nombre'])} {item['nombre']}")
            lineas.append(f"🍀 {formato_cupos_disponibles(cupo)}")
            lineas.append(f"⚡ Reabre · agotada {veces}x antes")
            if i < len(items) - 1:
                lineas.append("")

        return lineas

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: DISPONIBLES AHORA
    # ─────────────────────────────────────────────────────────

    def _seccion_disponibles(self):
        if not self.clasificacion["disponible"]:
            return None

        items = sorted(self.clasificacion["disponible"], key=lambda x: x[0])
        lineas = ["────────────", "🟢 DISPONIBLES AHORA", "────────────"]

        for i, (nombre, cupo) in enumerate(items):
            plural = "s" if cupo > 1 else ""
            lineas.append(f"{emoji_de(nombre)} {nombre}")
            lineas.append(f"✅ {cupo} Cupo{plural}")
            if i < len(items) - 1:
                lineas.append("")

        return lineas

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: POCOS CUPOS DISPONIBLES
    # ─────────────────────────────────────────────────────────

    def _seccion_pocos(self):
        especiales = self.clasificacion["pocos"] + self.clasificacion["ultimos"]

        if not especiales:
            return None

        items = sorted(especiales, key=lambda x: x[0])
        lineas = ["────────────", "⚠️ POCOS CUPOS DISPONIBLES", "────────────"]

        for i, (nombre, cupo) in enumerate(items):
            plural = "s" if cupo > 1 else ""
            lineas.append(f"{emoji_de(nombre)} {nombre}")
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

def guardar_estadisticas(cambios, estado_actual):
    try:
        stats = cargar_json(ARCHIVOS["estadisticas"]) or {"registros": {}, "eventos": [], "es_primera_ejecucion": True}
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
                if stats["es_primera_ejecucion"] and cambio_tipo == "nuevos":
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

        # Limpiar eventos antiguos (180 días)
        fecha_limite = (ahora - timedelta(days=180)).isoformat()
        stats["eventos"] = [e for e in stats["eventos"] if e["fecha"] > fecha_limite]

        # Limpiar registros diarios antiguos (180 días)
        fecha_limite_registros = (ahora - timedelta(days=180)).strftime("%Y-%m-%d")
        stats["registros"] = {
            f: r for f, r in stats["registros"].items()
            if f >= fecha_limite_registros
        }

        # Marcar que ya no es primera ejecución
        if stats.get("es_primera_ejecucion"):
            stats["es_primera_ejecucion"] = False
            logger.info("✓ Primera ejecución completada")

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

        if fecha not in stats["registros"]:
            return None

        registros = stats["registros"][fecha]
        eventos = [e for e in stats["eventos"] if e["fecha"].startswith(fecha)]

        # Especialidades con cupos ahora
        estado_actual = cargar_json(ARCHIVOS["estado"]) or {}
        con_cupos = [(nombre, cupo) for nombre, cupo in estado_actual.items() if cupo > 0]
        con_cupos.sort(key=lambda x: x[0])
        sin_cupos = [nombre for nombre, cupo in estado_actual.items() if cupo == 0]

        # Aperturas del día
        nuevas_hoy = list({e["especialidad"] for e in eventos if e["tipo"] == "nuevos"})
        nuevas_hoy.sort()

        # Construir mensaje
        lineas = [
            f"🌅 RESUMEN MATUTINO",
            f"🏥 HOSPITAL PERRUPATO",
            f"📅 {ahora.strftime('%d/%m/%Y')}",
            "",
            "────────────",
            "📊 ESTADO ACTUAL",
            "────────────",
            f"• Especialidades monitoreadas: {len(estado_actual)}",
            f"• Con cupos disponibles: {len(con_cupos)}",
            f"• Sin cupos: {len(sin_cupos)}",
            f"• Total cupos: {sum(cupo for _, cupo in con_cupos)}",
        ]

        if con_cupos:
            lineas += ["", "────────────", "✅ DISPONIBLES AHORA", "────────────"]
            for nombre, cupo in con_cupos:
                plural = "s" if cupo > 1 else ""
                lineas.append(f"{emoji_de(nombre)} {nombre}: {cupo} cupo{plural}")

        if nuevas_hoy:
            lineas += ["", "────────────", "🆕 ABRIERON HOY", "────────────"]
            for nombre in nuevas_hoy:
                lineas.append(f"• {nombre}")

        lineas += [
            "",
            "────────────",
            "📈 ACTIVIDAD DE AYER",
            "────────────",
            f"• Monitoreos realizados: {len(registros)}",
            f"• Cambios detectados: {len(eventos)}",
            f"• Nuevas aperturas: {sum(1 for e in eventos if e['tipo'] == 'nuevos')}",
            f"• Agotamientos: {sum(1 for e in eventos if e['tipo'] == 'agotados')}",
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

def construir_alerta_patron(banner, fecha_hora):
    """Alerta anticipatoria (uso personal), alineada con el banner del dashboard.
    Reusa el modelo condicional: especialidades agotadas AHORA con probabilidad
    real de abrir pronto (probabilidad + confianza), no la frecuencia cruda."""
    if not banner or not banner.get("items"):
        return None

    hora = banner.get("hora", "")
    dias = banner.get("dias", 0)
    lineas = [
        "🔮 PATRÓN DE APERTURAS DETECTADO",
        f"Suelen abrir cerca de las {hora} hs y ahora están agotadas:",
        "",
    ]
    for it in banner["items"]:
        nombre = it["especialidad"]
        nivel = "Alta" if it.get("confianza") == "alta" else "Media"
        lineas.append(f"{emoji_de(nombre)} {nombre}")
        lineas.append(f"   Probabilidad {nivel} · {it['aciertos']} de {it['casos']} días similares")
        lineas.append("")
    lineas += [
        f"🕒 Basado en {dias} días de historial · {fecha_hora}",
        "",
        "👉 https://sganotti.mendoza.gov.ar/digisalud/comunicacion/solicitudturnosweb.aspx?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328",
    ]
    return "\n".join(lineas)


# ═══════════════════════════════════════════════════════════════
# MOTOR PREDICTIVO  (capa nueva, AISLADA)
# Genera predicciones.json: frases cocinadas + confianza + categoria.
# No usa red. No modifica archivos existentes. Si falla, main() la
# atrapa con try/except y el resto del monitor sigue igual.
# ═══════════════════════════════════════════════════════════════
import statistics  # (json, datetime y timedelta ya están importados arriba)

DIAS_SEM = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']

CLUSTER_WIN = 45
VENT_RECIENTE_D = 21
DIAS_MIN_ALTA = 3
NOBS_MIN_CASI_TODOS = 8
FREQ_CASI_TODOS = 0.60
DUR_POCO_MIN = 120
DUR_POCO_PARES = 3
FREC_DIAS_VENTANA = 14
FREC_DIAS_MIN = 4
AUSENCIA_DIAS = 7
AUSENCIA_SEMANAS = 21


def _ev_dt(fecha):
    return datetime.fromisoformat(fecha)

def _peso_edad(dt, ahora):
    dias = (ahora - dt).total_seconds() / 86400.0
    if dias <= 30: return 1.0
    if dias <= 60: return 0.7
    if dias <= 120: return 0.4
    return 0.2

def _hhmm(minu):
    mm = (round(minu / 15) * 15) % 1440
    return f"{mm // 60}:{mm % 60:02d}"

def _franja(minu):
    h = minu // 60
    return 'por la mañana' if h < 12 else ('por la tarde' if h < 19 else 'por la noche')

def _cat_franja(minu):
    h = minu // 60
    return 'franja_manana' if h < 12 else ('franja_tarde' if h < 19 else 'franja_noche')

def _plural_dia(d):
    return 'sábados' if d == 'sábado' else ('domingos' if d == 'domingo' else d)

def _unir(arr):
    if len(arr) == 1: return arr[0]
    return ', '.join(arr[:-1]) + ' y ' + arr[-1]

def _clusters(items):
    ordenado = sorted(items, key=lambda x: x[0])
    cl = []
    for minu, peso in ordenado:
        if cl and minu - cl[-1]['lastMin'] <= CLUSTER_WIN:
            cl[-1]['mins'].append(minu); cl[-1]['pesos'].append(peso); cl[-1]['lastMin'] = minu
        else:
            cl.append({'mins': [minu], 'pesos': [peso], 'lastMin': minu})
    out = []
    for c in cl:
        wtot = sum(c['pesos'])
        wavg = sum(m * p for m, p in zip(c['mins'], c['pesos'])) / wtot
        out.append({'rep': wavg, 'peso': wtot, 'n': len(c['mins'])})
    out.sort(key=lambda x: x['peso'], reverse=True)
    return out

def _es_consecutivo(arr):
    return len(arr) >= 3 and all(i == 0 or v == arr[i - 1] + 1 for i, v in enumerate(arr))

def _obs_de(nombre, eventos, ahora):
    porDia = {}
    for e in eventos:
        if e.get('especialidad') != nombre: continue
        # Solo nuevos y reaperturas: un 'aumento' suma cupos a una ventana ya abierta,
        # no inicia una apertura, y contaminaría la hora probable (condición acordada).
        if e.get('tipo') not in ('nuevos', 'reaperturas'): continue
        dt = _ev_dt(e['fecha']); fecha = e['fecha'][:10]; minu = dt.hour * 60 + dt.minute
        if fecha not in porDia:
            porDia[fecha] = {'dow': (dt.weekday() + 1) % 7, 'mins': [], 'peso': _peso_edad(dt, ahora),
                             'ts': dt, 'domMes': dt.day, 'mes': fecha[:7]}
        porDia[fecha]['mins'].append(minu)
    obs = list(porDia.values())
    for o in obs: o['min'] = min(o['mins'])
    return obs


def _frecuencia_diaria(obs, ahora):
    """Fracción de días hábiles (lun-vie) del período observado en los que hubo apertura."""
    if not obs:
        return 0.0
    d0 = min(o['ts'] for o in obs).date()
    d1 = ahora.date()
    habiles = sum(1 for i in range((d1 - d0).days + 1)
                  if (d0 + timedelta(days=i)).weekday() < 5)
    return (len(obs) / habiles) if habiles else 0.0


def generar_frase_cuando(nombre, eventos, ahora):
    """Devuelve (frase, confianza, categoria)."""
    obs = _obs_de(nombre, eventos, ahora)
    nObs = len(obs)
    if nObs == 0: return ("Todavía no hay suficiente historial", "baja", "aprendiendo")
    if nObs == 1: return ("No hay patrón claro todavía", "baja", "sinPatron")

    pesoTotal = sum(o['peso'] for o in obs) or 1.0
    dowPeso, dowCount, dowMins = {}, {}, {}
    for o in obs:
        dowPeso[o['dow']] = dowPeso.get(o['dow'], 0) + o['peso']
        dowCount[o['dow']] = dowCount.get(o['dow'], 0) + 1
        dowMins.setdefault(o['dow'], []).extend((m, o['peso']) for m in o['mins'])
    dowsOrden = sorted(dowPeso.keys(), key=lambda d: dowPeso[d], reverse=True)
    distintosDows = len(dowsOrden); topPeso = dowPeso[dowsOrden[0]]
    habituales = [d for d in dowsOrden if dowCount[d] >= 2 and dowPeso[d] >= 0.5 * topPeso]
    if not habituales:
        habituales = [d for d in dowsOrden if dowPeso[d] >= 0.6 * topPeso]
    pesoHab = sum(dowPeso[d] for d in habituales); habituales.sort()

    def horaDeDows(arr):
        it = []
        for d in arr: it.extend(dowMins.get(d, []))
        return _clusters(it)

    def baja(): return ("No hay patrón claro todavía", "baja", "sinPatron")

    vent = timedelta(days=VENT_RECIENTE_D)
    rec = [o for o in obs if ahora - o['ts'] <= vent]
    vie = [o for o in obs if ahora - o['ts'] > vent]
    if len(rec) >= 3 and len(vie) >= 3:
        pr, pv = {}, {}
        for o in rec: pr[o['dow']] = pr.get(o['dow'], 0) + o['peso']
        for o in vie: pv[o['dow']] = pv.get(o['dow'], 0) + o['peso']
        topR = max(pr, key=pr.get); topV = max(pv, key=pv.get)
        pesoRec = sum(o['peso'] for o in rec) or 1.0
        if topR != topV and pr[topR] >= 0.6 * pesoRec:
            cl = horaDeDows([topR])
            return (f"Últimamente vienen apareciendo turnos los {_plural_dia(DIAS_SEM[topR])} alrededor de las {_hhmm(cl[0]['rep'])} hs.", "media", "reciente")

    if distintosDows >= 5 and (topPeso / pesoTotal) < 0.45:
        cl = horaDeDows(dowsOrden)
        tieneHora = bool(cl and cl[0]['peso'] / pesoTotal >= 0.5)
        hora = _hhmm(cl[0]['rep']) if tieneHora else None
        if _frecuencia_diaria(obs, ahora) >= FREQ_CASI_TODOS:
            # Abre de verdad casi a diario
            conf = "alta" if nObs >= NOBS_MIN_CASI_TODOS else "media"
            if tieneHora:
                return (f"Suele haber turnos casi todos los días alrededor de las {hora} hs.", conf, "abundancia")
            return ("Suele haber turnos casi todos los días", conf, "abundancia")
        # Aparece en muchos días de semana, pero no casi a diario → frase honesta sin exagerar
        if tieneHora:
            return (f"Suele haber turnos varios días de la semana, alrededor de las {hora} hs.", "media", "atencion")
        return ("Suele haber turnos varios días de la semana", "media", "atencion")

    if pesoHab / pesoTotal >= 0.6:
        nombresHab = [_plural_dia(DIAS_SEM[d]) for d in habituales]
        clHab = horaDeDows(habituales); clTot = sum(c['peso'] for c in clHab) or 1.0
        if len(habituales) == 1:
            d = habituales[0]; diasD = dowCount[d]
            if (len(clHab) >= 2 and clHab[0]['n'] >= 2 and clHab[1]['n'] >= 2 and
                    clHab[1]['peso'] / clTot >= 0.30 and abs(clHab[0]['rep'] - clHab[1]['rep']) >= 90):
                dos = sorted([clHab[0]['rep'], clHab[1]['rep']])
                conf = "alta" if diasD >= DIAS_MIN_ALTA else "media"
                return (f"Suele haber turnos los {nombresHab[0]} cerca de las {_hhmm(dos[0])} hs y nuevamente alrededor de las {_hhmm(dos[1])} hs.", conf, "certero")
            if clHab[0]['n'] >= 2 and clHab[0]['peso'] / clTot >= 0.6:
                if diasD >= DIAS_MIN_ALTA:
                    return (f"Suele haber turnos los {nombresHab[0]} alrededor de las {_hhmm(clHab[0]['rep'])} hs.", "alta", "certero")
                return (f"Suele haber turnos los {nombresHab[0]} {_franja(clHab[0]['rep'])}", "media", "atencion")
            if diasD >= 2:
                return (f"Suele haber turnos los {nombresHab[0]} {_franja(clHab[0]['rep'])}", "media", "atencion")
            return baja()
        if 2 <= len(habituales) <= 4:
            diasHab = sum(dowCount[d] for d in habituales)
            if clHab and clHab[0]['peso'] / clTot >= 0.5:
                conf = "alta" if diasHab >= DIAS_MIN_ALTA else "media"
                if _es_consecutivo(habituales):
                    return (f"Suele haber turnos de {DIAS_SEM[habituales[0]]} a {DIAS_SEM[habituales[-1]]} cerca de las {_hhmm(clHab[0]['rep'])} hs.", conf, "certero")
                return (f"Suele haber turnos los {_unir(nombresHab)} cerca de las {_hhmm(clHab[0]['rep'])} hs.", conf, "certero")
            if diasHab >= 3:
                return (f"Suele haber turnos los {_unir(nombresHab)} {_franja(clHab[0]['rep'])}", "media", "atencion")
            return baja()

    meses = {o['mes'] for o in obs}
    if len(meses) >= 2:
        pIni = sum(o['peso'] for o in obs if o['domMes'] <= 7)
        pFin = sum(o['peso'] for o in obs if o['domMes'] >= 23)
        if pIni / pesoTotal >= 0.6:
            return ("Suele haber turnos durante los primeros días del mes", "media", "mensual")
        if pFin / pesoTotal >= 0.6:
            return ("Suele haber turnos hacia fin de mes", "media", "mensual")

    clTodos = _clusters([(o['min'], o['peso']) for o in obs])
    if clTodos and clTodos[0]['peso'] / pesoTotal >= 0.6 and nObs >= 3:
        return (f"Suele haber turnos {_franja(clTodos[0]['rep'])}", "media", _cat_franja(clTodos[0]['rep']))

    return baja()


def _estructura_modal(frase):
    """Deriva (hora_probable, tipo_hora_modal, texto_sin_hora) DESDE la frase que
    ya generó generar_frase_cuando. Misma fuente única: la 3ª card del modal y la
    sección 'Cuándo suele haber turnos' nunca pueden contradecirse.

    tipo_hora_modal:
      'probable' -> hay hora exacta (hora_probable = "9:30")
      'franja'   -> solo franja      (hora_probable = "mañana" | "tarde" | "noche")
      'sin_hora' -> ni hora ni franja (hora_probable = None)

    texto_sin_hora: la misma frase pero sin la hora ni la franja, para mostrar
    abajo cuando NO hay cupos sin repetir lo que ya va en la card.
    """
    m = re.search(r'las (\d{1,2}:\d{2}) hs', frase)
    if m:
        hora, tipo = m.group(1), 'probable'
    else:
        fr = re.search(r'por la (mañana|tarde|noche)', frase)
        if fr:
            hora, tipo = fr.group(1), 'franja'
        else:
            hora, tipo = None, 'sin_hora'
    txt = re.sub(
        r'\s*(?:cerca de las|alrededor de las)\s*\d{1,2}:\d{2}\s*hs'
        r'(?:\s*y nuevamente alrededor de las\s*\d{1,2}:\d{2}\s*hs)?',
        '', frase)
    txt = re.sub(r'\s*por la (?:mañana|tarde|noche)', '', txt)
    txt = txt.strip().rstrip('.').strip()
    return hora, tipo, txt


def _ultima_apertura(nombre, eventos):
    """Hora (redondeada a 15 min) de la última apertura real registrada
    (solo nuevos/reaperturas). None si la especialidad nunca abrió."""
    aps = [_ev_dt(e['fecha']) for e in eventos
           if e.get('especialidad') == nombre and e.get('tipo') in ('nuevos', 'reaperturas')]
    if not aps:
        return None
    dt = max(aps)
    return _hhmm(dt.hour * 60 + dt.minute)


def generar_frase_duracion(nombre, eventos):
    items = sorted([e for e in eventos if e.get('especialidad') == nombre], key=lambda x: x['fecha'])
    aps = [_ev_dt(e['fecha']) for e in items if e['tipo'] in ('nuevos', 'reaperturas', 'aumentos')]
    agos = [_ev_dt(e['fecha']) for e in items if e['tipo'] == 'agotados']
    dur = []
    for a in aps:
        post = [g for g in agos if 0 <= (g - a).total_seconds() <= 24 * 3600]
        if post: dur.append((min(post) - a).total_seconds() / 60.0)
    if len(dur) >= DUR_POCO_PARES and statistics.median(dur) <= DUR_POCO_MIN:
        return "Cuando aparece, suele durar poco"
    return None

def generar_frase_frecuencia(nombre, eventos, ahora):
    aps_dias = {e['fecha'][:10] for e in eventos
                if e.get('especialidad') == nombre and e['tipo'] in ('nuevos', 'reaperturas', 'aumentos')
                and (ahora - _ev_dt(e['fecha'])).total_seconds() <= FREC_DIAS_VENTANA * 86400}
    if len(aps_dias) >= FREC_DIAS_MIN:
        return "Últimamente aparece con frecuencia"
    return None

def generar_frase_ausencia(nombre, eventos, estado_actual, ahora):
    if estado_actual is None or estado_actual.get(nombre, 0) != 0: return None
    aps = [_ev_dt(e['fecha']) for e in eventos
           if e.get('especialidad') == nombre and e['tipo'] in ('nuevos', 'reaperturas', 'aumentos')]
    if not aps: return None
    dias = (ahora - max(aps)).total_seconds() / 86400.0
    if dias >= AUSENCIA_SEMANAS: return "Hace semanas sin turnos nuevos"
    if dias >= AUSENCIA_DIAS: return "Hace varios días sin turnos nuevos"
    return None


# ═══════════════════════════════════════════════════════════════
# BANNER PREDICTIVO — probabilidad CONDICIONAL de apertura próxima
# ═══════════════════════════════════════════════════════════════
# Pregunta que responde: "De las veces que era día hábil, a esta hora,
# esta especialidad estaba agotada... ¿cuántas veces abrió (nuevos/
# reaperturas, NO aumentos) dentro de los próximos 90 min?".
# Modelo escalonado: Nivel 1 (mismo día de semana) si hay evidencia
# suficiente; si no, Nivel 2 (cualquier día hábil); si tampoco, no se
# muestra. El Nivel 1 queda implementado pero "duerme" hasta tener
# ≥5 casos comparables, y se activa solo cuando el historial crece.

# Feriados nacionales AR (editable). Se excluyen como "día hábil" tanto
# para el bloqueo de hoy como para los casos comparables del historial.
FERIADOS_AR = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-03-24", "2026-04-02",
    "2026-04-03", "2026-05-01", "2026-05-25", "2026-06-17", "2026-06-20",
    "2026-07-09", "2026-08-17", "2026-10-12", "2026-11-23", "2026-12-08",
    "2026-12-25",
}
VENTANA_BANNER_MIN = 90   # ventana de apertura tras estar agotada
MIN_CASOS_BANNER   = 5    # casos comparables mínimos para confiar
PROB_MIN_BANNER    = 30   # piso de probabilidad para mostrar
MAX_BANNER         = 5    # tope de especialidades en el banner


def _es_dia_habil(fecha):
    """fecha: datetime.date → True si es lun-vie y no feriado nacional."""
    return fecha.weekday() < 5 and fecha.isoformat() not in FERIADOS_AR


def _timeline_estado(nombre, eventos):
    """Reconstruye el estado (agotada/concupos) de una especialidad como
    función escalonada a partir de las transiciones guardadas."""
    tl = []
    for e in eventos:
        if e.get("especialidad") != nombre:
            continue
        t = e.get("tipo")
        if t == "agotados":
            st = "agotada"
        elif t in ("nuevos", "reaperturas", "aumentos", "ultimos"):
            st = "concupos"
        else:
            continue
        try:
            tl.append((datetime.fromisoformat(e["fecha"]), st))
        except Exception:
            continue
    tl.sort(key=lambda x: x[0])
    return tl


def _estado_en(tl, momento):
    """Estado vigente en 'momento' = el de la última transición previa.
    None si no hay transición previa (estado desconocido → no se cuenta)."""
    last = None
    for t, st in tl:
        if t <= momento:
            last = st
        else:
            break
    return last


def calcular_chance_apertura_proxima(nombre, eventos, ahora):
    """Probabilidad condicional de que una especialidad AGOTADA abra pronto.
    Devuelve dict {especialidad, probabilidad, confianza, nivel, casos} o None.
    No bloquea por franja horaria fija: las horas sin actividad dan ~0% y el
    piso de probabilidad las descarta solas."""
    if not _es_dia_habil(ahora.date()):
        return None  # hoy no es día hábil

    H = ahora.hour
    wd = ahora.weekday()
    ventana = timedelta(minutes=VENTANA_BANNER_MIN)

    tl = _timeline_estado(nombre, eventos)
    if not tl:
        return None

    aperturas = []
    for e in eventos:
        if e.get("especialidad") == nombre and e.get("tipo") in ("nuevos", "reaperturas"):
            try:
                aperturas.append(datetime.fromisoformat(e["fecha"]))
            except Exception:
                pass

    dias = sorted({datetime.fromisoformat(e["fecha"]).date() for e in eventos})
    dias_habil = [d for d in dias if _es_dia_habil(d)]

    def evaluar(solo_wd):
        casos = aciertos = 0
        for d in dias_habil:
            if solo_wd is not None and d.weekday() != solo_wd:
                continue
            mom = datetime(d.year, d.month, d.day, H, 0, 0, tzinfo=ahora.tzinfo)
            if _estado_en(tl, mom) == "agotada":
                casos += 1
                if any(mom <= a < mom + ventana for a in aperturas):
                    aciertos += 1
        return casos, aciertos

    # Nivel 1: mismo día de semana (si hay evidencia suficiente)
    casos, aciertos = evaluar(wd)
    nivel = 1
    if casos < MIN_CASOS_BANNER:
        # Nivel 2: cualquier día hábil
        casos, aciertos = evaluar(None)
        nivel = 2
        if casos < MIN_CASOS_BANNER:
            return None  # Nivel 3: sin evidencia → no mostrar

    prob = round(100 * aciertos / casos)
    if prob < PROB_MIN_BANNER:
        return None

    return {
        "especialidad": nombre,
        "probabilidad": prob,
        "confianza": "alta" if prob >= 60 else "media",
        "nivel": nivel,
        "casos": casos,
        "aciertos": aciertos,
    }


def calcular_prob_apertura(nombre, eventos, registros, ahora):
    """Indicador de actividad de la tarjeta 'Prob. de Apertura' del modal.
    Misma métrica que venía calculando el Index: de los días monitoreados de
    los últimos 30 (sin feriados), en cuántos hubo alguna apertura.
    Devuelve {emoji, txt}."""
    hace30 = (ahora - timedelta(days=30)).date()
    aperturas = [e for e in eventos
                 if e.get("especialidad") == nombre
                 and e.get("tipo") in ("nuevos", "reaperturas", "aumentos")]
    dias_con_apertura = set()
    for e in aperturas:
        fstr = (e.get("fecha") or "")[:10]
        try:
            fd = datetime.fromisoformat(fstr).date()
        except Exception:
            continue
        if fd >= hace30 and fstr not in FERIADOS_AR:
            dias_con_apertura.add(fstr)
    dias_monit = 0
    for f in (registros or {}):
        fstr = f[:10]
        try:
            fd = datetime.fromisoformat(fstr).date()
        except Exception:
            continue
        if fd >= hace30 and fstr not in FERIADOS_AR:
            dias_monit += 1
    if not aperturas or dias_monit == 0:
        return {"emoji": "🧮", "txt": "s/datos"}
    pct = min(100, round(100 * len(dias_con_apertura) / dias_monit))
    if pct >= 40:
        return {"emoji": "🟢", "txt": "Alta"}
    elif pct >= 15:
        return {"emoji": "🟡", "txt": "Media"}
    return {"emoji": "🔴", "txt": "Baja"}


def generar_predicciones(stats, estado_actual, ahora):
    eventos = stats.get('eventos', [])
    registros = stats.get('registros', {})
    universo = {e['especialidad'] for e in eventos}
    if estado_actual: universo |= set(estado_actual.keys())
    especialidades = {}
    for nombre in sorted(universo):
        frase, conf, cat = generar_frase_cuando(nombre, eventos, ahora)
        entrada = {"cuando": frase, "confianza": conf, "categoria": cat}
        # Campos estructurados para la 3ª card del modal (derivados de la MISMA frase,
        # así la card y la sección 'Cuándo suele haber turnos' nunca se contradicen).
        hora_p, tipo_h, texto_sh = _estructura_modal(frase)
        entrada["tipo_hora_modal"] = tipo_h
        if hora_p: entrada["hora_probable"] = hora_p
        entrada["texto_sin_hora"] = texto_sh
        ult = _ultima_apertura(nombre, eventos)
        if ult: entrada["ultima_apertura"] = ult
        dur = generar_frase_duracion(nombre, eventos)
        if dur: entrada["duracion"] = dur
        frec = generar_frase_frecuencia(nombre, eventos, ahora)
        if frec: entrada["frecuencia"] = frec
        aus = generar_frase_ausencia(nombre, eventos, estado_actual, ahora)
        if aus: entrada["ausencia"] = aus
        entrada["prob_apertura"] = calcular_prob_apertura(nombre, eventos, registros, ahora)
        especialidades[nombre] = entrada

    # ── BANNER PREDICTIVO: especialidades agotadas AHORA con chance real de abrir pronto ──
    banner_items = []
    for nombre in sorted(universo):
        cupo_now = (estado_actual or {}).get(nombre, 0)
        if cupo_now and cupo_now > 0:
            continue  # solo las que están agotadas ahora
        chance = calcular_chance_apertura_proxima(nombre, eventos, ahora)
        if chance:
            # adjuntar al detalle de la especialidad (lo usa el modal)
            if nombre in especialidades:
                especialidades[nombre]["chance"] = {
                    "hora": ahora.strftime("%H:00"),
                    "probabilidad": chance["probabilidad"],
                    "confianza": chance["confianza"],
                    "casos": chance["casos"],
                    "aciertos": chance["aciertos"],
                }
            banner_items.append(chance)
    banner_items.sort(key=lambda x: -x["probabilidad"])
    banner_items = banner_items[:MAX_BANNER]

    # días hábiles del historial (para el pie del banner)
    _dias = sorted({datetime.fromisoformat(e["fecha"]).date() for e in eventos})
    dias_habil_n = len([d for d in _dias if _es_dia_habil(d)])

    banner = {
        "hora": ahora.strftime("%H:00"),
        "dias": dias_habil_n,
        "items": banner_items,
    }

    return {"generado": ahora.isoformat(), "version": 1,
            "especialidades": especialidades, "banner": banner}


# ═══════════════════════════════════════════════════════════════
# HISTORIAL DE CUPOS (velocidad reciente)
# ═══════════════════════════════════════════════════════════════
# Mantiene historial_cupos.json: por especialidad, lecturas recientes {t, c}.
# El Index lo usa para detectar si una especialidad "se está agotando rápido".
# Solo guarda especialidades con cupos > 0 y conserva una ventana corta (acotado).

def guardar_historial_cupos(estado_actual, ahora):
    VENTANA_MIN = 180   # conservar lecturas de las últimas 3 horas
    MAX_LECTURAS = 40   # tope duro de lecturas por especialidad
    hist = cargar_json(ARCHIVOS["historial_cupos"]) or {}
    t_iso = ahora.isoformat()

    # 1) Agregar la lectura actual (solo especialidades con cupos disponibles)
    for nombre, cupos in estado_actual.items():
        if cupos and cupos > 0:
            hist.setdefault(nombre, []).append({"t": t_iso, "c": cupos})

    # 2) Podar lecturas viejas y descartar especialidades sin lecturas recientes
    limpio = {}
    for nombre, lecturas in hist.items():
        recientes = []
        for l in lecturas:
            try:
                t = datetime.fromisoformat(l["t"])
                if (ahora - t).total_seconds() <= VENTANA_MIN * 60:
                    recientes.append(l)
            except Exception:
                continue
        recientes = recientes[-MAX_LECTURAS:]
        if recientes:
            limpio[nombre] = recientes

    guardar_json_seguro(limpio, ARCHIVOS["historial_cupos"])
    return limpio


# ── VELOCIDAD DE AGOTAMIENTO (portado del dashboard, lógica idéntica) ──
VEL_VENTANA_MIN = 75    # ventana reciente para medir el ritmo
VEL_ELAPSED_MIN = 10    # span mínimo de lecturas para confiar
VEL_CONSUMO_MIN = 3     # caída mínima de cupos para considerar riesgo
VEL_UMBRAL_BASE = 30    # se agota en <= 30 min → riesgo (lo modula el histórico)

def _velocidad_historica(nombre, eventos, limite_ms=7 * 24 * 60 * 60 * 1000):
    """Promedio en minutos que dura una especialidad desde que abre hasta agotarse.
    Solo modula la sensibilidad del umbral; None si no hay ciclos suficientes."""
    relevantes = sorted(
        (e for e in eventos if e.get("especialidad") == nombre
         and e.get("tipo") in ("nuevos", "reaperturas", "agotados")),
        key=lambda e: e.get("fecha", "")
    )
    pares, inicio = [], None
    for e in relevantes:
        try:
            t = datetime.fromisoformat(e["fecha"])
        except Exception:
            continue
        if e["tipo"] == "agotados":
            if inicio is not None:
                dur_ms = (t - inicio).total_seconds() * 1000
                if 0 < dur_ms < limite_ms:
                    pares.append(dur_ms / 60000)
                inicio = None
        elif inicio is None:
            inicio = t
    if len(pares) < 2:
        return None
    return round(sum(pares) / len(pares))

def _proyeccion_agotamiento(lecturas, cupo_actual):
    """Minutos estimados hasta agotarse al ritmo reciente. None si no hay confianza."""
    if not isinstance(lecturas, list) or len(lecturas) < 2:
        return None
    try:
        t_ult = datetime.fromisoformat(lecturas[-1]["t"])
    except Exception:
        return None
    recientes = []
    for l in lecturas:
        try:
            t = datetime.fromisoformat(l["t"])
            if (t_ult - t).total_seconds() <= VEL_VENTANA_MIN * 60:
                recientes.append((t, l["c"]))
        except Exception:
            continue
    if len(recientes) < 2:
        return None
    elapsed_min = (recientes[-1][0] - recientes[0][0]).total_seconds() / 60
    if elapsed_min < VEL_ELAPSED_MIN:
        return None
    consumo = 0
    for i in range(1, len(recientes)):
        delta = recientes[i - 1][1] - recientes[i][1]
        if delta > 0:
            consumo += delta
    if consumo < VEL_CONSUMO_MIN:
        return None
    ritmo = consumo / elapsed_min
    if ritmo <= 0:
        return None
    return cupo_actual / ritmo

def _se_agota_rapido(nombre, lecturas, eventos, cupo_actual):
    """Minutos proyectados si se está agotando rápido AHORA; None si no aplica."""
    proy = _proyeccion_agotamiento(lecturas, cupo_actual)
    if proy is None:
        return None
    umbral = VEL_UMBRAL_BASE
    vel_hist = _velocidad_historica(nombre, eventos)
    if vel_hist is not None:
        if vel_hist < 60:
            umbral = 45        # suele agotarse rápido → más sensible
        elif vel_hist > 180:
            umbral = 15        # suele durar mucho → exigir más evidencia
    return proy if proy <= umbral else None

def construir_alerta_velocidad(items, fecha_hora):
    """items: lista de (nombre, cupo_actual, proy_min)."""
    if not items:
        return None
    lineas = ["⚡ SE ESTÁ AGOTANDO RÁPIDO", ""]
    for nombre, cupo, proy in items:
        mins = max(1, round(proy))
        plural = "s" if cupo != 1 else ""
        lineas.append(f"{emoji_de(nombre)} {nombre}")
        lineas.append(f"   Quedan {cupo} cupo{plural} · se agotaría en ~{mins} min")
        lineas.append("")
    lineas += [
        f"🕒 {fecha_hora}",
        "",
        "👉 https://sganotti.mendoza.gov.ar/digisalud/comunicacion/solicitudturnosweb.aspx?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328",
    ]
    return "\n".join(lineas)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

# ── COMANDOS POR TELEGRAM: manejar la lista de encargos desde el chat ──
# El bot lee mensajes nuevos en cada ciclo (getUpdates). No depende de un
# marcador frágil: guarda el offset en encargos.json (que se respalda por git)
# y además descarta mensajes más viejos que 1 h, para acotar cualquier reproceso
# tras un reinicio de Railway. Todo es no crítico: si falla, el ciclo sigue igual.

COMANDOS_VENTANA_SEG = 3600  # ignorar comandos más viejos que 1 hora

def _cargar_encargos():
    data = cargar_json(ARCHIVOS["encargos"]) or {}
    palabras = data.get("palabras", [])
    if not isinstance(palabras, list):
        palabras = []
    return data, palabras

def leer_y_procesar_comandos():
    if not BOT_TOKEN or not CHAT_ID:
        return
    data, palabras = _cargar_encargos()
    offset = data.get("ultimo_update_id", 0)
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset + 1, "timeout": 0},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"getUpdates devolvió {resp.status_code} (no crítico)")
            return
        updates = resp.json().get("result", [])
    except Exception as e:
        logger.warning(f"No se pudieron leer comandos de Telegram (no crítico): {e}")
        return
    if not updates:
        return

    import time
    ahora_ts = time.time()
    max_id = offset
    respuestas = []
    cambió = False

    def _ya_esta(arg):
        return arg in [_norm_esp(p) for p in palabras]

    for upd in updates:
        uid = upd.get("update_id", 0)
        if uid > max_id:
            max_id = uid
        msg = upd.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        texto = (msg.get("text") or "").strip()
        fecha_msg = msg.get("date", 0)
        if chat != str(CHAT_ID):            # seguridad: solo tu chat
            continue
        if ahora_ts - fecha_msg > COMANDOS_VENTANA_SEG:   # descartar viejos
            continue
        if not texto.startswith("/"):
            continue
        partes = texto.split(maxsplit=1)
        cmd = partes[0].lower().lstrip("/").split("@")[0]
        arg = _norm_esp(partes[1]) if len(partes) > 1 else ""
        if cmd in ("encargo", "agregar", "add") and arg:
            if not _ya_esta(arg):
                palabras.append(arg); cambió = True
                respuestas.append(f"✓ Anotada: {arg.lower()}. Te aviso cuando aparezca.")
            else:
                respuestas.append(f"Ya la tenías anotada: {arg.lower()}.")
        elif cmd in ("sacar", "quitar", "borrar", "remove") and arg:
            nuevas = [p for p in palabras if _norm_esp(p) != arg]
            if len(nuevas) != len(palabras):
                palabras = nuevas; cambió = True
                respuestas.append(f"✓ Saqué: {arg.lower()}.")
            else:
                respuestas.append(f"No estaba en la lista: {arg.lower()}.")
        elif cmd in ("lista", "encargos", "list"):
            if palabras:
                respuestas.append("📋 Tus encargos:\n" + "\n".join(f"• {p.lower()}" for p in palabras))
            else:
                respuestas.append("No tenés encargos cargados.\nAgregá con: /encargo oftalmo")
        elif cmd in ("ayuda", "help", "start"):
            respuestas.append(
                "Comandos:\n"
                "/encargo <palabra> — anotar (ej: /encargo oftalmo)\n"
                "/sacar <palabra> — quitar\n"
                "/lista — ver lo anotado"
            )

    # Guardar SIEMPRE el offset (aunque no cambie la lista) para no reprocesar
    data["palabras"] = palabras
    data["ultimo_update_id"] = max_id
    guardar_json_seguro(data, ARCHIVOS["encargos"])

    for r in respuestas:
        enviar_telegram(r)
    if cambió:
        logger.info(f"📋 Lista de encargos actualizada: {palabras}")


def main():
    ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
    fecha_hora = ahora.strftime("%d/%m • %H:%M hs")

    logger.info("╔════════════════════════════════════════════════════╗")
    logger.info(f"║ 🏥 MONITOR PROFESIONAL - {ahora.strftime('%d/%m/%Y %H:%M:%S')} ║")
    logger.info("╚════════════════════════════════════════════════════╝")

    # Leer comandos del bot (/encargo, /sacar, /lista) antes de procesar
    leer_y_procesar_comandos()

    estado_anterior = cargar_json(ARCHIVOS["estado"]) or {}
    especialidades = consultar_api()

    if not especialidades:
        logger.critical("✗ No se pudo obtener datos de la API")
        enviar_telegram("🚨 Error: No se pudo conectar con la API del hospital")
        return

    # VERIFICAR si es primera ejecución
    es_primera_ejecucion = len(estado_anterior) == 0

    stats_db = cargar_json(ARCHIVOS["estadisticas"]) or {"eventos": [], "registros": {}}
    procesador = ProcesadorEspecialidades(especialidades, estado_anterior, stats_db, sin_baseline=es_primera_ejecucion).procesar()

    guardar_json_seguro(estado_anterior, ARCHIVOS["estado_anterior"])
    guardar_json_seguro(procesador.estado_actual, ARCHIVOS["estado"])
    hb = cargar_json(ARCHIVOS["heartbeat"]) or {}
    hb["ultima_ejecucion"] = ahora.isoformat()
    guardar_json_seguro(hb, ARCHIVOS["heartbeat"])
    total_especialidades = len(procesador.estado_actual)
    slog.ejecucion(
        estado="ok",
        especialidades=total_especialidades,
        cupos=sum(procesador.estado_actual.values()),
        con_cupos=len([c for c in procesador.estado_actual.values() if c > 0])
    )
    guardar_estadisticas(procesador.cambios, procesador.estado_actual)

    # ── CAPA PREDICTIVA (nueva, aislada): escribe predicciones.json. Nunca rompe el flujo. ──
    _predicciones = None
    try:
        _stats_pred = cargar_json(ARCHIVOS["estadisticas"]) or {"eventos": [], "registros": {}}
        _predicciones = generar_predicciones(_stats_pred, procesador.estado_actual, ahora)
        guardar_json_seguro(_predicciones, ARCHIVOS["predicciones"])
        logger.info(f"🧠 predicciones.json generado ({len(_predicciones['especialidades'])} especialidades)")
    except Exception as e:
        logger.error(f"Capa predictiva falló (no crítico, se ignora): {e}")

    # ── HISTORIAL DE CUPOS (nuevo, aislado): escribe historial_cupos.json para la velocidad. ──
    _hist = {}
    try:
        _hist = guardar_historial_cupos(procesador.estado_actual, ahora)
        logger.info(f"📉 historial_cupos.json actualizado ({len(_hist)} especialidades con cupos)")
    except Exception as e:
        logger.error(f"Historial de cupos falló (no crítico, se ignora): {e}")

    # ── ALERTA DE VELOCIDAD: especialidades que se están agotando rápido (uso personal) ──
    try:
        if CONFIG.get("alertas_velocidad", True):
            estado_vel = procesador.estado_actual or {}
            eventos_vel = (cargar_json(ARCHIVOS["estadisticas"]) or {}).get("eventos", [])
            vel_estado = cargar_json(ARCHIVOS["velocidad"]) or {}
            ya = set(vel_estado.get("alertadas", []))
            # Cerrar episodios: las ya agotadas salen de la lista y pueden volver a alertar luego
            ya = {n for n in ya if estado_vel.get(n, 0) and estado_vel[n] > 0}
            nuevas = []
            for nombre, cupo in estado_vel.items():
                if not cupo or cupo <= 0 or nombre in ya:
                    continue
                proy = _se_agota_rapido(nombre, _hist.get(nombre), eventos_vel, cupo)
                if proy is not None:
                    nuevas.append((nombre, cupo, proy))
                    ya.add(nombre)
            if nuevas:
                msg_vel = construir_alerta_velocidad(nuevas, fecha_hora)
                if msg_vel:
                    enviar_telegram(msg_vel)
                    logger.info(f"⚡ Alerta de velocidad enviada: {len(nuevas)} especialidad(es)")
            vel_estado["alertadas"] = sorted(ya)
            guardar_json_seguro(vel_estado, ARCHIVOS["velocidad"])
    except Exception as e:
        logger.error(f"Alerta de velocidad falló (no crítico, se ignora): {e}")

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

        # Muestra de la alerta de PATRÓN (usa el banner real del momento)
        alerta_p = construir_alerta_patron(_predicciones["banner"], fecha_hora) if _predicciones else None
        if alerta_p:
            enviar_telegram("🧪 EJEMPLO — ALERTA DE PATRÓN\n\n" + alerta_p)
        else:
            enviar_telegram("🧪 EJEMPLO — ALERTA DE PATRÓN\n\nSin patrón de aperturas en este momento (ninguna especialidad supera el umbral).")

        # Muestra de la alerta de VELOCIDAD (real si hay algo agotándose; si no, un ejemplo)
        _eventos_t = (cargar_json(ARCHIVOS["estadisticas"]) or {}).get("eventos", [])
        _items_v = []
        for _nom, _cup in (procesador.estado_actual or {}).items():
            if _cup and _cup > 0:
                _proy = _se_agota_rapido(_nom, _hist.get(_nom), _eventos_t, _cup)
                if _proy is not None:
                    _items_v.append((_nom, _cup, _proy))
        if _items_v:
            enviar_telegram("🧪 EJEMPLO — ALERTA DE VELOCIDAD (datos reales)\n\n" + construir_alerta_velocidad(_items_v, fecha_hora))
        else:
            _ej = construir_alerta_velocidad([("CARDIOLOGIA ADULTO", 6, 8)], fecha_hora)
            enviar_telegram("🧪 EJEMPLO — ALERTA DE VELOCIDAD (simulada, nada agotándose ahora)\n\n" + _ej)
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
    interes = [_norm_esp(e) for e in CONFIG.get("especialidades_interes", [])] + \
              [_norm_esp(p) for _d, plist in [_cargar_encargos()] for p in plist]
    interes = [k for k in dict.fromkeys(interes) if k]   # dedup, sin vacíos
    if interes and hay_cambios:
        logger.info(f"⭐ Encargos activos: {interes}")
        todas_listas = (
            procesador.cambios["nuevos"] +
            procesador.cambios["reaperturas"] +
            procesador.cambios["aumentos"] +
            procesador.cambios["ultimos"]
        )
        avisadas = set()
        for item in todas_listas:
            nom = item["nombre"]
            if nom in avisadas:
                continue
            nom_norm = _norm_esp(nom)
            if not any(kw in nom_norm for kw in interes):
                continue
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
                f"⭐ ENCARGO DISPONIBLE\n"
                f"{emoji_de(nom)} {nom}\n\n"
                f"{tipo}\n"
                f"🍀 {cupo} Cupo{plural} Disponible{plural}\n\n"
                f"🕒 {fecha_hora}\n\n"
                f"👉 https://sganotti.mendoza.gov.ar/digisalud/comunicacion/solicitudturnosweb.aspx"
                f"?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328"
            )
            enviar_telegram(msg_individual)
            avisadas.add(nom)
            logger.info(f"⭐ Aviso de encargo enviado: {nom}")

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
            alerta_patrones = construir_alerta_patron(_predicciones["banner"], fecha_hora) if _predicciones else None
            if alerta_patrones:
                enviar_telegram(alerta_patrones)
                hb_pat["ultima_alerta_patron_ts"] = ahora.isoformat()
                guardar_json_seguro(hb_pat, ARCHIVOS["heartbeat"])

    logger.info("═════════════════════════════════════════════════════")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.critical(f"Error crítico: {e}", exc_info=True)
        enviar_telegram(f"🚨 Error crítico: {str(e)[:100]}")