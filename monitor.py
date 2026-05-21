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
import json
import logging
import tempfile
import sys
import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
GITHUB_REPO = "santopayuno/monitor-turnos-hospital"
GITHUB_BRANCH = "main"
DB_URL = os.environ.get("DATABASE_URL", "")

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
    "reporte": "reporte_diario.txt"
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

def consultar_api():
    logger.info("→ Consultando API...")
    try:
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
        
        logger.info(f"✓ API: {len(especialidades)} especialidades recibidas")
        return especialidades
        
    except requests.RequestException as e:
        logger.error(f"✗ Error de red: {e}")
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"✗ Error de datos: {e}")
    except Exception as e:
        logger.error(f"✗ Error inesperado: {e}")
    
    return None

# ═══════════════════════════════════════════════════════════════
# PROCESAMIENTO
# ═══════════════════════════════════════════════════════════════

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
        nombre = self._normalizar_nombre(esp.get("descripcion", ""))
        cupo = max(0, int(esp.get("cupo", 0)))
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
            self.cambios["nuevos"].append({
                "nombre": nombre,
                "cupo_actual": cupo
            })
            logger.info(f"🆕 NUEVO: {nombre} ({cupo} cupos)")
        
        elif cupo_anterior > 0 and cupo > cupo_anterior + 10:
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
# FAVORITAS
# ═══════════════════════════════════════════════════════════════

