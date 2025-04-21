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


def try_pull(command):
    try:
        subprocess.run(command, shell=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def sync_service_to_host(service_name):
    local_compose_dir = Path(TMP_PATH) / "compose" / service_name
    local_secrets_env = Path(TMP_PATH) / "secrets" / service_name / ".env"
    remote_dir = f"{SSH_COMPOSE_ROOT}/{service_name}"

    print(f"📦 Syncing '{service_name}' to host...")

    subprocess.run([
        "ssh", "-i", "/root/.ssh/id_ed25519", f"{SSH_USER}@{SSH_TARGET}",
        f"mkdir -p '{remote_dir}'"
    ], check=True)

    subprocess.run([
        "scp", "-i", "/root/.ssh/id_ed25519", "-r", str(local_compose_dir) + "/", f"{SSH_USER}@{SSH_TARGET}:{remote_dir}"
    ], check=True)

    if local_secrets_env.exists():
        subprocess.run([
            "scp", "-i", "/root/.ssh/id_ed25519", str(local_secrets_env), f"{SSH_USER}@{SSH_TARGET}:{remote_dir}/.env"
        ], check=True)
        print(f"🔐 Copied .env for {service_name}")
    else:
        print(f"⚠️ No secrets .env for {service_name}")


def deploy_all_services(service_names):
    print("🚀 Deploying services...")

    ssh_base = f"ssh -i /root/.ssh/id_ed25519 {SSH_USER}@{SSH_TARGET}"

    for name in service_names:
        path = f"{SSH_COMPOSE_ROOT}/{name}/docker-compose.yml"
        print(f"▶️ Deploying {name}...")

        pull = f'{ssh_base} {HOST_DOCKER_PATH} compose -f "{path}" pull'
        down = f'{ssh_base} {HOST_DOCKER_PATH} compose -f "{path}" down'
        up = f'{ssh_base} {HOST_DOCKER_PATH} compose -f "{path}" up -d'

        if not try_pull(pull):
            print(f"⚠️ Failed to pull image for {name}. Might be private or missing. Skipping...")
            continue

        subprocess.run(down, shell=True, check=True)
        print(f"✅ Stopped {name}")

        subprocess.run(up, shell=True, check=True)
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
        print("🧹 Cleaning tmp...")
        shutil.rmtree(TMP_PATH, ignore_errors=True)
        os.makedirs(TMP_PATH, exist_ok=True)

        print("📥 Cloning config and secrets...")
        clone_repo(f"https://github.com/{GITHUB_USERNAME}/{COMPOSE_REPO}.git", f"{TMP_PATH}/compose")
        clone_repo(f"https://{GITHUB_USERNAME}:{GITHUB_PAT}@github.com/{GITHUB_USERNAME}/{SECRETS_REPO}.git", f"{TMP_PATH}/secrets")

        service_names = [f.name for f in Path(f"{TMP_PATH}/compose").iterdir() if (f / "docker-compose.yml").exists()]
        print(f"📦 Found services: {', '.join(service_names)}")

        for service in service_names:
            sync_service_to_host(service)

        deploy_all_services(service_names)

        print("✅ Deployment complete.")
        return "Deployed!", 200

    except Exception as e:
        print(f"❌ Deployment failed: {e}")
        return f"Deploy failed: {e}", 500


# --- Entry Point ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
