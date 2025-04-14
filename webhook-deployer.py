from flask import Flask, request, abort
import hmac
import hashlib
import os
import subprocess
import shutil
from pathlib import Path

app = Flask(__name__)

# Configuration
GITHUB_SECRET = os.environ.get('GITHUB_SECRET', '').encode()
COMPOSE_REPO = os.environ.get('COMPOSE_REPO')
SECRETS_REPO = os.environ.get('SECRETS_REPO')
DEPLOY_BASE = os.environ.get('DEPLOY_BASE', '/opt/docker/homelab-config')
TMP_PATH = 'tmp/homelab-tmp'

@app.route('/payload', methods=['POST'])
def webhook():
  # Verify the request signature
  signature = request.headers.get('X-Hub-Signature-256')
  if GITHUB_SECRET and signature:
    sha_name, signature = signature.split('=')
    mac = hmac.new(GITHUB_SECRET, msg=request.data, digestmod=hashlib.sha256)
    if not hmac.compare_digest(mac.hexdigest(), signature):
      abort(403)

  payload = request.json
  if payload.get('ref') != 'refs/heads/main':
    return 'Not a main branch push', 200
  
  try:
    print('Pulling latest changes...')
    shutil.rmtree(TMP_PATH, ignore_errors=True)
    os.makedirs(TMP_PATH, exist_ok=True)

    subprocess.run(['git', 'clone', '--depth', '1', COMPOSE_REPO, f"{TMP_PATH}/homelab-config"], check=True)
    subprocess.run(['git', 'clone', '--depth', '1', SECRETS_REPO, f"{TMP_PATH}/secrets"], check=True)

    print('Replacing config folders...')
    shutil.rmtree(DEPLOY_BASE, ignore_errors=True)
    shutil.copytree(f"{TMP_PATH}/homelab-config", DEPLOY_BASE)

    print('Replacing secrets folders...')
    shutil.rmtree(f"{DEPLOY_BASE}/secrets", ignore_errors=True)
    shutil.copytree(f"{TMP_PATH}/secrets", f"{DEPLOY_BASE}/secrets")

    print('Running docker compose up -d in each folder...')
    for service_dir in Path(DEPLOY_BASE).iterdir():
      if (service_dir / 'docker-compose.yml').exists():
        print(f"Deploying {service_dir.name}...")
        subprocess.run(['docker', 'compose', '-f', f"{service_dir}/docker-compose.yml", 'pull'], check=True)
        subprocess.run(['docker', 'compose', '-f', f"{service_dir}/docker-compose.yml", 'up', '-d'], check=True)

    return 'Deployed!', 200
  
  except Exception as e:
    print(f"Error: {e}")
    return f"Deploy failed: {e}", 500
  
if __name__ == '__main__':
  port = int(os.environ.get('PORT', 5005))
  app.run(host="0.0.0.0", port=port)