def _es_favorita(nombre):
    favs = CONFIG.get("especialidades_interes", [])
    return nombre.upper() in [f.upper() for f in favs]

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
        
        lineas = []
        
        # ─────────────────────────────────────────────────────
        # ENCABEZADO
        # ─────────────────────────────────────────────────────
        lineas.append("🚨 NUEVOS TURNOS DISPONIBLES")
        lineas.append("🏥 HOSPITAL PERRUPATO")
        lineas.append("")
        lineas.append("━━━━━━━━━━━━━━━━━━")
        lineas.append("")
        
        # ─────────────────────────────────────────────────────
        # CAMBIOS DETECTADOS (si los hay)
        # ─────────────────────────────────────────────────────
        cambios_section = self._seccion_cambios()
        if cambios_section:
            lineas.extend(cambios_section)
            lineas.append("")
            lineas.append("━━━━━━━━━━━━━━━━━━")
            lineas.append("")
        
        # ─────────────────────────────────────────────────────
        # DISPONIBLES AHORA (si los hay)
        # ─────────────────────────────────────────────────────
        disponibles_section = self._seccion_disponibles()
        if disponibles_section:
            lineas.extend(disponibles_section)
            lineas.append("")
            lineas.append("━━━━━━━━━━━━━━━━━━")
            lineas.append("")
        
        # ─────────────────────────────────────────────────────
        # POCOS CUPOS (si los hay)
        # ─────────────────────────────────────────────────────
        pocos_section = self._seccion_pocos()
        if pocos_section:
            lineas.extend(pocos_section)
            lineas.append("")
            lineas.append("━━━━━━━━━━━━━━━━━━")
            lineas.append("")
        
        # ─────────────────────────────────────────────────────
        # SIN CUPOS (SIEMPRE visible)
        # ─────────────────────────────────────────────────────
        agotados_section = self._seccion_agotados()
        if agotados_section:
            lineas.extend(agotados_section)
            lineas.append("")
            lineas.append("━━━━━━━━━━━━━━━━━━")
            lineas.append("")
        
        # ─────────────────────────────────────────────────────
        # ESTADÍSTICAS FINALES
        # ─────────────────────────────────────────────────────
        stats_section = self._seccion_estadisticas()
        if stats_section:
            lineas.append("")
            lineas.extend(stats_section)
            lineas.append("")
            lineas.append("━━━━━━━━━━━━━━━━━━")
        
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
        
        lineas = ["🆕 CAMBIOS DETECTADOS", ""]
        
        # NUEVOS - Ordenar alfabéticamente
        nuevos_ordenados = sorted(self.cambios["nuevos"], key=lambda x: x['nombre'])
        for item in nuevos_ordenados:
            fav = "⭐ " if _es_favorita(item['nombre']) else ""
            lineas.append(f"{fav}🏥 {item['nombre']}")
            lineas.append(f"🍀 {formato_cupos_disponibles(item['cupo_actual'])}")
            lineas.append(f"📈 +{item['cupo_actual']} nuevos")
            lineas.append("")
            lineas.append("▫️▫️▫️")
            lineas.append("")
        
        # AUMENTOS - Ordenar alfabéticamente
        aumentos_ordenados = sorted(self.cambios["aumentos"], key=lambda x: x['nombre'])
        for item in aumentos_ordenados:
            fav = "⭐ " if _es_favorita(item['nombre']) else ""
            lineas.append(f"{fav}🏥 {item['nombre']}")
            lineas.append(f"🍀 {formato_cupos_disponibles(item['cupo_actual'])}")
            lineas.append(f"📈 +{item['aumento']} nuevos")
            lineas.append("")
            lineas.append("▫️▫️▫️")
            lineas.append("")
        
        # ÚLTIMOS - Ordenar alfabéticamente
        ultimos_ordenados = sorted(self.cambios["ultimos"], key=lambda x: x['nombre'])
        for item in ultimos_ordenados:
            fav = "⭐ " if _es_favorita(item['nombre']) else ""
            lineas.append(f"{fav}🏥 {item['nombre']}")
            plural = "s" if item['cupo_actual'] > 1 else ""
            lineas.append(f"⚠️ {item['cupo_actual']} Cupo{plural} Restante{plural}")
            lineas.append("")
            lineas.append("▫️▫️▫️")
            lineas.append("")
        
        # Eliminar último separador de cambios
        while lineas and lineas[-1] in ["", "▫️▫️▫️"]:
            lineas.pop()
        
        return lineas
    
    # ─────────────────────────────────────────────────────────
    # SECCIÓN: DISPONIBLES AHORA
    # ─────────────────────────────────────────────────────────
    
    def _seccion_disponibles(self):
        if not self.clasificacion["disponible"]:
            return None
        
        # Ordenar alfabéticamente
        items = sorted(self.clasificacion["disponible"], key=lambda x: x[0])
        
        lineas = [
            "🟢 DISPONIBLES AHORA",
            "",
            "┌────────────────",
            ""
        ]
        
        # Mostrar TODAS
        for nombre, cupo in items:
            fav = "⭐ " if _es_favorita(nombre) else ""
            lineas.append(f"{fav}🏥 {nombre}")
            plural = "s" if cupo > 1 else ""
            lineas.append(f"✅ {cupo} Cupo{plural}")
            lineas.append("")
        
        # Eliminar última línea vacía
        if lineas and lineas[-1] == "":
            lineas.pop()
        
        lineas.append("")
        lineas.append("└────────────────")
        
        return lineas
    
    # ─────────────────────────────────────────────────────────
    # SECCIÓN: POCOS CUPOS DISPONIBLES
    # ─────────────────────────────────────────────────────────
    
    def _seccion_pocos(self):
        especiales = self.clasificacion["pocos"] + self.clasificacion["ultimos"]
        
        if not especiales:
            return None
        
        # Ordenar alfabéticamente
        items = sorted(especiales, key=lambda x: x[0])
        
        lineas = [
            "⚠️ POCOS CUPOS DISPONIBLES",
            ""
        ]
        
        # Mostrar TODAS
        for nombre, cupo in items:
            fav = "⭐ " if _es_favorita(nombre) else ""
            icono = "⚠️" if cupo < 5 else "🟡"
            plural = "s" if cupo > 1 else ""
            lineas.append(f"{fav}🏥 {nombre}")
            lineas.append(f"{icono} {cupo} Cupo{plural}")
            lineas.append("")
        
        # Eliminar última línea vacía
        while lineas and lineas[-1] == "":
            lineas.pop()
        
        return lineas
    
    # ─────────────────────────────────────────────────────────
    # SECCIÓN: SIN CUPOS DISPONIBLES (SIEMPRE visible)
    # ─────────────────────────────────────────────────────────
    
    def _seccion_agotados(self):
        # Mostrar TODAS las especialidades con 0 cupos
        lineas = [
            "‼️ SIN CUPOS DISPONIBLES",
            ""
        ]
        
        # Obtener todas las agotadas del estado actual - Ordenar alfabéticamente
        agotadas = sorted([(nombre, cupo) for nombre, cupo in self.estado_actual.items() if cupo == 0], 
                         key=lambda x: x[0])
        
        if not agotadas:
            lineas.append("(No hay especialidades agotadas)")
            return lineas
        
        # Mostrar TODAS
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
            f"🔵 Especialidades Monitoreadas: {self.total_especialidades}",
            f"🔵 Especialidades Disponibles: {total_con_cupos}",
            f"🔵 Total de Cupos: {total_cupos}",
            "",
            "🕒 Actualizado: " + self.fecha_hora
        ]
        
        return lineas

