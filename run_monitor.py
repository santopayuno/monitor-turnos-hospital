#!/usr/bin/env python3
"""
Monitor Perrupato en Railway — proceso 24/7:
  - Corre monitor.py en loop cada 5 min
  - Sirve los JSON de /data por HTTP con CORS (para el dashboard)
  - YA NO pushea datos a git. El código sigue viniendo de git al arrancar.
"""
import subprocess
import sys
import os
import json
import time
import shutil
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.chdir(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR  = os.getenv("DATA_DIR", "/data")
CICLO_SEG = int(os.getenv("CICLO_SEG", "300"))   # 5 min
PORT      = int(os.getenv("PORT", "8080"))       # Railway inyecta PORT

try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    DATA_DIR = "."

# Archivos que el dashboard puede pedir por HTTP
SERVIBLES = {
    "estado_turnos.json", "estado_anterior.json", "estadisticas_db.json",
    "heartbeat.json", "historial_cupos.json", "predicciones.json",
    "encargos.json", "archivo_diario.json",
}


def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.stdout:
            print(r.stdout)
        return r.returncode == 0
    except Exception as e:
        print(f"cmd error: {e}")
        return False


def pull_codigo():
    """Trae el código de GitHub al arrancar (solo si no hay repo local)."""
    if not os.path.exists(".git"):
        token = os.getenv("GITHUB_TOKEN", "")
        url = f"https://{token}@github.com/santopayuno/monitor-turnos-hospital.git"
        run_cmd(["git", "init"])
        run_cmd(["git", "config", "user.email", "railway@monitor.local"])
        run_cmd(["git", "config", "user.name", "Railway Monitor"])
        run_cmd(["git", "remote", "add", "origin", url])
        run_cmd(["git", "fetch", "origin", "main"])
        run_cmd(["git", "reset", "--hard", "origin/main"])
        print("✅ Código sincronizado de GitHub")


def sembrar_data():
    """Primera vez: si /data está vacío pero el repo trae los JSON, los copia."""
    for nombre in SERVIBLES:
        destino = os.path.join(DATA_DIR, nombre)
        origen = nombre  # copia local traída del repo
        if not os.path.exists(destino) and os.path.exists(origen):
            try:
                shutil.copy2(origen, destino)
                print(f"🌱 Sembrado {nombre} en {DATA_DIR}")
            except Exception as e:
                print(f"⚠️ No se pudo sembrar {nombre}: {e}")


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")

    def do_GET(self):
        nombre = self.path.lstrip("/").split("?")[0]
        if nombre in SERVIBLES:
            ruta = os.path.join(DATA_DIR, nombre)
            if os.path.exists(ruta):
                try:
                    with open(ruta, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    pass
            self.send_response(404); self._cors(); self.end_headers()
            return
        if nombre in ("", "health"):
            self.send_response(200); self._cors(); self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404); self._cors(); self.end_headers()

    def log_message(self, *a):
        pass  # silencia el log de accesos


def iniciar_servidor():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🌐 Server HTTP escuchando en :{PORT}")
    srv.serve_forever()


def watchdog():
    """Avisa por Telegram si el monitor lleva >30 min sin correr."""
    try:
        with open(os.path.join(DATA_DIR, "heartbeat.json")) as f:
            hb = json.load(f)
        ultima = datetime.fromisoformat(hb.get("ultima_ejecucion", ""))
        if ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        mins = (datetime.now(timezone.utc) - ultima).total_seconds() / 60
        if mins > 30:
            bot = os.getenv("BOT_TOKEN", ""); chat = os.getenv("CHAT_ID", "")
            if bot and chat:
                import urllib.request
                msg = ("⚠️ ALERTA\n🚫 Monitor sin ejecutar\n\n"
                       f"🕒 La última ejecución exitosa fue hace {int(mins)} min.\n"
                       "📲 Revisá Railway → Deployments para verificar el estado del servicio")
                data = json.dumps({"chat_id": chat, "text": msg}).encode("utf-8")
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{bot}/sendMessage",
                    data=data, headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10)
                print(f"⚠️ Watchdog: alerta enviada ({int(mins)} min)")
    except Exception as e:
        print(f"ℹ️ Watchdog: {e}")


def main():
    pull_codigo()
    sembrar_data()
    threading.Thread(target=iniciar_servidor, daemon=True).start()

    while True:
        inicio = time.time()
        print(f"🏥 Ciclo {datetime.now().isoformat()}")
        r = subprocess.run([sys.executable, "monitor.py"])

        if r.returncode == 0:
            hc = os.getenv("HEALTHCHECK_URL", "")
            if hc:
                try:
                    import urllib.request
                    urllib.request.urlopen(hc, timeout=10)
                    # Ping OK: no se loguea (evita ruido). Solo se avisa si falla.
                except Exception as e:
                    print(f"⚠️ Healthchecks: falló el ping ({e})")

        watchdog()
        dormir = max(5, CICLO_SEG - int(time.time() - inicio))
        print(f"😴 Próximo ciclo en {dormir}s")
        time.sleep(dormir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrumpido")
