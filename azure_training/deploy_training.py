"""
deploy_training.py — Push training data + scripts to the 4 Azure T4 VMs
                     and launch training jobs over SSH.

Usage:
    python deploy_training.py --ips 1.2.3.4 5.6.7.8 9.10.11.12 13.14.15.16 \
                              --key ~/.ssh/azure_t4.pem \
                              [--user azureuser] \
                              [--dry-run]

VM assignment (fixed):
    VM 1 → PERSONA=cortana  (primary Cortana fine-tune)
    VM 2 → PERSONA=jarvis   (primary JARVIS fine-tune)
    VM 3 → PERSONA=cortana  (second run — higher rank / longer epochs)
    VM 4 → PERSONA=jarvis   (second run — higher rank / longer epochs)

Prerequisites:
    pip install paramiko  (only needed on the machine running this script)
    All 4 VMs must have setup_vm.sh already run.

If paramiko is not available, use --dry-run to print the raw SSH commands
instead of executing them.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

# Files to upload to each VM (relative to repo root)
UPLOAD_FILES = [
    "azure_training/train_azure_t4.py",
    "azure_training/setup_vm.sh",
    "training_data/albedo_dataset_v3.jsonl",
    "training_data/jarvis_dataset_v2.jsonl",
]

# Per-VM job config
VM_JOBS = [
    {
        "label":   "VM1 — Cortana primary",
        "persona": "cortana",
        "epochs":  "10",
        "rank":    "32",
        "batch":   "4",
    },
    {
        "label":   "VM2 — JARVIS primary",
        "persona": "jarvis",
        "epochs":  "10",
        "rank":    "32",
        "batch":   "4",
    },
    {
        "label":   "VM3 — Cortana extended (rank 64)",
        "persona": "cortana",
        "epochs":  "15",
        "rank":    "64",
        "batch":   "2",   # rank-64 uses more VRAM; smaller batch
    },
    {
        "label":   "VM4 — JARVIS extended (rank 64)",
        "persona": "jarvis",
        "epochs":  "15",
        "rank":    "64",
        "batch":   "2",
    },
]

REMOTE_DIR = "/home/{user}/albedo_training"


def _make_train_cmd(job: dict, user: str) -> str:
    rdir = REMOTE_DIR.format(user=user)
    env = (
        f"PERSONA={job['persona']} "
        f"EPOCHS={job['epochs']} "
        f"LORA_RANK={job['rank']} "
        f"BATCH_SIZE={job['batch']} "
        f"OUTPUT_DIR={rdir}/outputs "
        f"DATA_FILE={rdir}/training_data/{job['persona']}_dataset_{'v3' if job['persona'] == 'cortana' else 'v2'}.jsonl"
    )
    script = f"{rdir}/azure_training/train_azure_t4.py"
    log    = f"{rdir}/train_{job['persona']}.log"
    return f"nohup {env} python3.11 {script} > {log} 2>&1 &"


def print_ssh_commands(ips: list[str], key: str, user: str) -> None:
    """Print raw SSH/SCP commands the user can run manually."""
    repo_root = Path(__file__).resolve().parent.parent

    print("\n" + "=" * 68)
    print("  MANUAL SSH COMMANDS — run these in order")
    print("=" * 68)

    for i, (ip, job) in enumerate(zip(ips, VM_JOBS)):
        rdir = REMOTE_DIR.format(user=user)
        print(f"\n# ── {job['label']}  ({ip}) ──")
        print(f"# 1. Create remote dir")
        print(f"ssh -i {key} {user}@{ip} 'mkdir -p {rdir}/{{azure_training,training_data,outputs}}'")
        print()
        print(f"# 2. Upload training script + datasets")
        for f in UPLOAD_FILES:
            local_path = repo_root / f
            remote_path = f"{rdir}/{f}"
            # Ensure remote subdirectory exists
            print(f"scp -i {key} {local_path} {user}@{ip}:{remote_path}")
        print()
        print(f"# 3. Run VM setup (first time only)")
        print(f"ssh -i {key} {user}@{ip} 'bash {rdir}/azure_training/setup_vm.sh'")
        print()
        print(f"# 4. Launch training in background")
        train_cmd = _make_train_cmd(job, user)
        print(f"ssh -i {key} {user}@{ip} '{train_cmd}'")
        print()
        print(f"# 5. Tail log")
        log = f"{rdir}/train_{job['persona']}.log"
        print(f"ssh -i {key} {user}@{ip} 'tail -f {log}'")

    print("\n" + "=" * 68)
    print("  After training completes on each VM:")
    print("=" * 68)
    for ip, job in zip(ips, VM_JOBS):
        rdir  = REMOTE_DIR.format(user=user)
        label = f"lora_adapter_{job['persona']}_8b"
        gguf  = f"{rdir}/outputs/gguf/{job['persona']}-8b"
        print(f"\n# Download GGUF from {ip} ({job['label']})")
        print(f"scp -i {key} -r {user}@{ip}:{gguf} ./azure_outputs/{label}_gguf")
    print()


def deploy_with_paramiko(ips: list[str], key: str, user: str, dry_run: bool) -> None:
    try:
        import paramiko
    except ImportError:
        print("[deploy] paramiko not installed — falling back to printed commands.")
        print("[deploy] Install with: pip install paramiko")
        print_ssh_commands(ips, key, user)
        return

    repo_root = Path(__file__).resolve().parent.parent

    for ip, job in zip(ips, VM_JOBS):
        rdir = REMOTE_DIR.format(user=user)
        print(f"\n[deploy] Connecting to {ip} ({job['label']})…")

        if dry_run:
            print(f"  [DRY RUN] Would SSH to {user}@{ip}")
            print(f"  [DRY RUN] Train cmd: {_make_train_cmd(job, user)}")
            continue

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=user, key_filename=key, timeout=30)

        # Create directories
        _exec(ssh, f"mkdir -p {rdir}/{{azure_training,training_data,outputs}}")

        # Upload files
        sftp = ssh.open_sftp()
        for rel_path in UPLOAD_FILES:
            local  = repo_root / rel_path
            remote = f"{rdir}/{rel_path}"
            if not local.exists():
                print(f"  [WARN] Local file not found: {local} — skipping")
                continue
            print(f"  upload {rel_path}…")
            sftp.put(str(local), remote)
        sftp.close()

        # Launch training
        train_cmd = _make_train_cmd(job, user)
        print(f"  launching: {train_cmd}")
        _exec(ssh, train_cmd)

        ssh.close()
        print(f"  [OK] {job['label']} started.")

    print("\n[deploy] All VMs launched.")
    print("[deploy] Monitor with:")
    for ip, job in zip(ips, VM_JOBS):
        rdir = REMOTE_DIR.format(user=user)
        print(f"  ssh -i {key} {user}@{ip} 'tail -f {rdir}/train_{job[\"persona\"]}.log'")


def _exec(ssh, cmd: str) -> str:  # noqa: ANN001
    _, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if err:
        print(f"  [stderr] {err}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy Albedo training to 4× Azure T4 VMs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Example:
              python deploy_training.py \\
                --ips 20.10.1.1 20.10.1.2 20.10.1.3 20.10.1.4 \\
                --key ~/.ssh/azure_t4.pem

            Dry run (print SSH commands only):
              python deploy_training.py --ips ... --key ... --dry-run
        """),
    )
    parser.add_argument("--ips",     nargs=4, metavar="IP",   required=True,
                        help="4 VM public IP addresses in order")
    parser.add_argument("--key",     metavar="PEM",           required=True,
                        help="Path to SSH private key (.pem)")
    parser.add_argument("--user",    default="azureuser",
                        help="SSH username (default: azureuser)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print SSH commands without executing them")
    parser.add_argument("--print-only", action="store_true",
                        help="Print manual SSH commands (no paramiko needed)")

    args = parser.parse_args()

    if args.print_only or args.dry_run:
        print_ssh_commands(args.ips, args.key, args.user)
        if not args.dry_run:
            return

    deploy_with_paramiko(args.ips, args.key, args.user, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