# ═══════════════════════════════════════════════════════════════
# NOTIFICACIONES
# ═══════════════════════════════════════════════════════════════

def enviar_telegram(mensaje):
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("⚠️ Telegram no configurado")
        return False
    
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": mensaje},
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info("✓ Notificación Telegram enviada")
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
        stats = cargar_json(ARCHIVOS["estadisticas"]) or {"registros": {}, "eventos": []}
        ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
        fecha = ahora.strftime("%Y-%m-%d")
        
        if fecha not in stats["registros"]:
            stats["registros"][fecha] = []
        
        stats["registros"][fecha].append({
            "hora": ahora.strftime("%H:%M:%S"),
            "con_cupos": len([c for c in estado_actual.values() if c > 0]),
            "total_cupos": sum(estado_actual.values()),
            "cambios": len([x for x in cambios.values() if x])
        })
        
        for cambio_tipo, items in cambios.items():
            for item in items:
                stats["eventos"].append({
                    "fecha": ahora.isoformat(),
                    "tipo": cambio_tipo,
                    "especialidad": item["nombre"],
                    "cupos": item.get("cupo_actual", 0)
                })
        
        fecha_limite = (ahora - timedelta(days=90)).isoformat()
        stats["eventos"] = [e for e in stats["eventos"] if e["fecha"] > fecha_limite]
        
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
        
        reporte = f"""
┌──────────────────────────────────────┐
│  📊 REPORTE DIARIO                   │
│  {ahora.strftime('%d/%m/%Y')}
└──────────────────────────────────────┘

📈 ESTADÍSTICAS

Monitoreos realizados: {len(registros)}
Promedio con cupos: {sum(r['con_cupos'] for r in registros) // len(registros) if registros else 0}
Total cupos abiertos: {sum(r['total_cupos'] for r in registros)}

🆕 CAMBIOS DETECTADOS: {len(eventos)}

Nuevas aperturas: {sum(1 for e in eventos if e['tipo'] == 'nuevos')}
Aumentos: {sum(1 for e in eventos if e['tipo'] == 'aumentos')}
Últimos cupos: {sum(1 for e in eventos if e['tipo'] == 'ultimos')}
Agotamientos: {sum(1 for e in eventos if e['tipo'] == 'agotados')}

Reporte generado: {ahora.strftime('%d/%m/%Y %H:%M:%S')}
"""
        
        return reporte
    except Exception as e:
        logger.error(f"Error generando reporte: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# SINCRONIZACIÓN GITHUB
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# BASE DE DATOS POSTGRESQL
# ═══════════════════════════════════════════════════════════════

def guardar_en_db(estado_actual, cambios, ahora):
    if not DB_URL:
        logger.debug("DB sync desactivado (sin DATABASE_URL)")
        return
    try:
        import psycopg2
        ahora_naive = ahora.replace(tzinfo=None)
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        for nombre, cupos in estado_actual.items():
            cur.execute("""
                INSERT INTO estado_turnos (nombre, cupos, actualizado_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (nombre) DO UPDATE
                SET cupos = EXCLUDED.cupos, actualizado_at = EXCLUDED.actualizado_at
            """, (nombre, cupos, ahora_naive))

        fecha = ahora.strftime("%Y-%m-%d")
        hora = ahora.strftime("%H:%M:%S")
        con_cupos = len([c for c in estado_actual.values() if c > 0])
        total_cupos = sum(estado_actual.values())
        n_cambios = sum(len(v) for v in cambios.values())
        cur.execute("""
            INSERT INTO estadisticas_registros (fecha, hora, con_cupos, total_cupos, cambios)
            VALUES (%s, %s, %s, %s, %s)
        """, (fecha, hora, con_cupos, total_cupos, n_cambios))

        for tipo, items in cambios.items():
            for item in items:
                cur.execute("""
                    INSERT INTO estadisticas_eventos (fecha, tipo, especialidad, cupos)
                    VALUES (%s, %s, %s, %s)
                """, (ahora_naive, tipo, item["nombre"], item.get("cupo_actual", 0)))

        conn.commit()
        cur.close()
        conn.close()
        logger.info("🗄️  DB sync: estado, registros y eventos guardados")
    except Exception as e:
        logger.warning(f"⚠️ Error guardando en DB: {e}")


def guardar_monitor_status(estado, ahora, total_esp, total_cupos, ciclos_hoy, error_msg=None):
    if not DB_URL:
        return
    try:
        import psycopg2
        ahora_naive = ahora.replace(tzinfo=None)
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO monitor_status
                (ultima_consulta, estado, especialidades_contadas, cupos_totales, ciclos_hoy, error_msg)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (ahora_naive, estado, total_esp, total_cupos, ciclos_hoy, error_msg))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"⚠️ Error guardando monitor status: {e}")


