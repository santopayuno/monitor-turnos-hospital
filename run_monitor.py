#!/usr/bin/env python3
"""
Script para ejecutar monitor.py en Railway + git push
"""
import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

try:
    # 0. Inicializar git si no existe
    if not os.path.exists('.git'):
        print("Inicializando repositorio git...")
        subprocess.run(['git', 'init'], check=False)
        subprocess.run(['git', 'remote', 'add', 'origin', f'https://{os.getenv("GITHUB_TOKEN")}@github.com/santopayuno/monitor-turnos-hospital.git'], check=False)
        subprocess.run(['git', 'fetch', 'origin', 'main'], check=False)
        subprocess.run(['git', 'checkout', '-b', 'main', 'origin/main'], check=False)
    
    # 1. Ejecutar monitor
    print("Ejecutando monitor.py...")
    result = subprocess.run([sys.executable, 'monitor.py'], check=False)
    
    # 2. Git config
    subprocess.run(['git', 'config', 'user.email', 'railway@monitor.local'], check=False)
    subprocess.run(['git', 'config', 'user.name', 'Railway Monitor'], check=False)
    
    # 3. Git add
    subprocess.run(['git', 'add', 'estado_turnos.json', 'estadisticas_db.json', 'logs/'], check=False)
    
    # 4. Git commit (sin fallar si no hay cambios)
    subprocess.run(['git', 'commit', '-m', 'Monitor: Railway cron job'], check=False)
    
    # 5. Git push
    print("Haciendo push a GitHub...")
    subprocess.run(['git', 'push', 'origin', 'main'], check=False)
    
    sys.exit(result.returncode)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
