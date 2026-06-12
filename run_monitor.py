#!/usr/bin/env python3
"""
Script para ejecutar monitor.py en Railway + git push CORRECTO
Resuelve conflictos de archivos y rama main vs master
"""
import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def run_cmd(cmd, ignore_error=False):
    """Ejecutar comando de shell"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=not ignore_error)
        if result.stdout:
            print(result.stdout)
        if result.stderr and not ignore_error:
            print(f"ERROR: {result.stderr}")
        return result.returncode == 0
    except Exception as e:
        print(f"Exception: {e}")
        return False

try:
    # ============================================================
    # PASO 1: Inicializar Git si no existe
    # ============================================================
    if not os.path.exists('.git'):
        print("🔧 Inicializando repositorio git...")

        run_cmd(['git', 'init'])
        run_cmd(['git', 'config', 'user.email', 'railway@monitor.local'])
        run_cmd(['git', 'config', 'user.name', 'Railway Monitor'])

        # Agregar remote
        token = os.getenv('GITHUB_TOKEN', '')
        repo_url = f'https://{token}@github.com/santopayuno/monitor-turnos-hospital.git'
        run_cmd(['git', 'remote', 'add', 'origin', repo_url])

        # Fetch limpio
        print("📥 Descargando repositorio...")
        run_cmd(['git', 'fetch', 'origin', 'main'])

        # Reset --hard: resuelve conflictos de archivos locales
        print("🔄 Sincronizando archivos locales...")
        run_cmd(['git', 'reset', '--hard', 'origin/main'], ignore_error=True)

        # Crear rama main si no existe (y trackear origin/main)
        run_cmd(['git', 'checkout', '--track', 'origin/main'], ignore_error=True)

        print("✅ Git inicializado correctamente\n")

    # ============================================================
    # PASO 2: Watchdog — detectar si el monitor anterior falló
    # ============================================================
    import json
    from datetime import datetime, timezone

    try:
        with open('heartbeat.json', 'r') as f:
            hb = json.load(f)
        ultima = datetime.fromisoformat(hb.get('ultima_ejecucion', ''))
        ahora_utc = datetime.now(timezone.utc)
        if ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        minutos_desde_ultima = (ahora_utc - ultima).total_seconds() / 60

        if minutos_desde_ultima > 30:
            horas = int(minutos_desde_ultima // 60)
            mins = int(minutos_desde_ultima % 60)
            tiempo_str = f"{horas} h {mins} min" if horas > 0 else f"{int(minutos_desde_ultima)} min"
            bot_token = os.getenv('BOT_TOKEN', '')
            chat_id = os.getenv('CHAT_ID', '')
            if bot_token and chat_id:
                import urllib.request
                msg = (
                    f"⚠️ ALERTA: Monitor sin ejecutar\n\n"
                    f"La última ejecución exitosa fue hace {tiempo_str}.\n"
                    f"Revisá Railway → Cron Runs para verificar el estado del servicio."
                )
                data = json.dumps({"chat_id": chat_id, "text": msg}).encode('utf-8')
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                urllib.request.urlopen(req, timeout=10)
                print(f"⚠️ Watchdog: alerta enviada por Telegram ({tiempo_str} sin ejecución)")
    except Exception as e:
        print(f"ℹ️ Watchdog: no pudo verificar heartbeat ({e})")

    # ============================================================
    # PASO 3: Ejecutar monitor
    # ============================================================
    print("🏥 Ejecutando monitor.py...")
    result = subprocess.run([sys.executable, 'monitor.py'], check=False)
    print()

    # ============================================================
    # PASO 3: Git config (por si acaso)
    # ============================================================
    run_cmd(['git', 'config', 'user.email', 'railway@monitor.local'], ignore_error=True)
    run_cmd(['git', 'config', 'user.name', 'Railway Monitor'], ignore_error=True)

    # ============================================================
    # PASO 4: Verificar estado del repo
    # ============================================================
    print("📊 Estado del repositorio:")
    run_cmd(['git', 'status'])
    print()

    # ============================================================
    # PASO 5: Git add - Solo archivos específicos
    # ============================================================
    print("📝 Agregando archivos cambios...")
    run_cmd(['git', 'add', 'estado_turnos.json', 'estado_anterior.json', 'estadisticas_db.json', 'heartbeat.json', 'historial_cupos.json'], ignore_error=True)
    run_cmd(['git', 'add', 'logs/'], ignore_error=True)

    # ============================================================
    # PASO 6: Git commit
    # ============================================================
    print("💾 Creando commit...")
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_cmd(['git', 'commit', '-m', f'Monitor: Railway cron job - {timestamp}'], ignore_error=True)

    # ============================================================
    # PASO 7: Pull antes de push (resolver conflictos)
    # ============================================================
    print("🔀 Sincronizando cambios remotos...")
    run_cmd(['git', 'pull', 'origin', 'main', '--rebase'], ignore_error=True)

    # ============================================================
    # PASO 8: Git push
    # ============================================================
    print("📤 Haciendo push a GitHub...")
    success = run_cmd(['git', 'push', 'origin', 'main'], ignore_error=True)

    if success:
        print("✅ Push exitoso a GitHub\n")
    else:
        print("⚠️  Push falló, pero monitor ejecutó correctamente\n")

    # ============================================================
    # PASO 9: Log final
    # ============================================================
    print("=" * 60)
    print("🎉 EJECUCIÓN COMPLETADA")
    print("=" * 60)
    print(f"Timestamp: {datetime.datetime.now()}")
    print("Próxima ejecución: en 15 minutos")

    sys.exit(result.returncode)

except Exception as e:
    print(f"❌ Error fatal: {e}")
    sys.exit(1)