def _github_get_sha(session, archivo):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{archivo}?ref={GITHUB_BRANCH}"
    r = session.get(url, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("sha")

def push_a_github(archivos):
    if not GITHUB_TOKEN:
        logger.debug("GitHub sync desactivado (sin token)")
        return
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    session = requests.Session()
    session.headers.update(headers)
    subidos = []
    for archivo in archivos:
        if not os.path.exists(archivo):
            continue
        try:
            with open(archivo, "r", encoding="utf-8") as f:
                contenido = f.read()
            sha = _github_get_sha(session, archivo)
            body = {
                "message": f"auto: actualización {archivo}",
                "content": base64.b64encode(contenido.encode("utf-8")).decode("utf-8"),
                "branch": GITHUB_BRANCH,
            }
            if sha:
                body["sha"] = sha
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{archivo}"
            r = session.put(url, json=body, timeout=15)
            r.raise_for_status()
            subidos.append(archivo)
        except Exception as e:
            logger.warning(f"⚠️ No se pudo subir {archivo} a GitHub: {e}")
    if subidos:
        logger.info(f"☁️  GitHub sync: {', '.join(subidos)}")

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
    
    procesador = ProcesadorEspecialidades(especialidades, estado_anterior).procesar()
    
    guardar_json_seguro(procesador.estado_actual, ARCHIVOS["estado"])
    guardar_estadisticas(procesador.cambios, procesador.estado_actual)
    guardar_en_db(procesador.estado_actual, procesador.cambios, ahora)

    total_especialidades = len(procesador.estado_actual)
    
    # Enviar notificación SOLO si hay nuevos o aumentos
    if procesador.cambios["nuevos"] or procesador.cambios["aumentos"]:
        constructor = ConstructorMensajeTelegram(
            procesador.cambios,
            procesador.clasificacion,
            fecha_hora,
            procesador.estado_actual,
            total_especialidades
        )
        mensaje = constructor.construir()
        if mensaje:
            enviar_telegram(mensaje)
    else:
        logger.info("ℹ️ Sin nuevos o aumentos para notificar")
    
    if CONFIG.get("generar_reporte_diario"):
        hora = ahora.strftime("%H:%M")
        if hora == CONFIG.get("hora_reporte", "23:55"):
            reporte = generar_reporte_diario()
            if reporte:
                with open(ARCHIVOS["reporte"], "w", encoding="utf-8") as f:
                    f.write(reporte)
                enviar_telegram(reporte)
    
    stats = cargar_json(ARCHIVOS["estadisticas"]) or {"registros": {}}
    ciclos_hoy = len(stats["registros"].get(ahora.strftime("%Y-%m-%d"), []))
    total_cupos_final = sum(procesador.estado_actual.values())
    guardar_monitor_status("ok", ahora, total_especialidades, total_cupos_final, ciclos_hoy)

    push_a_github([ARCHIVOS["estado"], ARCHIVOS["estadisticas"]])

    logger.info("═════════════════════════════════════════════════════")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.critical(f"Error crítico: {e}", exc_info=True)
        enviar_telegram(f"🚨 Error crítico: {str(e)[:100]}")
