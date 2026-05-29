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
    # PASO 2: Ejecutar monitor
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
    run_cmd(['git', 'add', 'estado_turnos.json', 'estadisticas_db.json'], ignore_error=True)
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
    # NUEVO PASO: Forzar la ejecución manual en GitHub Actions (Telegram)
    # ============================================================
    import urllib.request
    import json

    token = os.getenv('GITHUB_TOKEN')
    if token:
        print("🚀 Despertando a GitHub Actions para enviar la notificación de Telegram...")

        # Como tu archivo se llama exactamente monitor.yml, esta URL ya está perfecta:
        url = "https://api.github.com/repos/santopayuno/monitor-turnos-hospital/actions/workflows/monitor.yml/dispatches"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Railway-Trigger-Script"
        }

        # Le indicamos a GitHub que ejecute el flujo usando la rama principal (main)
        data = json.dumps({"ref": "main"}).encode('utf-8')

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req) as response:
                if response.status == 204:
                    print("✅ ¡GitHub Actions despertado con éxito! Se ejecutará el monitor manual en breve.")
                else:
                    print(f"⚠️ GitHub respondió con código de estado: {response.status}")
        except Exception as api_err:
            print(f"❌ Error al conectar con la API de GitHub: {api_err}")
    else:
        print("⚠️ No se encontró la variable GITHUB_TOKEN en Railway. Asegúrate de añadirla en las Variables de Entorno del servicio.")

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