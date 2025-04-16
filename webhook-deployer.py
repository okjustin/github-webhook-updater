from flask import Flask, request, abort
import hmac
import hashlib
import os
import subprocess
import shutil
from pathlib import Path

# --- Config ---
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 5005))

GITHUB_SECRET = os.environ.get("GITHUB_SECRET", "").encode()
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")
GITHUB_PAT = os.environ.get("GITHUB_PAT")
COMPOSE_REPO = os.environ.get("COMPOSE_REPO")
SECRETS_REPO = os.environ.get("SECRETS_REPO")
DEPLOY_BASE = os.environ.get("DEPLOY_BASE", "/opt/docker/homelab-config")
HOST_DEPLOY_BASE = os.environ.get("HOST_DEPLOY_BASE", DEPLOY_BASE)
TMP_PATH = "/tmp/webhook-tmp"
ENV = os.environ.get("ENV", "production")

# --- Utils ---
def verify_signature(request):
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        return False

    sha_name, signature = signature.split("=")
    mac = hmac.new(GITHUB_SECRET, msg=request.data, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)

def clone_repo(url, destination):
    subprocess.run(["git", "clone", "--depth", "1", url, destination], check=True)

def replace_folder(target, source):
    if os.path.exists(target):
        print(f"Removing existing folder: {target}")
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    shutil.copytree(source, target)
    print(f"Replaced {target} with new contents.")

def deploy_all_services(container_path, host_path):
    print("Deploying services...")

    container_compose_root = Path(container_path) / "compose"
    host_compose_root = Path(host_path) / "compose"

    for service_dir in container_compose_root.iterdir():
        compose_file = service_dir / "docker-compose.yml"
        if compose_file.exists():
            print(f"Deploying: {service_dir.name}")

            host_compose_file = host_compose_root / service_dir.name / "docker-compose.yml"

            subprocess.run(["docker-compose", "-f", str(host_compose_file), "pull"], check=True)
            subprocess.run(["docker-compose", "-f", str(host_compose_file), "up", "-d"], check=True)
            print(f"✅ Deployed {service_dir.name}")
        else:
            print(f"Skipping {service_dir.name}: No docker-compose.yml found.")

# --- Flask Route ---
@app.route("/payload", methods=["POST"])
def webhook():
    if ENV == "production" and GITHUB_SECRET and not verify_signature(request):
        abort(403)

    payload = request.json
    if payload.get("ref") != "refs/heads/main":
        return "Not a main branch push", 200

    try:
        print("Starting deployment process...")
        shutil.rmtree(TMP_PATH, ignore_errors=True)
        os.makedirs(TMP_PATH, exist_ok=True)

        # Clone compose repo
        config_repo_url = f"https://github.com/{GITHUB_USERNAME}/{COMPOSE_REPO}.git"
        clone_repo(config_repo_url, f"{TMP_PATH}/compose")

        # Clone secrets repo (using PAT)
        secrets_repo_url = f"https://{GITHUB_USERNAME}:{GITHUB_PAT}@github.com/{GITHUB_USERNAME}/{SECRETS_REPO}.git"
        clone_repo(secrets_repo_url, f"{TMP_PATH}/secrets")

        # Replace configs and secrets
        replace_folder(os.path.join(DEPLOY_BASE, "compose"), f"{TMP_PATH}/compose")
        replace_folder(os.path.join(DEPLOY_BASE, "secrets"), f"{TMP_PATH}/secrets")

        # Deploy services
        deploy_all_services(
            container_path=DEPLOY_BASE,
            host_path=HOST_DEPLOY_BASE,
          )

        print("✅ Deployment complete.")
        return "Deployed!", 200

    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        return f"Deploy failed: {e}", 500

# --- Entry Point ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
