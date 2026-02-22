# ECS Shell Access

This repo now enables ECS Exec on both services (`streamlit` and `worker`) so you can open an interactive shell in running Fargate tasks.

## 1) Terraform changes included

- ECS services set `enable_execute_command = var.enable_ecs_exec`.
- Task role includes required `ssmmessages:*Channel` actions.
- New variable: `enable_ecs_exec` (default `true`).

## 2) Prerequisites on your machine

- AWS CLI v2 installed and configured.
- Session Manager plugin installed.
- IAM permissions for your user/role:
  - `ecs:ExecuteCommand`
  - `ecs:ListTasks`
  - `ecs:DescribeTasks`
  - `ssm:StartSession`

## 3) Apply infra

```bash
cd deploy
terraform apply
```

## 4) Open shell using helper script

From repository root:

```bash
./deploy/ecs_shell.sh ap-south-1 np-pgrest neet-prod-worker worker
./deploy/ecs_shell.sh ap-south-1 np-pgrest neet-prod-streamlit streamlit
```

Arguments:

1. AWS region
2. ECS cluster name
3. ECS service name
4. Optional container name

The script picks the first running task for the service and runs:

```bash
aws ecs execute-command --interactive --command /bin/sh
```

## 5) Query SQLite inside worker shell

Once in the worker shell:

```bash
sqlite3 /shared/data/sources.db
```

Useful commands:

```sql
.tables
PRAGMA journal_mode;
SELECT source_id, source_type, status, updated_at FROM sources ORDER BY updated_at DESC LIMIT 20;
```

## 6) Probe FAISS snippets for a user phrase

From repo root (local or inside a task with code mounted):

```bash
./faiss_probe.sh "work done at constant pressure" --top-k 8 --show-prompt
```

Make shortcut:

```bash
make faiss-probe QUERY="work done at constant pressure" TOP_K=8
```
