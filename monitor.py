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

        # VALIDACIÓN: Si recibimos muy pocas especialidades, algo está mal
        if len(especialidades) < 20:
            logger.warning(f"⚠️ API devolvió solo {len(especialidades)} especialidades (esperaba ~30+)")
            logger.warning("Posible error en API, ignorando respuesta")
            return None

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

        # ENCABEZADO (con doble salto después)
        lineas.append("🚨 NUEVOS TURNOS DISPONIBLES")
        lineas.append("🏥 HOSPITAL PERRUPATO")
        lineas.append("")
        lineas.append("")

        # CAMBIOS DETECTADOS (si los hay)
        cambios_section = self._seccion_cambios()
        if cambios_section:
            lineas.extend(cambios_section)
            lineas.append("")
            lineas.append("")

        # DISPONIBLES AHORA (si los hay)
        disponibles_section = self._seccion_disponibles()
        if disponibles_section:
            lineas.extend(disponibles_section)
            lineas.append("")
            lineas.append("")

        # POCOS CUPOS (si los hay)
        pocos_section = self._seccion_pocos()
        if pocos_section:
            lineas.extend(pocos_section)
            lineas.append("")
            lineas.append("")

        # SIN CUPOS (SIEMPRE visible)
        agotados_section = self._seccion_agotados()
        if agotados_section:
            lineas.extend(agotados_section)
            lineas.append("")
            lineas.append("")

        # ESTADÍSTICAS FINALES
        stats_section = self._seccion_estadisticas()
        if stats_section:
            lineas.extend(stats_section)

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
            cupo = item['cupo_actual']
            plural = "s" if cupo > 1 else ""
            lineas.append(f"🏥 {item['nombre']}")
            lineas.append(f"🍀 {formato_cupos_disponibles(cupo)}")
            lineas.append(f"📈 +{cupo} nuevo{plural}")
            lineas.append("")

        # AUMENTOS - Ordenar alfabéticamente
        aumentos_ordenados = sorted(self.cambios["aumentos"], key=lambda x: x['nombre'])
        for item in aumentos_ordenados:
            aumento = item['aumento']
            plural = "s" if aumento > 1 else ""
            lineas.append(f"🏥 {item['nombre']}")
            lineas.append(f"🍀 {formato_cupos_disponibles(item['cupo_actual'])}")
            lineas.append(f"📈 +{aumento} nuevo{plural}")
            lineas.append("")

        # ÚLTIMOS - Ordenar alfabéticamente
        ultimos_ordenados = sorted(self.cambios["ultimos"], key=lambda x: x['nombre'])
        for item in ultimos_ordenados:
            lineas.append(f"🏥 {item['nombre']}")
            plural = "s" if item['cupo_actual'] > 1 else ""
            lineas.append(f"⚠️ {item['cupo_actual']} Cupo{plural} Restante{plural}")
            lineas.append("")

        # Eliminar última línea vacía
        while lineas and lineas[-1] == "":
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

        lineas = ["🟢 DISPONIBLES AHORA", ""]

        # Mostrar TODAS
        for nombre, cupo in items:
            lineas.append(f"🏥 {nombre}")
            plural = "s" if cupo > 1 else ""
            lineas.append(f"✅ {cupo} Cupo{plural}")
            lineas.append("")

        # Eliminar última línea vacía
        while lineas and lineas[-1] == "":
            lineas.pop()

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
            plural = "s" if cupo > 1 else ""
            lineas.append(f"🏥 {nombre}")
            lineas.append(f"⚠️ {cupo} Cupo{plural}")
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
            "📊 ESTADÍSTICAS",
            "",
            f"• Monitoreadas: {self.total_especialidades}",
            f"• Con cupos: {total_con_cupos}",
            f"• Total: {total_cupos}",
            "",
            f"🕒 {self.fecha_hora}"
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

    procesador = ProcesadorEspecialidades(especialidades, estado_anterior).procesar()

    guardar_json_seguro(procesador.estado_actual, ARCHIVOS["estado"])
    guardar_json_seguro({"ultima_ejecucion": ahora.isoformat()}, ARCHIVOS["heartbeat"])
    guardar_estadisticas(procesador.cambios, procesador.estado_actual)

    total_especialidades = len(procesador.estado_actual)

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

    # Enviar notificación SOLO si hay nuevos o aumentos (después de primera ejecución)
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
        if hora == CONFIG.get("hora_reporte_diario", "23:55"):
            reporte = generar_reporte_diario()
            if reporte:
                with open(ARCHIVOS["reporte"], "w", encoding="utf-8") as f:
                    f.write(reporte)
                enviar_telegram(reporte)

    logger.info("═════════════════════════════════════════════════════")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.critical(f"Error crítico: {e}", exc_info=True)
        enviar_telegram(f"🚨 Error crítico: {str(e)[:100]}")