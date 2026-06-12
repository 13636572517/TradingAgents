#!/usr/bin/env python3
"""Remote deploy via paramiko SSH.
Usage: python scripts/remote_deploy.py
"""
import os
import sys
import time
import paramiko
from pathlib import Path

HOST = "47.103.133.232"
USER = "admin"
# Never hardcode credentials. Export DEPLOY_SSH_PASSWORD before running, or
# rely on key-based auth via KEY_PATH.
SSH_PASSWORD = os.getenv("DEPLOY_SSH_PASSWORD")
KEY_PATH = str(Path.home() / ".ssh" / "id_ed25519")
REMOTE_APP_DIR = "/root/TradingAgents"   # adjust if different on server


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 300) -> int:
    print(f"\n$ {cmd}")
    transport = client.get_transport()
    channel = transport.open_session()
    channel.set_combine_stderr(True)
    channel.exec_command(cmd)

    while True:
        if channel.recv_ready():
            data = channel.recv(4096).decode("utf-8", errors="replace")
            print(data, end="", flush=True)
        if channel.exit_status_ready():
            # Drain remaining output
            while channel.recv_ready():
                data = channel.recv(4096).decode("utf-8", errors="replace")
                print(data, end="", flush=True)
            break
        time.sleep(0.2)

    rc = channel.recv_exit_status()
    print(f"[exit {rc}]")
    return rc


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"Connecting to {USER}@{HOST} ...")
    client.connect(HOST, username=USER, password=SSH_PASSWORD, timeout=15)

    print("Connected.")

    # Ensure git remote uses SSH (not HTTPS)
    _ensure_ssh_remote(client)

    # Reset server repo — sudo needed for root-owned icon files
    run(client, "cd /opt/tradingagents && git stash 2>/dev/null; "
                "sudo rm -f web/public/icons/apple-touch-icon.png "
                "web/public/icons/icon-192.png web/public/icons/icon-512.png "
                "web/public/icons/icon-180.png; git clean -fd; "
                "git restore .", timeout=60)

    # Test GitHub SSH connectivity
    print("\n[*] Testing GitHub SSH connectivity...")
    rc_net = run(client, "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -T git@github.com 2>&1 | grep -q 'successfully authenticated'; echo $?", timeout=20)

    if rc_net == 0:
        # Normal deploy via git pull
        rc = run(client, "cd /opt/tradingagents && bash deploy.sh", timeout=600)
    else:
        print("[!] GitHub unreachable — switching to rsync push")
        rc = _rsync_and_build(client)

    if rc != 0:
        print(f"\n❌ deploy failed with code {rc}")
        sys.exit(rc)

    print("\n✅ Deploy complete.")
    client.close()


def _ensure_ssh_remote(client: paramiko.SSHClient):
    """Make sure /opt/tradingagents uses SSH remote and server has a deploy key."""
    # 1. Switch remote URL from HTTPS to SSH if needed
    run(client,
        "cd /opt/tradingagents && "
        "git remote get-url origin | grep -q 'git@github.com' || "
        "git remote set-url origin git@github.com:13636572517/TradingAgents.git",
        timeout=15)

    # 2. Generate an SSH key for the deploy user if one doesn't exist
    run(client,
        "[ -f ~/.ssh/id_ed25519 ] || "
        "ssh-keygen -t ed25519 -C 'deploy@tradingagents' -N '' -f ~/.ssh/id_ed25519",
        timeout=15)

    # 3. Add github.com to known_hosts to avoid interactive prompt
    run(client,
        "ssh-keygen -F github.com > /dev/null 2>&1 || "
        "ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null",
        timeout=15)

    # 4. Test auth — if it fails, show the public key for the user to add
    transport = client.get_transport()
    chan = transport.open_session()
    chan.set_combine_stderr(True)
    chan.exec_command("ssh -o BatchMode=yes -T git@github.com 2>&1 || true")
    output = chan.recv(4096).decode("utf-8", errors="replace")
    chan.recv_exit_status()

    if "successfully authenticated" not in output:
        # Fetch and display the public key
        transport2 = client.get_transport()
        chan2 = transport2.open_session()
        chan2.set_combine_stderr(True)
        chan2.exec_command("cat ~/.ssh/id_ed25519.pub")
        pubkey = chan2.recv(4096).decode("utf-8", errors="replace").strip()
        chan2.recv_exit_status()
        print("\n" + "="*60)
        print("⚠️  GitHub SSH auth not yet set up on the server.")
        print("请将以下公钥添加到 GitHub → Settings → Deploy keys:")
        print(f"\n{pubkey}\n")
        print("添加后重新运行部署脚本。")
        print("="*60)
        import sys; sys.exit(1)

    print("[✓] GitHub SSH auth OK")


def _rsync_and_build(client: paramiko.SSHClient) -> int:
    import subprocess, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Use paramiko SFTP to upload changed files
    sftp = client.open_sftp()
    upload_dirs = ["tradingagents", "server", "cli", "web", "scripts"]
    upload_files = ["pyproject.toml", "Dockerfile.prod", "docker-compose.prod.yml",
                    "manage_users.py", "deploy.sh"]

    def _upload_tree(local_dir: str, remote_base: str):
        import os
        for dirpath, dirnames, filenames in os.walk(local_dir):
            # Skip node_modules / __pycache__ / .git
            dirnames[:] = [d for d in dirnames if d not in
                           ("node_modules", "__pycache__", ".git", "dist", ".venv")]
            rel = os.path.relpath(dirpath, root)
            remote_dir = remote_base + "/" + rel.replace(os.sep, "/")
            try:
                sftp.mkdir(remote_dir)
            except Exception:
                pass
            for fn in filenames:
                local_path = os.path.join(dirpath, fn)
                remote_path = remote_dir + "/" + fn
                sftp.put(local_path, remote_path)
        print(f"  uploaded {local_dir}/")

    REMOTE = "/opt/tradingagents"
    for d in upload_dirs:
        local = os.path.join(root, d)
        if os.path.isdir(local):
            _upload_tree(local, REMOTE)
    for f in upload_files:
        local = os.path.join(root, f)
        if os.path.isfile(local):
            sftp.put(local, f"{REMOTE}/{f}")
            print(f"  uploaded {f}")
    sftp.close()
    print("[*] Upload done. Running docker compose build + up...")

    rc = run(client,
             "cd /opt/tradingagents && "
             "docker compose -f docker-compose.prod.yml build && "
             "docker compose -f docker-compose.prod.yml up -d && "
             "sleep 5 && docker compose -f docker-compose.prod.yml ps",
             timeout=600)
    return rc


def check_logs(lines: int = 80):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=SSH_PASSWORD, timeout=15)
    run(client, f"docker compose -f /opt/tradingagents/docker-compose.prod.yml "
                f"logs --no-color --tail={lines} server", timeout=30)
    client.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "logs":
        check_logs(int(sys.argv[2]) if len(sys.argv) > 2 else 80)
    else:
        main()
