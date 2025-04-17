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

GITHUB_SECRET = os.environ.get("GITHUB_SECRET").encode()
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")
GITHUB_PAT = os.environ.get("GITHUB_PAT")
COMPOSE_REPO = os.environ.get("COMPOSE_REPO")
SECRETS_REPO = os.environ.get("SECRETS_REPO")

DEPLOY_BASE = os.environ.get("DEPLOY_BASE")

TMP_PATH = "/tmp"

SSH_USER = os.environ.get("SSH_USER")
SSH_TARGET = os.environ.get("SSH_TARGET")
SSH_COMPOSE_ROOT = os.environ.get("SSH_COMPOSE_ROOT")

HOST_DOCKER_PATH = os.environ.get("HOST_DOCKER_PATH", "docker")

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

def try_pull(command):
    try:
        subprocess.run(command, shell=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False
    
def copy_env_file_if_needed(service_name):
    compose_path = Path(DEPLOY_BASE) / "compose" / service_name / ".env"
    secrets_path = Path(DEPLOY_BASE) / "secrets" / service_name / ".env"

    if compose_path.exists():
        print(f"✅ .env for {service_name} already exists.")
        return

    if secrets_path.exists():
        shutil.copy2(secrets_path, compose_path)
        print(f"🔐 Copied .env for {service_name} from secrets.")
    else:
        print(f"⚠️ No .env found for {service_name} in compose or secrets.")


def deploy_all_services(compose_dir_names):
    print("Deploying services...")

    ssh_command = ["ssh", "-i", "/root/.ssh/id_ed25519", f"{SSH_USER}@{SSH_TARGET}"]
    ssh_command = " ".join(ssh_command)
    print(f"SSH command: {ssh_command}")

    for name in compose_dir_names:
        print(f"🔍 Preparing {name}...")

        copy_env_file_if_needed(name)

        path = f"{SSH_COMPOSE_ROOT}/{name}/docker-compose.yml"

        print(f"Deploying {name}...")

        try_pull_command = f'{ssh_command} {HOST_DOCKER_PATH} compose -f "{path}" pull'

        print(try_pull_command)

        pull_success = try_pull(try_pull_command)

        if not pull_success:
            print(f"⚠️ Failed to pull image for {name}, it was inaccessible or private, so you may need to log in. Skipping...")
            continue

        stop_command = f'{ssh_command} {HOST_DOCKER_PATH} compose -f "{path}" down'

        start_command = f'{ssh_command} {HOST_DOCKER_PATH} compose -f "{path}" up -d'

        subprocess.run(stop_command, shell=True, check=True)
        print(f"✅ Stopped {name}")

        subprocess.run(start_command, shell=True, check=True)
        print(f"✅ Started {name}")

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
