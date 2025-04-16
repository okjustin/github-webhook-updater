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

TMP_PATH = "/tmp/webhook-tmp"

SSH_USER = os.environ.get("SSH_USER", "justin")
SSH_TARGET = os.environ.get("SSH_TARGET", "localhost")
SSH_COMPOSE_ROOT = os.environ.get("SSH_COMPOSE_ROOT", "/opt/docker/homelab-config/compose")

ENV = os.environ.get("ENV", "production")

DOCKER_PATH = "/usr/local/bin/docker"
LOCAL_DOCKER_CONFIG = "/app/docker-config"

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

def ssh_run(ssh_base, cmd_string):
    """Run a full shell command on the remote via SSH, with proper env + quoting"""
    full_cmd = ssh_base + ["sh", "-c", cmd_string]
    print(f"Running SSH command: {' '.join(full_cmd)}")
    subprocess.run(full_cmd, check=True)

def deploy_all_services(compose_dir_names):
    print("Deploying services...")

    ssh_base = ["ssh", "-i", "/root/.ssh/id_ed25519", f"{SSH_USER}@{SSH_TARGET}"]
    docker_path = DOCKER_PATH
    docker_config = LOCAL_DOCKER_CONFIG

    if os.path.exists(docker_config):
        print(f"Using isolated Docker config at: {docker_config}")
    else:
        print("⚠️ Local Docker config not found, using default Docker settings")

    for name in compose_dir_names:
        path = f"{SSH_COMPOSE_ROOT}/{name}/docker-compose.yml"
        print(f"Deploying {name}...")

        pull_cmd = f'DOCKER_CONFIG="{docker_config}" {docker_path} compose -f "{path}" pull'
        up_cmd   = f'DOCKER_CONFIG="{docker_config}" {docker_path} compose -f "{path}" up -d'

        ssh_run(ssh_base, pull_cmd)
        ssh_run(ssh_base, up_cmd)

        print(f"✅ Deployed {name}")

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

        service_names = [f.name for f in Path(f"{DEPLOY_BASE}/compose").iterdir() if (f / "docker-compose.yml").exists()]

        print(f"Found services: {service_names}")

        # Deploy services
        deploy_all_services(service_names)

        print("✅ Deployment complete.")
        return "Deployed!", 200

    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        return f"Deploy failed: {e}", 500

# --- Entry Point ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
