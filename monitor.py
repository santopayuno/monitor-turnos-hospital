"""
🏥 MONITOR DE TURNOS - HOSPITAL PERRUPATO
Sistema profesional de monitoreo automático

Características:
- Consulta API cada 5 minutos
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
    "estado_anterior": "estado_anterior.json"
}

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

def _consultar_api_una_vez():
    """Intento único de consulta a la API. Lanza excepción si falla."""
    session = crear_sesion_reintentos()
    response = session.post(
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

        elif cupo_anterior > 0 and cupo - cupo_anterior >= 10:
            self.cambios["aumentos"].append({
                "nombre": nombre,
                "cupo_anterior": cupo_anterior,
                "cupo_actual": cupo,
                "aumento": cupo - cupo_anterior
            })
            logger.info(f"📈 AUMENTO: {nombre} ({cupo_anterior} → {cupo}, +{cupo - cupo_anterior})")

        elif cupo_anterior >= 5 and 1 <= cupo < 5:
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
            any(self.cambios.values()) or
            any(self.clasificacion.values())
        )

    # ─────────────────────────────────────────────────────────
    # SECCIÓN: CAMBIOS DETECTADOS
    # ─────────────────────────────────────────────────────────

    def _seccion_cambios(self):
        if not any([self.cambios["nuevos"], self.cambios["aumentos"], 
                    self.cambios["ultimos"], self.cambios["agotados"]]):
            return None

        # Encabezado sin línea vacía después del separador de cierre
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

        ultimos_ordenados = sorted(self.cambios["ultimos"], key=lambda x: x['nombre'])
        for item in ultimos_ordenados:
            plural = "s" if item['cupo_actual'] > 1 else ""
            todos_items.append([
                f"🏥 {item['nombre']}",
                f"⚠️ {item['cupo_actual']} Cupo{plural} Restante{plural}",
            ])

        # Agregar items con 1 línea vacía ENTRE ellos (no al final)
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

    def _seccion_disponibles(self):
        if not self.clasificacion["disponible"]:
            return None

        items = sorted(self.clasificacion["disponible"], key=lambda x: x[0])
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
        especiales = self.clasificacion["pocos"] + self.clasificacion["ultimos"]

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

        # Limpiar eventos antiguos (90 días)
        fecha_limite = (ahora - timedelta(days=90)).isoformat()
        stats["eventos"] = [e for e in stats["eventos"] if e["fecha"] > fecha_limite]

        # Limpiar registros diarios antiguos (90 días)
        fecha_limite_registros = (ahora - timedelta(days=90)).strftime("%Y-%m-%d")
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

def detectar_patrones_apertura(hora_objetivo):
    """
    Analiza el historial de eventos y avisa si alguna especialidad
    suele abrir turnos en la hora_objetivo.
    Solo notifica si hay al menos 3 aperturas históricas en esa hora
    y la especialidad no tiene cupos ahora mismo.
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
            if e.get("tipo") not in ("nuevos", "aumentos"):
                continue
            try:
                hora = datetime.fromisoformat(e["fecha"]).hour
            except Exception:
                continue
            esp = e["especialidad"]
            if esp not in aperturas_por_hora:
                aperturas_por_hora[esp] = {}
            aperturas_por_hora[esp][hora] = aperturas_por_hora[esp].get(hora, 0) + 1

        # Filtrar: especialidades que suelen abrir en hora_objetivo (mínimo 3 veces)
        # y que ahora mismo NO tienen cupos (si ya tienen, no hace falta avisar)
        candidatas = []
        for esp, horas in aperturas_por_hora.items():
            frecuencia = horas.get(hora_objetivo, 0)
            # Verificar mínimo 5 aperturas en al menos 3 días distintos
        dias_distintos = len(set(
            e["fecha"][:10] for e in eventos
            if e.get("especialidad") == esp
            and e.get("tipo") in ("nuevos", "aumentos")
            and datetime.fromisoformat(e["fecha"]).hour == hora_objetivo
        ))
        if frecuencia >= 5 and dias_distintos >= 3 and estado_actual.get(esp, 0) == 0:
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
        enviar_telegram("🚨 Error: No se pudo conectar con la API del hospital")
        return

    # VERIFICAR si es primera ejecución
    es_primera_ejecucion = len(estado_anterior) == 0

    stats_db = cargar_json(ARCHIVOS["estadisticas"]) or {"eventos": [], "registros": {}}
    procesador = ProcesadorEspecialidades(especialidades, estado_anterior, stats_db).procesar()

    guardar_json_seguro(estado_anterior, ARCHIVOS["estado_anterior"])
    guardar_json_seguro(procesador.estado_actual, ARCHIVOS["estado"])
    guardar_json_seguro({"ultima_ejecucion": ahora.isoformat()}, ARCHIVOS["heartbeat"])
    total_especialidades = len(procesador.estado_actual)
    slog.ejecucion(
        estado="ok",
        especialidades=total_especialidades,
        cupos=sum(procesador.estado_actual.values()),
        con_cupos=len([c for c in procesador.estado_actual.values() if c > 0])
    )
    guardar_estadisticas(procesador.cambios, procesador.estado_actual)

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

    # Aplicar filtro de especialidades de interés si está configurado
    interes = [e.upper().strip() for e in CONFIG.get("especialidades_interes", [])]
    cambios_filtrados = procesador.cambios

    if interes:
        cambios_filtrados = {
            "nuevos":      [c for c in procesador.cambios["nuevos"]      if c["nombre"].upper() in interes],
            "reaperturas": [c for c in procesador.cambios["reaperturas"] if c["nombre"].upper() in interes],
            "aumentos":    [c for c in procesador.cambios["aumentos"]    if c["nombre"].upper() in interes],
            "ultimos":     [c for c in procesador.cambios["ultimos"]     if c["nombre"].upper() in interes],
            "agotados":    [c for c in procesador.cambios["agotados"]    if c["nombre"].upper() in interes],
        }
        logger.info(f"🎯 Filtro activo: {len(interes)} especialidades de interés")

    # Enviar notificación SOLO si hay nuevos o aumentos (después de primera ejecución)
    if cambios_filtrados["nuevos"] or cambios_filtrados["reaperturas"] or cambios_filtrados["aumentos"]:
        constructor = ConstructorMensajeTelegram(
            cambios_filtrados,
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
        if interes:
            logger.info("ℹ️ Sin nuevos o aumentos en especialidades de interés")
        else:
            logger.info("ℹ️ Sin nuevos o aumentos para notificar")

    # Alerta urgente separada para últimos cupos (1-4 cupos restantes)
    if cambios_filtrados["ultimos"]:
        lineas = ["🚨 ÚLTIMOS CUPOS — URGENTE", "🏥 HOSPITAL PERRUPATO", ""]
        for item in sorted(cambios_filtrados["ultimos"], key=lambda x: x["cupo_actual"]):
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
        logger.info(f"🚨 Alerta urgente enviada: {len(cambios_filtrados['ultimos'])} especialidad(es) con últimos cupos")

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

# Detección de patrones: avisar UNA sola vez por hora (solo al minuto 45-59 de cada hora)
    if CONFIG.get("alertas_patrones", True):
        if ahora.minute >= 45:
            hora_siguiente = (ahora.hour + 1) % 24
            # Flag para no repetir: guardar en heartbeat la última hora de alerta
            hb = cargar_json(ARCHIVOS["heartbeat"]) or {}
            ultima_alerta_hora = hb.get("ultima_alerta_patron_hora", -1)
            if ultima_alerta_hora != hora_siguiente:
                alerta_patrones = detectar_patrones_apertura(hora_siguiente)
                if alerta_patrones:
                    enviar_telegram(alerta_patrones)
                    hb["ultima_alerta_patron_hora"] = hora_siguiente
                    guardar_json_seguro(hb, ARCHIVOS["heartbeat"])

    logger.info("═════════════════════════════════════════════════════")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.critical(f"Error crítico: {e}", exc_info=True)
        enviar_telegram(f"🚨 Error crítico: {str(e)[:100]}")