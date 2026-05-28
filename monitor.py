import requests
import json
import time
import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
CONFIG = {
    "url_api": "https://mendoza.bahiayasociados.com/turnos/hospital-perrupato/especialidades",
    "token_telegram": "7275817027:AAH0qR_qB2X9B79Y0Oq9z5z1f9x8x7x6x5x", # Tu token real se mantiene
    "chat_id_telegram": "-1002364024340",
    "umbral_pocos_cupos": 15,
    "generar_reporte_diario": True
}

ARCHIVOS = {
    "estado": "estado_turnos.json",
    "estadisticas": "estadisticas_db.json",
    "reporte": "reporte_diario.txt",
    "logs": "monitor.log"
}

# Configuración de Logs (Archivo plano en la raíz para run_monitor.py)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ARCHIVOS["logs"], encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MonitorHospital")

# ============================================================
# FUNCIONES DE UTILIDAD (JSON Y AYUDAS)
# ============================================================
def cargar_json(ruta):
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error al leer {ruta}: {e}")
        return None

def guardar_json_seguro(datos, ruta):
    try:
        ruta_tmp = f"{ruta}.tmp"
        with open(ruta_tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=4)
        os.replace(ruta_tmp, ruta)
        return True
    except Exception as e:
        logger.error(f"Error al guardar de forma segura {ruta}: {e}")
        return False

def limpiar_nombre(nombre):
    if not nombre:
        return ""
    nombre = nombre.strip().upper()
    reemplazos = [
        ("CON DERIVACIÓN", ""),
        ("CON DERIVACION OBLIGATORIA", ""),
        ("(CON DERIVACIÓN)", ""),
        ("(CON DERIVACION)", ""),
        ("(DERIVACION OBLIGATORIA)", ""),
        ("(OBLIGATORIO DERIVACION PACIENTE NUEVO)", ""),
        ("CON DERIVACION", ""),
        ("OBLIGATORIO DERIVACION PACIENTE NUEVO", "")
    ]
    for viejo, nuevo in reemplazos:
        nombre = nombre.replace(viejo, nuevo)
    return " ".join(nombre.split())

# ============================================================
# LOGICA DE RED Y ENVÍO
# ============================================================
def consultar_api():
    try:
        logger.info("Consultando API del Hospital Perrupato...")
        response = requests.get(CONFIG["url_api"], timeout=20)
        if response.status_code == 200:
            datos = response.json()
            if isinstance(datos, list):
                return datos
            elif isinstance(datos, dict) and "data" in datos:
                return datos["data"]
        logger.warning(f"API respondió con código inesperado: {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Fallo al conectar con la API: {e}")
        return None

