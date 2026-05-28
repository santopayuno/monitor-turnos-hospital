#!/usr/bin/env python3
"""
🏥 ORQUESTADOR DE ENTORNO - HOSPITAL PERRUPATO
Script optimizado para ejecuciones cíclicas en Railway con persistencia en GitHub.
Resuelve conflictos de archivos y sincroniza el árbol de datos.
"""
import subprocess
import sys
import os
import datetime
import urllib.request
import json

# Asegurar que trabajamos en el directorio del script
os.chdir(os.path.dirname(os.path.abspath(__file__)))

def run_cmd(cmd, ignore_error=False):
    """Ejecuta comandos de terminal de forma controlada"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=not ignore_error)
        if result.stdout and not ignore_error:
            print(result.stdout.strip())
        if result.stderr and not ignore_error:
            print(f"⚠️ GIT LOG: {result.stderr.strip()}")
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Error ejecutando comando {cmd}: {e}")
        return False

try:
    # ============================================================
    # PASO 1: Inicializar Git y asegurar Tracking Limpio
    # ============================================================
    if not os.path.exists('.git'):
        print("🔧 Configurando repositorio Git por primera vez en el nodo...")
        run_cmd(['git', 'init'])
        run_cmd(['git', 'config', 'user.email', 'railway@monitor.local'])
        run_cmd(['git', 'config', 'user.name', 'Railway Monitor'])

        token = os.getenv('GITHUB_TOKEN', '')
        if not token:
            print("❌ ERROR CRÍTICO: GITHUB_TOKEN no configurado en las variables de Railway.")
            sys.exit(1)

        repo_url = f'https://{token}@github.com/santopayuno/monitor-turnos-hospital.git'
        run_cmd(['git', 'remote', 'add', 'origin', repo_url])
        
        print("📥 Sincronizando estado inicial con GitHub (main)...")
        run_cmd(['git', 'fetch', 'origin', 'main'])
        run_cmd(['git', 'reset', '--hard', 'origin/main'], ignore_error=True)
        run_cmd(['git', 'checkout', '-B', 'main', 'origin/main'], ignore_error=True)
        print("✅ Inicialización completada con éxito.\n")

    # ============================================================
    # PASO 2: Ejecutar el Monitor Clínico
    # ============================================================
    print("🏥 Iniciando monitor.py (Consulta de API y Alertas Telegram)...")
    result_monitor = subprocess.run([sys.executable, 'monitor.py'], check=False)
    print(f"ℹ️ Proceso del monitor finalizado con código: {result_monitor.returncode}\n")

    # Re-verificar credenciales locales por seguridad de entorno continuo
    run_cmd(['git', 'config', 'user.email', 'railway@monitor.local'], ignore_error=True)
    run_cmd(['git', 'config', 'user.name', 'Railway Monitor'], ignore_error=True)

    # ============================================================
    # PASO 3: Indexación de Cambios Estructurales
    # ============================================================
    print("📝 Indexando archivos modificados...")
    run_cmd(['git', 'add', 'estado_turnos.json', 'estadisticas_db.json'], ignore_error=True)
    
    # PROGRAMACIÓN CORREGIDA: Apuntar al archivo real de logs generado en la raíz
    if os.path.exists('monitor.log'):
        run_cmd(['git', 'add', 'monitor.log'], ignore_error=True)

    # Verificación de diferencias reales antes de comprometer el árbol
    status_proc = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True)
    
    if status_proc.stdout.strip():
        print("💾 Cambios detectados. Generando commit histórico...")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        run_cmd(['git', 'commit', '-m', f'Data Update: {timestamp} [Railway Cron]'], ignore_error=True)
        
        print("🔀 Ejecutando pull preventivo con rebase...")
        run_cmd(['git', 'pull', 'origin', 'main', '--rebase'], ignore_error=True)
        
        print("📤 Enviando base de datos actualizada a GitHub...")
        push_success = run_cmd(['git', 'push', 'origin', 'main'])
    else:
        print("🕊️ El estado de los cupos no cambió en este ciclo. No se requiere Push.")
        push_success = True

    # ============================================================
    # PASO 4: Despertar GitHub Actions para Actualización Web
    # ============================================================
    token = os.getenv('GITHUB_TOKEN')
    if token and push_success:
        print("🚀 Notificando a GitHub Actions para reconstruir el Dashboard estático...")
        url = "https://api.github.com/repos/santopayuno/monitor-turnos-hospital/actions/workflows/monitor.yml/dispatches"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Railway-Pipeline-Orchestrator"
        }
        
        data = json.dumps({"ref": "main"}).encode('utf-8')
        
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req) as response:
                if response.status == 204:
                    print("✅ Despliegue solicitado. La web se actualizará con los nuevos gráficos en breve.")
                else:
                    print(f"⚠️ Respuesta inesperada de la API de GitHub: {response.status}")
        except Exception as api_err:
            print(f"❌ No se pudo despachar el disparador en GitHub Actions: {api_err}")

    print("\n" + "=" * 60)
    print(f"🎉 CICLO COMPLETADO EXITOSAMENTE - {datetime.datetime.now()}")
    print("=" * 60)
    
    sys.exit(result_monitor.returncode)

except Exception as e:
    print(f"❌ Error crítico en el orquestador: {e}")
    sys.exit(1)
