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

DATA_DIR = os.getenv("DATA_DIR", "/data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    DATA_DIR = "."   # entornos sin /data (ej. test de GitHub): usa carpeta local
def _d(nombre):
    return os.path.join(DATA_DIR, nombre)

ARCHIVOS = {
    "estado": _d("estado_turnos.json"),
    "estadisticas": _d("estadisticas_db.json"),
    "config": "config.json",
    "logs": "monitor.log",
    "reporte": _d("reporte_diario.txt"),
    "heartbeat": _d("heartbeat.json"),
    "estado_anterior": _d("estado_anterior.json"),
    "predicciones": _d("predicciones.json"),
    "historial_cupos": _d("historial_cupos.json"),
    "encargos": _d("encargos.json"),
    "archivo_diario": _d("archivo_diario.json")
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

# Todas las especialidades usan el mismo ícono que el dashboard.
def emoji_de(nombre):
    return "🩺"

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

        # "Disponible" con la MISMA regla que usa la página oficial del hospital:
        # no suspendida + tiene cupos + la fecha tope no venció.
        # suspendido por defecto False (igual que la web, que hace !esp.suspendido):
        # así no se pierde una apertura si la API omitiera el campo.
        suspendido = bool(esp.get("suspendido", False))
        vigente = self._fechatope_vigente(esp.get("fechatope"))
        disponible = cupo > 0 and not suspendido and vigente

        # cupo_efectivo = 0 si NO está realmente disponible (suspendida con cupos,
        # o fecha vencida). Así, cuando se libera, la transición 0→N se detecta
        # como apertura limpia; y si una abierta se suspende/vence, se ve como agotada.
        cupo_efectivo = cupo if disponible else 0

        self.estado_actual[nombre] = cupo_efectivo
        cupo_anterior = self.estado_anterior.get(nombre, 0)

        self._detectar_cambios(nombre, cupo_efectivo, cupo_anterior, disponible)

        if disponible:
            self._clasificar(nombre, cupo_efectivo)
        else:
            self.clasificacion["agotado"].append((nombre, 0))

    def _fechatope_vigente(self, fechatope):
        """True si la fecha tope no venció (o no hay fecha). Falla en seguro:
        si no se puede interpretar, asume vigente (no peor que ignorarla)."""
        if not fechatope:
            return True
        try:
            txt = str(fechatope).strip()
            m = re.match(r"/Date\((\d+)", txt)        # formato .NET /Date(ms)/
            if m:
                tope = datetime.fromtimestamp(int(m.group(1)) / 1000,
                                              ZoneInfo("America/Argentina/Mendoza"))
            else:
                tope = datetime.fromisoformat(txt)
                if tope.tzinfo is None:
                    tope = tope.replace(tzinfo=ZoneInfo("America/Argentina/Mendoza"))
            ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
            return ahora <= tope
        except Exception:
            return True   # formato inesperado → no excluimos (sin regresión)

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

        SEP = "────────────"
        LINK = ("https://sganotti.mendoza.gov.ar/digisalud/comunicacion/"
                "solicitudturnosweb.aspx?plantilla=PLT_PUBLIC_ESPE_TURNOS_PERRUPATO&multiempresa=837328")

        def bloque(nombre, cupo, icono, sufijo="", nota=""):
            """Una especialidad: su nombre en un renglón y el cupo debajo (más una nota si va)."""
            unidad = "Cupo" if cupo == 1 else "Cupos"
            filas = [f"{emoji_de(nombre)} {nombre}", f"{icono} {cupo} {unidad}{sufijo}"]
            if nota:
                filas.append(nota)
            return filas

        # Cada especialidad aparece en UN SOLO cajón, por prioridad de arriba a abajo.
        ya = set()
        cajones = []

        def agregar(titulo, items, arma):
            grupo = []
            for it in sorted(items, key=lambda x: x["nombre"]):
                n = it["nombre"]
                if n in ya:
                    continue
                ya.add(n)
                if grupo:
                    grupo.append("")      # un renglón en blanco entre especialidades
                grupo.extend(arma(it))
            if grupo:
                cajones.append([SEP, titulo, SEP] + grupo)

        # 1) Nuevos  2) Reaperturas  3) Aumentos  (la novedad de esta pasada)
        agregar("🆕 NUEVOS TURNOS", self.cambios.get("nuevos", []),
                lambda it: bloque(it["nombre"], it.get("cupo_actual", 0), "☘️", " Disponibles"))

        agregar("🔄 REAPERTURAS", self.cambios.get("reaperturas", []),
                lambda it: bloque(it["nombre"], it.get("cupo_actual", 0), "☘️", " Disponibles",
                                  (f"⚡ Reabre · agotada {it['veces_agotada']}x antes"
                                   if it.get("veces_agotada") else "⚡ Reabre")))

        agregar("📈 SUMARON CUPOS", self.cambios.get("aumentos", []),
                lambda it: bloque(it["nombre"], it.get("cupo_actual", 0), "☘️", " Disponibles",
                                  f"📈 Sumó {it.get('aumento', 0)}"))

        # 4) Disponibles (20+)  5) Pocos (6-19)  6) Últimos (1-5)  7) Sin cupos
        #    Mismos cortes e íconos que las viñetas del dashboard.
        disponibles, pocos, ultimos, agotados = [], [], [], []
        for nombre, cupo in sorted(self.estado_actual.items()):
            if nombre in ya:
                continue
            if cupo >= 20:
                if disponibles: disponibles.append("")
                disponibles.extend(bloque(nombre, cupo, "☘️"))
            elif cupo >= 6:
                if pocos: pocos.append("")
                pocos.extend(bloque(nombre, cupo, "⚠️"))
            elif cupo > 0:
                if ultimos: ultimos.append("")
                ultimos.extend(bloque(nombre, cupo, "‼️"))
            else:
                agotados.append(f"✖️ {nombre}")

        if disponibles:
            cajones.append([SEP, "☘️ DISPONIBLES AHORA", SEP] + disponibles)
        if pocos:
            cajones.append([SEP, "⚠️ POCOS CUPOS DISPONIBLES", SEP] + pocos)
        if ultimos:
            cajones.append([SEP, "‼️ ÚLTIMOS CUPOS DISPONIBLES", SEP] + ultimos)
        if agotados:
            cajones.append([SEP, "✖️ SIN CUPOS DISPONIBLES", SEP] + agotados)

        # Encabezado honesto: "nuevos" solo si de verdad hubo novedad en esta pasada
        hubo_novedad = bool(self.cambios.get("nuevos") or
                            self.cambios.get("reaperturas") or
                            self.cambios.get("aumentos"))
        encabezado = "🚨 NUEVOS TURNOS DISPONIBLES" if hubo_novedad else "📋 ESTADO DE TURNOS"

        lineas = [encabezado, "🏥 HOSPITAL PERRUPATO"]
        for i, caj in enumerate(cajones):
            lineas += ["", "", ""] if i == 0 else ["", ""]
            lineas.extend(caj)

        total_con = len([c for c in self.estado_actual.values() if c > 0])
        total_cupos = sum(self.estado_actual.values())
        lineas += [
            "", "", "",
            "📊 ESTADÍSTICAS",
            f"• Monitoreadas: {self.total_especialidades}",
            f"• Con cupos: {total_con}",
            f"• Total: {total_cupos}",
            "", "",
            f"🕒 {self.fecha_hora}",
            f"👉 {LINK}",
        ]
        return "\n".join(lineas)


    def _hay_contenido(self):
        return (
            bool(self.cambios.get("nuevos")) or
            bool(self.cambios.get("reaperturas")) or
            bool(self.cambios.get("aumentos")) or
            any(self.clasificacion.values())
        )

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
        mantener_archivo_diario()

    except Exception as e:
        logger.error(f"Error guardando estadísticas: {e}")

# ═══════════════════════════════════════════════════════════════
# ARCHIVO HISTÓRICO DIARIO (permanente)
# ═══════════════════════════════════════════════════════════════
# Resumen por día y especialidad que NO vence nunca, aunque el detalle
# fino de estadisticas_db.json se vaya borrando. Sirve para, con los
# años, ver cómo se comporta cada época del año.
#
# Regla: acá van SOLO datos crudos y sumables (conteos, sumas, repartos
# por hora). Nada de promedios ni conclusiones: la estación del año se
# deduce después, a partir de la fecha. Lo que no se guarde hoy, no se
# recupera mañana.
#
# El análisis por época todavía NO está escrito (hacen falta años de
# datos). Este bloque solo junta la materia prima.

ARCHIVO_DIARIO_VERSION = 1


def _resumen_dia_especialidades(eventos_dia):
    """Resumen por especialidad de un día, a partir de sus eventos."""
    esp = {}

    def get(n):
        if n not in esp:
            esp[n] = {"aperturas": 0, "aumentos": 0, "agotamientos": 0,
                      "turnos_liberados": 0, "cupo_max": 0,
                      "horas_apertura": {}, "horas_agotamiento": {},
                      "duraciones": []}
        return esp[n]

    ordenados = sorted(eventos_dia, key=lambda x: x.get("fecha", ""))

    for e in ordenados:
        nombre = e.get("especialidad")
        if not nombre:
            continue
        try:
            hora = str(_ev_dt(e["fecha"]).hour)
        except Exception:
            continue
        s = get(nombre)
        tipo = e.get("tipo")
        cupos = e.get("cupos") or 0
        if cupos > s["cupo_max"]:
            s["cupo_max"] = cupos
        if tipo in ("nuevos", "reaperturas"):
            s["aperturas"] += 1
            # En una apertura, "cupos" es lo que se liberó (venía de 0)
            s["turnos_liberados"] += cupos
            s["horas_apertura"][hora] = s["horas_apertura"].get(hora, 0) + 1
        elif tipo == "aumentos":
            # No se suma a turnos_liberados: "cupos" es el total nuevo, no el incremento
            s["aumentos"] += 1
        elif tipo == "agotados":
            s["agotamientos"] += 1
            s["horas_agotamiento"][hora] = s["horas_agotamiento"].get(hora, 0) + 1

    # Duraciones: se cuenta cada ciclo apertura → agotamiento del mismo día
    abiertos = {}
    for e in ordenados:
        nombre = e.get("especialidad")
        if nombre not in esp:
            continue
        try:
            dt = _ev_dt(e["fecha"])
        except Exception:
            continue
        tipo = e.get("tipo")
        if tipo in ("nuevos", "reaperturas") and nombre not in abiertos:
            abiertos[nombre] = dt
        elif tipo == "agotados" and nombre in abiertos:
            minutos = int((dt - abiertos.pop(nombre)).total_seconds() / 60)
            if minutos >= 0:
                esp[nombre]["duraciones"].append(minutos)

    return esp


def mantener_archivo_diario():
    """Rellena los días que falten y recalcula hoy y ayer. Los días viejos no se tocan."""
    try:
        stats = cargar_json(ARCHIVOS["estadisticas"]) or {}
        eventos = stats.get("eventos", [])
        registros = stats.get("registros", {})
        if not eventos and not registros:
            return

        archivo = cargar_json(ARCHIVOS["archivo_diario"]) or {}
        dias = archivo.get("dias") or {}

        ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
        hoy = ahora.strftime("%Y-%m-%d")
        ayer = (ahora - timedelta(days=1)).strftime("%Y-%m-%d")

        por_dia = {}
        for e in eventos:
            f = (e.get("fecha") or "")[:10]
            if f:
                por_dia.setdefault(f, []).append(e)

        agregados = 0
        for f in sorted(set(registros.keys()) | set(por_dia.keys())):
            ya_estaba = f in dias
            reciente = f in (hoy, ayer)
            if ya_estaba and not reciente:
                continue                      # día viejo: congelado
            dias[f] = {
                # "en_vivo" = medido mientras pasaba · "reconstruido" = armado
                # después desde el detalle, con criterios de medición distintos
                "origen": "en_vivo" if reciente else "reconstruido",
                "lecturas": len(registros.get(f, [])),   # cobertura: cuánto se miró ese día
                "especialidades": _resumen_dia_especialidades(por_dia.get(f, []))
            }
            if not ya_estaba:
                agregados += 1

        archivo["version"] = ARCHIVO_DIARIO_VERSION
        archivo["dias"] = dias
        guardar_json_seguro(archivo, ARCHIVOS["archivo_diario"])
        if agregados:
            logger.info(f"📚 Archivo histórico: +{agregados} día(s) · total {len(dias)}")

    except Exception as e:
        logger.error(f"Error actualizando archivo histórico: {e}")


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

        # ACTIVIDAD DE AYER: ventana de 24 hs. hacia atrás (de las 8 de ayer a las 8 de hoy).
        # El resumen sale una vez por día, así que cada uno toma justo lo que pasó desde
        # el anterior: sin agujeros ni repeticiones entre un día y el siguiente.
        desde = ahora - timedelta(days=1)
        ayer = desde.strftime("%Y-%m-%d")

        def _en_ventana(iso):
            try:
                return desde <= datetime.fromisoformat(iso) <= ahora
            except Exception:
                return False

        eventos_ayer = [e for e in stats["eventos"] if _en_ventana(e.get("fecha", ""))]

        registros_ayer = []
        for dia in (ayer, fecha):
            for r in stats["registros"].get(dia, []):
                try:
                    dt = datetime.fromisoformat(f"{dia}T{r['hora']}").replace(tzinfo=ahora.tzinfo)
                    if desde <= dt <= ahora:
                        registros_ayer.append(r)
                except Exception:
                    pass

        # Especialidades con cupos ahora
        estado_actual = cargar_json(ARCHIVOS["estado"]) or {}
        con_cupos = [(nombre, cupo) for nombre, cupo in estado_actual.items() if cupo > 0]
        con_cupos.sort(key=lambda x: x[0])
        sin_cupos = [nombre for nombre, cupo in estado_actual.items() if cupo == 0]

        # Aperturas del día (desde las 00:00). Se cuentan reaperturas: son el 89% de
        # lo que abre; con solo "nuevos" la sección quedaba casi siempre vacía.
        nuevas_hoy = list({e["especialidad"] for e in eventos if e["tipo"] in ("nuevos", "reaperturas")})
        nuevas_hoy.sort()

        # Construir mensaje
        lineas = [
            f"🌅 RESUMEN MATUTINO",
            f"🏥 HOSPITAL PERRUPATO",
            f"📅 {ahora.strftime('%d/%m/%Y')}",
            "", "",
            "────────────",
            "📊 ESTADO ACTUAL",
            "────────────",
            f"• Especialidades monitoreadas: {len(estado_actual)}",
            f"• Con cupos disponibles: {len(con_cupos)}",
            f"• Sin cupos: {len(sin_cupos)}",
            f"• Total cupos: {sum(cupo for _, cupo in con_cupos)}",
        ]

        if con_cupos:
            lineas += ["", "", "────────────", "☘️ DISPONIBLES AHORA", "────────────"]
            for nombre, cupo in con_cupos:
                plural = "s" if cupo > 1 else ""
                lineas.append(f"{emoji_de(nombre)} {nombre}")
                lineas.append(f"☘️ {cupo} Cupo{plural}")

        if nuevas_hoy:
            lineas += ["", "", "────────────", "🆕 ABRIERON HOY", "────────────"]
            for nombre in nuevas_hoy:
                lineas.append(f"{emoji_de(nombre)} {nombre}")

        lineas += [
            "", "",
            "────────────",
            "📈 ACTIVIDAD DE AYER",
            "────────────",
            f"• Monitoreos realizados: {len(registros_ayer)}",
            f"• Cambios detectados: {len(eventos_ayer)}",
            f"• Nuevas aperturas: {sum(1 for e in eventos_ayer if e['tipo'] in ('nuevos', 'reaperturas'))}",
            f"• Agotamientos: {sum(1 for e in eventos_ayer if e['tipo'] == 'agotados')}",
            "", "",
            f"🕒 Generado: {ahora.strftime('%d/%m • %H:%M hs.')}",
        ]

        return "\n".join(lineas)
    except Exception as e:
        logger.error(f"Error generando reporte: {e}")
        return None


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
                return (f"Suele haber turnos los {nombresHab[0]} cerca de las {_hhmm(dos[0])} hs. y nuevamente alrededor de las {_hhmm(dos[1])} hs.", conf, "certero")
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
        r'\s*(?:cerca de las|alrededor de las)\s*\d{1,2}:\d{2}\s*hs\.?'
        r'(?:\s*y nuevamente alrededor de las\s*\d{1,2}:\d{2}\s*hs\.?)?',
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
MIN_CASOS_BANNER   = 8    # casos comparables mínimos para confiar
PROB_MIN_BANNER    = 50   # piso de probabilidad para mostrar
MAX_BANNER         = 5    # tope de especialidades en el banner
RECENCIA_FUERA_D   = 21   # sin apertura real hace 21+ días → fuera del banner


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


def calcular_chance_apertura_proxima(nombre, eventos, ahora, registros=None):
    """Chance condicional de que una especialidad AGOTADA abra pronto.
    Etapa actual: solo Nivel 2 (cualquier día hábil), fracción cruda, base en
    días monitoreados reales (registros) y corte por recencia. El Nivel 1
    (mismo día de semana) queda apagado: con pocas semanas hay ~5 casos por día
    de semana y una racha corta se lee como 100% (infla). Reactivable con más
    historial. Devuelve {especialidad, probabilidad, casos, aciertos} o None."""
    if not _es_dia_habil(ahora.date()):
        return None  # hoy no es día hábil

    H = ahora.hour
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

    # Corte por recencia: sin apertura real en los últimos N días → fuera
    if not aperturas:
        return None
    if (ahora - max(aperturas)).days >= RECENCIA_FUERA_D:
        return None

    # Días monitoreados reales (registros), no solo los días con eventos
    if registros:
        dias = sorted({datetime.fromisoformat(d[:10]).date() for d in registros})
    else:
        dias = sorted({datetime.fromisoformat(e["fecha"]).date() for e in eventos})
    dias_habil = [d for d in dias if _es_dia_habil(d)]

    # Nivel 2: cualquier día hábil
    casos = aciertos = 0
    for d in dias_habil:
        mom = datetime(d.year, d.month, d.day, H, 0, 0, tzinfo=ahora.tzinfo)
        if _estado_en(tl, mom) == "agotada":
            casos += 1
            if any(mom <= a < mom + ventana for a in aperturas):
                aciertos += 1
    if casos < MIN_CASOS_BANNER:
        return None

    prob = round(100 * aciertos / casos)
    if prob < PROB_MIN_BANNER:
        return None

    return {
        "especialidad": nombre,
        "probabilidad": prob,
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
    # La franja que se evalúa arranca en la hora en punto y dura VENTANA_BANNER_MIN.
    # Se mandan las dos puntas para que el cartel diga la franja completa y no solo el arranque.
    _franja_ini = ahora.replace(minute=0, second=0, microsecond=0)
    _franja_fin = _franja_ini + timedelta(minutes=VENTANA_BANNER_MIN)
    banner_items = []
    for nombre in sorted(universo):
        cupo_now = (estado_actual or {}).get(nombre, 0)
        if cupo_now and cupo_now > 0:
            continue  # solo las que están agotadas ahora
        chance = calcular_chance_apertura_proxima(nombre, eventos, ahora, registros)
        if chance:
            # adjuntar al detalle de la especialidad (lo usa el modal)
            if nombre in especialidades:
                especialidades[nombre]["chance"] = {
                    "hora": _franja_ini.strftime("%H:%M"),
                    "hora_fin": _franja_fin.strftime("%H:%M"),
                    "probabilidad": chance["probabilidad"],
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
        "hora": _franja_ini.strftime("%H:%M"),
        "hora_fin": _franja_fin.strftime("%H:%M"),
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


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

# ── COMANDOS POR TELEGRAM: manejar la lista de encargos desde el chat ──
# El bot lee mensajes nuevos en cada ciclo (getUpdates). No depende de un
# marcador frágil: guarda el offset en encargos.json (en el volumen persistente de Railway)
# y además descarta mensajes más viejos que 1 h, para acotar cualquier reproceso
# tras un reinicio de Railway. Todo es no crítico: si falla, el ciclo sigue igual.

COMANDOS_VENTANA_SEG = 3600  # ignorar comandos más viejos que 1 hora

def _cargar_encargos():
    data = cargar_json(ARCHIVOS["encargos"]) or {}
    palabras = data.get("palabras", [])
    if not isinstance(palabras, list):
        palabras = []
    return data, palabras

MSG_COMANDOS = (
    "🤖 COMANDOS\n\n"
    "✅ Agregar: /encargo, /agregar o /add <especialidad>\n"
    "ej: /encargo oftalmo\n"
    "❌ Quitar: /sacar, /quitar o /borrar <especialidad>\n"
    "📝 /lista — ver lo que anotaste\n"
    "☘️ /estado — turnos disponibles ahora\n"
    "❓ ? o /ayuda — este mensaje"
)


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
        if texto == "?":                    # "?" a secas = ayuda
            texto = "/ayuda"
        if not texto.startswith("/"):
            continue
        partes = texto.split(maxsplit=1)
        cmd = partes[0].lower().lstrip("/").split("@")[0]
        arg = _norm_esp(partes[1]) if len(partes) > 1 else ""
        if cmd in ("encargo", "agregar", "add"):
            if not arg:
                respuestas.append(f"📝 FALTA LA ESPECIALIDAD\n\n✅ Ejemplo: /{cmd} oftalmo")
            elif not _ya_esta(arg):
                palabras.append(arg); cambió = True
                respuestas.append(f"✅ ANOTADA\n\n🩺 {arg.lower()}.\n👍 Te aviso cuando aparezca")
            else:
                respuestas.append(f"📝 YA LA TENÍAS ANOTADA\n\n🩺 {arg.lower()}.")
        elif cmd in ("sacar", "quitar", "borrar", "remove"):
            if not arg:
                respuestas.append(f"📝 FALTA LA ESPECIALIDAD\n\n✅ Ejemplo: /{cmd} oftalmo")
            else:
                nuevas = [p for p in palabras if _norm_esp(p) != arg]
                if len(nuevas) != len(palabras):
                    palabras = nuevas; cambió = True
                    respuestas.append(f"❌ SAQUÉ\n\n🩺 {arg.lower()}.")
                else:
                    respuestas.append(f"📝 NO ESTABA EN LA LISTA\n\n🩺 {arg.lower()}.")
        elif cmd in ("lista", "encargos", "list"):
            if palabras:
                respuestas.append("📝 TUS ENCARGOS\n\n" + "\n".join(f"• {p.lower()}" for p in palabras))
            else:
                respuestas.append("📝 NO TENÉS ENCARGOS\n\n✅ Agregá con: /encargo oftalmo")
        elif cmd in ("estado", "turnos", "turno"):
            est = cargar_json(ARCHIVOS["estado"]) or {}
            disp = sorted([(n, c) for n, c in est.items() if isinstance(c, int) and c > 0], key=lambda x: -x[1])
            if disp:
                filas = "\n".join(f"🩺 {n}\n☘️ {c} Cupo{'s' if c != 1 else ''}" for n, c in disp)
                respuestas.append(f"────────────\n☘️ TURNOS DISPONIBLES ({len(disp)})\n────────────\n\n{filas}")
            else:
                respuestas.append("✖️ AHORA MISMO NO HAY TURNOS DISPONIBLES")
        else:
            # /ayuda, ? y también cualquier comando que no exista
            respuestas.append(MSG_COMANDOS)

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
    fecha_hora = ahora.strftime("%d/%m • %H:%M hs.")

    logger.info("╔════════════════════════════════════════════════════╗")
    logger.info(f"║ 🏥 MONITOR PROFESIONAL - {ahora.strftime('%d/%m/%Y %H:%M:%S')} ║")
    logger.info("╚════════════════════════════════════════════════════╝")

    # Leer comandos del bot (/encargo, /sacar, /lista) antes de procesar
    leer_y_procesar_comandos()

    estado_anterior = cargar_json(ARCHIVOS["estado"]) or {}
    especialidades = consultar_api()

    if not especialidades:
        logger.critical("✗ No se pudo obtener datos de la API")
        enviar_telegram("❌ ERROR\n\n🏥 No se pudo conectar con la API del hospital.")
        # Salir con código ≠ 0: así run_monitor NO le manda el ping de "estoy vivo"
        # a Healthchecks, y el aviso por mail (dead-man's-switch) salta aunque el
        # Telegram de arriba no se haya podido enviar (ej.: corte de red total).
        sys.exit(1)

    # VERIFICAR si es primera ejecución
    # Re-fijar la base SIN emitir eventos: en el primer arranque, o la primera vez
    # tras adoptar el modelo de "cupo efectivo" (suspendido/fechatope). Evita
    # agotados falsos de transición que ensuciarían el historial.
    hb = cargar_json(ARCHIVOS["heartbeat"]) or {}
    es_primera_ejecucion = len(estado_anterior) == 0
    migrar_efectivo = not hb.get("modelo_efectivo", False)
    sin_baseline = es_primera_ejecucion or migrar_efectivo
    if migrar_efectivo and not es_primera_ejecucion:
        logger.info("🔁 Re-fijando base por nuevo modelo de cupo efectivo (sin emitir eventos)")

    stats_db = cargar_json(ARCHIVOS["estadisticas"]) or {"eventos": [], "registros": {}}
    procesador = ProcesadorEspecialidades(especialidades, estado_anterior, stats_db, sin_baseline=sin_baseline).procesar()

    guardar_json_seguro(estado_anterior, ARCHIVOS["estado_anterior"])
    guardar_json_seguro(procesador.estado_actual, ARCHIVOS["estado"])
    hb["ultima_ejecucion"] = ahora.isoformat()
    hb["modelo_efectivo"] = True
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

    # ── HISTORIAL DE CUPOS: escribe historial_cupos.json, que el dashboard usa
    #    para detectar si una especialidad se está agotando rápido. ──
    _hist = {}
    try:
        _hist = guardar_historial_cupos(procesador.estado_actual, ahora)
        logger.info(f"📉 historial_cupos.json actualizado ({len(_hist)} especialidades con cupos)")
    except Exception as e:
        logger.error(f"Historial de cupos falló (no crítico, se ignora): {e}")

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

    # ✓ PRIMERA EJECUCIÓN o RE-BASELINE: NO enviar Telegram, solo guardar estado
    if sin_baseline:
        logger.info("🎯 BASE FIJADA (primera ejecución o migración)")
        logger.info(f"   ✓ Estado base guardado ({total_especialidades} especialidades)")
        logger.info("   ℹ️ No se envía notificación en este ciclo")
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
                    ("‼️ ÚLTIMOS CUPOS", procesador.cambios["ultimos"]),
                ] if item in lista
            )
            plural = "s" if cupo > 1 else ""
            msg_individual = (
                f"📌 ENCARGO DISPONIBLE\n\n\n"
                f"────────────\n"
                f"{tipo}\n"
                f"────────────\n"
                f"{emoji_de(nom)} {nom}\n"
                f"☘️ {cupo} Cupo{plural} Disponible{plural}\n\n\n"
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
            if 0 <= (hora_actual_min - hora_config_min) <= 7:
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

    logger.info("═════════════════════════════════════════════════════")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.critical(f"Error crítico: {e}", exc_info=True)
        enviar_telegram(f"❌ ERROR\n\n🏥 {str(e)[:100]}")