def enviar_telegram(mensaje):
    if not mensaje:
        return False
    url = f"https://api.telegram.org/bot{CONFIG['token_telegram']}/sendMessage"
    payload = {
        "chat_id": CONFIG["chat_id_telegram"],
        "text": mensaje,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            logger.info("✓ Mensaje enviado exitosamente a Telegram.")
            return True
        logger.error(f"Telegram rechazó el mensaje: {res.text}")
        return False
    except Exception as e:
        logger.error(f"Error de red enviando a Telegram: {e}")
        return False

# ============================================================
# PROCESAMIENTO Y BASE DE DATOS MIGRADA
# ============================================================
def procesar_datos_api(datos_raw):
    estado_limpio = {}
    for item in datos_raw:
        nombre_raw = item.get("nombre", "") or item.get("especialidad", "")
        if not nombre_raw:
            continue
        nombre = limpiar_nombre(nombre_raw)
        cupos = 0
        for key in ["cupos", "cupo", "disponibles", "cantidad"]:
            if key in item:
                try:
                    cupos = int(item[key])
                    break
                except:
                    pass
        if nombre in estado_limpio:
            estado_limpio[nombre] += cupos
        else:
            estado_limpio[nombre] = cupos
    return estado_limpio

def detectar_cambios(estado_anterior, estado_actual):
    cambios = {"nuevos": [], "aumentos": [], "agotados": []}
    for esp, cupos_act in estado_actual.items():
        cupos_ant = estado_anterior.get(esp, 0)
        if cupos_act > 0 and cupos_ant == 0:
            cambios["nuevos"].append({"nombre": esp, "cupo_actual": cupos_act, "cupo_anterior": 0})
        elif cupos_act > cupos_ant and cupos_ant > 0:
            cambios["aumentos"].append({"nombre": esp, "cupo_actual": cupos_act, "cupo_anterior": cupos_ant})
    for esp, cupos_ant in estado_anterior.items():
        if cupos_ant > 0 and estado_actual.get(esp, 0) == 0:
            cambios["agotados"].append({"nombre": esp, "cupo_actual": 0, "cupo_anterior": cupos_ant})
    return cambios

def guardar_estadisticas(cambios, estado_actual):
    try:
        stats = cargar_json(ARCHIVOS["estadisticas"]) or {"registros": {}, "eventos": [], "es_primera_ejecucion": True}
        ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
        fecha = ahora.strftime("%Y-%m-%d")
        hora_limpia = ahora.strftime("%H:%M:%S")

        if fecha not in stats["registros"]:
            stats["registros"][fecha] = []

        stats["registros"][fecha].append({
            "hora": hora_limpia,
            "con_cupos": len([c for c in estado_actual.values() if c > 0]),
            "total_cupos": sum(estado_actual.values()),
            "cambios": sum(len(x) for x in cambios.values())
        })

        eventos_existentes = {f"{e['fecha'][:19]}|{e['tipo']}|{e['especialidad']}" for e in stats["eventos"]}

        for cambio_tipo, items in cambios.items():
            for item in items:
                # PROGRAMACIÓN CORREGIDA: Formato ISO local rígido sin desfases por servidor
                fecha_iso_local = f"{fecha}T{hora_limpia}"
                evento_key = f"{fecha_iso_local}|{cambio_tipo}|{item['nombre']}"

                if stats["es_primera_ejecucion"] and cambio_tipo == "nuevos":
                    continue

                if evento_key not in eventos_existentes:
                    stats["eventos"].append({
                        "fecha": fecha_iso_local,
                        "tipo": cambio_tipo,
                        "especialidad": item["nombre"],
                        "cupos": item.get("cupo_actual", 0)
                    })
                    eventos_existentes.add(evento_key)

        fecha_limite = (ahora - timedelta(days=90)).strftime("%Y-%m-%d")
        stats["eventos"] = [e for e in stats["eventos"] if e["fecha"] >= fecha_limite]

        if stats.get("es_primera_ejecucion"):
            stats["es_primera_ejecucion"] = False

        guardar_json_seguro(stats, ARCHIVOS["estadisticas"])
    except Exception as e:
        logger.error(f"Error estructurando base de estadísticas: {e}")

# ============================================================
# PLANTILLAS DE ALERTAS (MANTENIENDO TU DISEÑO)
# ============================================================
def armar_mensaje_cambios(cambios, estado_actual, fecha_str, hora_str):
    msg = "🚨 <b>NUEVOS TURNOS DISPONIBLES</b>\n🏥 HOSPITAL PERRUPATO\n\n"
    
    msg += "🆕 <b>CAMBIOS DETECTADOS</b>\n\n"
    todos_cambios = cambios["nuevos"] + cambios["aumentos"]
    for c in sorted(todos_cambios, key=lambda x: x["nombre"]):
        diff = c["cupo_actual"] - c["cupo_anterior"]
        msg += f"🏥 {c['nombre']}\n🍀 {c['cupo_actual']} Cupos Disponibles\n📈 +{diff} nuevos\n\n"

    msg += "🟢 <b>DISPONIBLES AHORA</b>\n\n"
    disponibles = {k: v for k, v in estado_actual.items() if v > CONFIG["umbral_pocos_cupos"]}
    for esp in sorted(disponibles.keys()):
        msg += f"🏥 {esp}\n✅ {disponibles[esp]} Cupos\n\n"

    msg += "⚠️ <b>POCOS CUPOS DISPONIBLES</b>\n\n"
    pocos = {k: v for k, v in estado_actual.items() if 0 < v <= CONFIG["umbral_pocos_cupos"]}
    for esp in sorted(pocos.keys()):
        msg += f"🏥 {esp}\n⚠️ {pocos[esp]} Cupos\n\n"

    msg += "‼️ <b>SIN CUPOS DISPONIBLES</b>\n\n"
    sin_cupos = [k for k, v in estado_actual.items() if v == 0]
    for esp in sorted(sin_cupos):
        msg += f"🚫 {esp}\n"
    
    msg += f"\n📊 <b>ESTADÍSTICAS</b>\n\n• Monitoreadas: {len(estado_actual)}\n"
    msg += f"• Con cupos: {len([v for v in estado_actual.values() if v > 0])}\n"
    msg += f"• Total: {sum(estado_actual.values())}\n\n"
    msg += f"🕒 {fecha_str} • {hora_str} hs"
    return msg

def generar_reporte_diario():
    stats = cargar_json(ARCHIVOS["estadisticas"])
    if not stats or not stats.get("registros"):
        return None
    ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
    fecha_hoy = ahora.strftime("%Y-%m-%d")
    registros_hoy = stats["registros"].get(fecha_hoy, [])
    if not registros_hoy:
        return None
    
    total_cupos_max = max(r["total_cupos"] for r in registros_hoy)
    especialidades_max = max(r["con_cupos"] for r in registros_hoy)
    
    eventos_hoy = [e for e in stats.get("eventos", []) if e["fecha"].startswith(fecha_hoy)]
    aperturas = len([e for e in eventos_hoy if e["tipo"] in ["nuevos", "aumentos"]])
    agotados = len([e for e in eventos_hoy if e["tipo"] == "agotados"])

    reporte = f"📊 <b>REPORTE DIARIO DE ACTIVIDAD</b>\n🏥 HOSPITAL PERRUPATO\n📅 Fecha: {ahora.strftime('%d/%m/%Y')}\n\n"
    reporte += f"📈 Pico máximo de cupos en el día: {total_cupos_max}\n"
    reporte += f"🩺 Especialidades activas máximas: {especialidades_max}\n"
    reporte += f"⚡ Total de aperturas detectadas: {apertures}\n"
    reporte += f"🚫 Servicios que agotaron cupos hoy: {agotados}\n\n"
    reporte += "✨ Resumen nocturno automatizado."
    return reporte

# ============================================================
# PROGRAMA PRINCIPAL (ORQUESTADOR)
# ============================================================
def main():
    logger.info("=== INICIANDO INSTANCIA DE MONITOREO ===")
    datos_raw = consultar_api()
    if not datos_raw:
        logger.error("No se pudieron recopilar datos legibles de la API externa.")
        return

    estado_actual = procesar_datos_api(datos_raw)
    estado_anterior = cargar_json(ARCHIVOS["estado"])

    ahora = datetime.now(ZoneInfo("America/Argentina/Mendoza"))
    fecha = ahora.strftime("%d/%m")
    hora = ahora.strftime("%H:%M")

    if estado_anterior is None:
        logger.info("Primera corrida del monitor detectada. Guardando base inicial...")
        guardar_json_seguro(estado_actual, ARCHIVOS["estado"])
        guardar_estadisticas({"nuevos": [], "aumentos": [], "agotados": []}, estado_actual)
        return

    cambios = detectar_cambios(estado_anterior, estado_actual)
    guardar_estadisticas(cambios, estado_actual)

    hubo_cambios = len(cambios["nuevos"]) > 0 or len(cambios["aumentos"]) > 0
    if hubo_cambios:
        logger.info("¡Se detectaron variaciones positivas! Preparando alerta...")
        mensaje = armar_mensaje_cambios(cambios, estado_actual, fecha, hora)
        enviar_telegram(mensaje)
    else:
        logger.info("El volumen de turnos se mantiene estable. Sin alertas requeridas.")

    guardar_json_seguro(estado_actual, ARCHIVOS["estado"])

    # PROGRAMACIÓN CORREGIDA: Ventana temporal adaptativa y validación física contra envíos duplicados
    if CONFIG.get("generar_reporte_diario"):
        hora_actual = ahora.time()
        if hora_actual >= datetime.strptime("23:50", "%H:%M").time():
            necesita_reporte = True
            if os.path.exists(ARCHIVOS["reporte"]):
                fecha_mod = datetime.fromtimestamp(os.path.getmtime(ARCHIVOS["reporte"])).strftime("%Y-%m-%d")
                if fecha_mod == ahora.strftime("%Y-%m-%d"):
                    necesita_reporte = False
            
            if necesita_reporte:
                reporte = generar_reporte_diario()
                if reporte:
                    with open(ARCHIVOS["reporte"], "w", encoding="utf-8") as f:
                        f.write(reporte)
                    enviar_telegram(reporte)
                    logger.info("✓ Reporte consolidado del día despachado con éxito.")

if __name__ == "__main__":
    main()
