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
    "heartbeat": "heartbeat.json"
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
    LOG_PATH = "logs/monitor_structured.jsonl"
    MAX_LINES = 5000

    @staticmethod
    def _escribir(evento: dict):
        try:
            os.makedirs("logs", exist_ok=True)
            linea = json.dumps(evento, ensure_ascii=False) + "\n"

            if os.path.exists(StructuredLogger.LOG_PATH):
                with open(StructuredLogger.LOG_PATH, "r", encoding="utf-8") as f:
                    lineas = f.readlines()
                if len(lineas) >= StructuredLogger.MAX_LINES:
                    with open(StructuredLogger.LOG_PATH, "w", encoding="utf-8") as f:
                        f.writelines(lineas[-(StructuredLogger.MAX_LINES - 1000):])

            with open(StructuredLogger.LOG_PATH, "a", encoding="utf-8") as f:
                f.write(linea)
        except Exception as e:
            logger.warning(f"StructuredLogger error: {e}")

    @staticmethod
    def ejecucion(estado: str, especialidades: int, cupos: int, con_cupos: int):
        StructuredLogger._escribir({
            "ts": datetime.now().isoformat(),
            "evento": "ejecucion",
            "estado": estado,
            "especialidades": especialidades,
            "cupos_total": cupos,
            "con_cupos": con_cupos
        })

    @staticmethod
    def cambio(tipo: str, especialidad: str, cupos: int):
        StructuredLogger._escribir({
            "ts": datetime.now().isoformat(),
            "evento": "cambio",
            "tipo": tipo,
            "especialidad": especialidad,
            "cupos": cupos
        })

    @staticmethod
    def telegram(tipo: str, exito: bool, detalle: str = ""):
        StructuredLogger._escribir({
            "ts": datetime.now().isoformat(),
            "evento": "telegram",
            "tipo": tipo,
            "exito": exito,
            "detalle": detalle
        })

    @staticmethod
    def error(contexto: str, mensaje: str):
        StructuredLogger._escribir({
            "ts": datetime.now().isoformat(),
            "evento": "error",
            "contexto": contexto,
            "mensaje": mensaje
        })

slog = StructuredLogger()


def cargar_config():
    if os.path.exists(ARCHIVOS["config"]):
        try:
            with open(ARCHIVOS["config"], "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Config corrompido, usando defaults")
    return {"especialidades_interes": [], "generar_reporte_diario": True}

CONFIG = cargar_config()


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


def formato_cupos_disponibles(cupo):
    if cupo == 1:
        return "1 Cupo Disponible"
    return f"{cupo} Cupos Disponibles"


def _consultar_api_una_vez():
    session = crear_sesion_reintentos()
    response = session.post(
        API_URL,
        json={"nombrePlantilla": "PLT_PUBLIC_ESPE_TURNOS_PERRUPATO", "dni": ""},
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30
    )
    response.raise_for_status()

    data = response.json()
    especialidades = json.loads(data["d"])

    if len(especialidades) < 20:
        raise ValueError("Respuesta API inválida")

    return especialidades


def consultar_api(max_intentos=3, espera_segundos=10):
    for intento in range(max_intentos):
        try:
            return _consultar_api_una_vez()
        except Exception as e:
            logger.warning(f"Intento {intento+1} falló: {e}")
            time.sleep(espera_segundos)

    return None


class ProcesadorEspecialidades:
    def __init__(self, especialidades, estado_anterior):
        self.especialidades = especialidades
        self.estado_anterior = estado_anterior or {}
        self.estado_actual = {}
        self.cambios = {
            "nuevos": [],
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
        nombre = esp.get("descripcion", "").strip().upper()

        try:
            cupo = max(0, int(esp.get("cupo") or 0))
        except:
            cupo = 0

        # 🔴 FIX ÚNICO APLICADO
        suspendido = esp.get("suspendido", False)

        disponible = cupo > 0 and not suspendido

        self.estado_actual[nombre] = cupo
        anterior = self.estado_anterior.get(nombre, 0)

        self._detectar_cambios(nombre, cupo, anterior, disponible)

        if disponible:
            self._clasificar(nombre, cupo)

    def _detectar_cambios(self, nombre, cupo, anterior, disponible):
        if anterior == 0 and disponible:
            self.cambios["nuevos"].append({"nombre": nombre, "cupo_actual": cupo})

        elif anterior > 0 and cupo > anterior:
            self.cambios["aumentos"].append({
                "nombre": nombre,
                "cupo_anterior": anterior,
                "cupo_actual": cupo,
                "aumento": cupo - anterior
            })

        elif 1 <= cupo < 5 and anterior >= 5:
            self.cambios["ultimos"].append({"nombre": nombre, "cupo_actual": cupo})

        elif cupo == 0 and anterior > 0:
            self.cambios["agotados"].append({"nombre": nombre})


    def _clasificar(self, nombre, cupo):
        if cupo >= 20:
            self.clasificacion["disponible"].append((nombre, cupo))
        elif cupo >= 5:
            self.clasificacion["pocos"].append((nombre, cupo))
        else:
            self.clasificacion["ultimos"].append((nombre, cupo))


def main():
    ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))

    estado_anterior = cargar_json("estado_turnos.json") or {}
    especialidades = consultar_api()

    if not especialidades:
        return

    procesador = ProcesadorEspecialidades(especialidades, estado_anterior).procesar()

    guardar_json_seguro(procesador.estado_actual, "estado_turnos.json")

    total_especialidades = len(procesador.estado_actual)

    slog.ejecucion(
        estado="ok",
        especialidades=total_especialidades,
        cupos=sum(procesador.estado_actual.values()),
        con_cupos=len([c for c in procesador.estado_actual.values() if c > 0])
    )

    print("OK")


if __name__ == "__main__":
    main()