# Quick Reference: Scaling to 1000 Users

## TL;DR - Critical Facts

| Question | Answer |
|----------|--------|
| **Can FAISS handle concurrent reads on EFS?** | ✅ YES - Thread-safe for reads, NOT for writes |
| **Do we need session stickiness?** | ✅ YES - Mandatory for Streamlit WebSockets |
| **How much RAM per user?** | 150-300 MB per active session |
| **Recommended task size?** | 2 vCPU / 4 GB RAM |
| **Users per task?** | 30-40 concurrent users |
| **Tasks needed for 1000 users?** | 25-35 tasks (scale 5-40) |
| **Monthly cost?** | ~$1,330 ($1.33/user) |

---

## Must-Do Configurations

### 1. ALB Sticky Sessions (MANDATORY)
```bash
aws elbv2 modify-target-group-attributes \
  --target-group-arn arn:aws:elasticloadbalancing:... \
  --attributes \
    Key=stickiness.enabled,Value=true \
    Key=stickiness.type,Value=lb_cookie \
    Key=stickiness.lb_cookie.duration_seconds,Value=86400
```

### 2. ECS Task Definition
```json
{
  "cpu": "2048",
  "memory": "4096",
  "containerDefinitions": [{
    "name": "streamlit-query",
    "image": "YOUR_ECR_IMAGE",
    "portMappings": [{"containerPort": 8501}],
    "mountPoints": [{
      "sourceVolume": "efs-data",
      "containerPath": "/app/data"
    }],
    "healthCheck": {
      "command": ["CMD-SHELL", "curl -f http://localhost:8501/_stcore/health || exit 1"]
    }
  }]
}
```

### 3. Auto-Scaling Policy
```json
{
  "TargetValue": 60.0,
  "PredefinedMetricSpecification": {
    "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
  },
  "ScaleOutCooldown": 60,
  "ScaleInCooldown": 300
}
```

Min: 5 tasks, Max: 40 tasks, Target: 60% CPU

---

## Code Changes Required

### Split Architecture (Priority 1)

**Current:** Single `app.py` (query + ingest)  
**Target:** Two separate services

#### query_app.py (Read-Only Service)
```python
import streamlit as st
from src.rag.vector_store import VectorStoreManager

# Load FAISS index once per container
@st.cache_resource
def load_vector_store():
    manager = VectorStoreManager("/app/data/faiss_index")
    manager.load_index()
    return manager

# Periodic reload check
def maybe_reload_index(manager):
    if manager.should_reload(check_interval=300):  # 5 min
        manager.load_index()
        st.success("Index updated!")

# Main app - query only
vector_store = load_vector_store()
maybe_reload_index(vector_store)

query = st.text_input("Ask a question:")
if query:
    results = vector_store.search(query)
    st.write(results)
```

#### ingest_app.py (Write Service - Single Task)
```python
import streamlit as st
import fcntl
from src.rag.vector_store import VectorStoreManager

def update_index_with_lock(index_path, new_vectors):
    lock_path = f"{index_path}.lock"
    with open(lock_path, 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            # Update index atomically
            manager = VectorStoreManager(index_path)
            manager.load_index()
            manager.add_vectors(new_vectors)
            manager.save_index_atomic()  # Write to .tmp, then rename
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

# Admin interface for adding content
st.title("Admin: Add Content")
uploaded_file = st.file_uploader("Upload PDF")
if uploaded_file and st.button("Ingest"):
    vectors = process_file(uploaded_file)
    update_index_with_lock("/app/data/faiss_index", vectors)
    st.success("Index updated!")
```

### Memory Management (Priority 2)

#### Add Session Timeout
```python
# Add to query_app.py
from datetime import datetime, timedelta

if 'created_at' not in st.session_state:
    st.session_state.created_at = datetime.now()

# Timeout after 2 hours
if datetime.now() - st.session_state.created_at > timedelta(hours=2):
    st.session_state.clear()
    st.rerun()
```

#### Add Memory Monitoring
```python
import psutil
import os

def check_memory():
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / 1024 / 1024
    if mem_mb > 3500:  # 87.5% of 4GB
        st.warning(f"⚠️ High memory usage: {mem_mb:.0f} MB. Please refresh.")
        return True
    return False

# Call periodically
if st.session_state.get('query_count', 0) % 10 == 0:
    check_memory()
```

### Cache Configuration (Priority 3)

```python
# Aggressive TTL to prevent memory growth
@st.cache_data(ttl=600, max_entries=100)  # 10 min, 100 queries
def get_query_results(query: str):
    return rag.query(query)

# Resource cache for heavy objects
@st.cache_resource(ttl=3600)  # Reload FAISS every hour
def load_vector_store():
    return VectorStoreManager("/app/data/faiss_index")
```

---

## Deployment Checklist

### Pre-Deployment
- [ ] Build and push Docker image to ECR
- [ ] Create EFS file system with mount targets
- [ ] Create ALB with HTTPS listener (ACM certificate)
- [ ] Create two target groups: `query-tg` and `ingest-tg`
- [ ] Enable sticky sessions on query target group
- [ ] Create ECS cluster (Fargate)
- [ ] Create IAM task role (ECR, CloudWatch, EFS permissions)

### Infrastructure
- [ ] Deploy query service: 5-40 tasks, 2vCPU/4GB
- [ ] Deploy ingest service: 1 task, 2vCPU/4GB
- [ ] Configure auto-scaling: target 60% CPU
- [ ] Set up CloudWatch alarms:
  - [ ] CPU > 80%
  - [ ] Memory > 85%
  - [ ] Unhealthy targets > 0
  - [ ] Target response time > 2s
- [ ] Enable Container Insights
- [ ] Test sticky sessions: `curl -c cookies.txt https://your-alb.com`

### Code
- [ ] Split `app.py` into `query_app.py` and `ingest_app.py`
- [ ] Implement index reload mechanism (check mtime every 5 min)
- [ ] Add file locking to ingest service (`fcntl.flock`)
- [ ] Add session timeout (2 hours)
- [ ] Add memory monitoring
- [ ] Configure cache TTLs (10 min for queries, 1 hour for index)
- [ ] Test locally with Docker Compose

### Testing
- [ ] Load test with Locust/k6: 100 → 500 → 1000 users
- [ ] Verify auto-scaling triggers at 60% CPU
- [ ] Test index update during query load (no errors)
- [ ] Test task failure recovery (kill task, verify reconnect)
- [ ] Monitor memory growth over 1 hour
- [ ] Test WebSocket persistence (same AWSALB cookie)

---

## Troubleshooting Commands

### Check ALB Sticky Sessions
```bash
# Verify cookie is set
curl -i https://your-alb.amazonaws.com | grep AWSALB

# Test session persistence
curl -c cookies.txt https://your-alb.amazonaws.com
curl -b cookies.txt https://your-alb.amazonaws.com  # Should hit same target
```

### Check ECS Task Health
```bash
# List running tasks
aws ecs list-tasks --cluster neet-rag-cluster --service-name neet-rag-query

# Get task details
aws ecs describe-tasks --cluster neet-rag-cluster --tasks TASK_ARN

# Check container health
aws ecs describe-tasks --cluster neet-rag-cluster --tasks TASK_ARN \
  --query 'tasks[0].containers[0].healthStatus'
```

### Check FAISS Index
```bash
# SSH to container (ECS Exec)
aws ecs execute-command \
  --cluster neet-rag-cluster \
  --task TASK_ARN \
  --container streamlit-query \
  --interactive \
  --command "/bin/bash"

# Inside container
ls -lh /app/data/faiss_index/
python -c "import faiss; idx=faiss.read_index('/app/data/faiss_index/index.faiss'); print(f'Vectors: {idx.ntotal}')"
```

### Check Memory Usage
```bash
# CloudWatch Insights query
fields @timestamp, @message
| filter @message like /High memory usage/
| stats count() by bin(5m)

# ECS task memory utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name MemoryUtilization \
  --dimensions Name=ServiceName,Value=neet-rag-query \
  --start-time 2026-02-17T00:00:00Z \
  --end-time 2026-02-17T23:59:59Z \
  --period 300 \
  --statistics Average
```

---

## Performance Targets

| Metric | Target | Alert Threshold |
|--------|--------|----------------|
| Query latency (p95) | < 2s | > 5s |
| FAISS search time | < 200ms | > 500ms |
| Memory per task | 2-3 GB | > 3.5 GB (85%) |
| CPU per task | 50-70% | > 80% |
| Concurrent users per task | 30-40 | > 50 |
| Task startup time | < 30s | > 60s |
| Index reload time | < 10s | > 30s |
| WebSocket reconnect time | < 3s | > 10s |

---

## Cost Monitoring

### Daily Cost Check
```bash
# ECS Fargate costs (last 7 days)
aws ce get-cost-and-usage \
  --time-period Start=2026-02-10,End=2026-02-17 \
  --granularity DAILY \
  --metrics BlendedCost \
  --filter file://filter.json

# filter.json
{
  "Dimensions": {
    "Key": "SERVICE",
    "Values": ["Amazon Elastic Container Service"]
  }
}
```

### Cost Breakdown (Expected)
```
Daily:  $45  (baseline 5 tasks + peak 20 tasks avg)
Weekly: $315
Monthly: $1,350

By component:
- ECS Fargate: $1,120 (83%)
- ALB: $82 (6%)
- EFS: $25 (2%)
- Data Transfer: $45 (3%)
- CloudWatch: $60 (4%)
```

---

## Monitoring Dashboard URLs

Once deployed, bookmark these:
- **CloudWatch Dashboard**: https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=NEET-RAG-Production
- **ECS Service**: https://console.aws.amazon.com/ecs/v2/clusters/neet-rag-cluster/services/neet-rag-query
- **ALB Target Groups**: https://console.aws.amazon.com/ec2/v2/home?region=us-east-1#TargetGroups:
- **EFS Console**: https://console.aws.amazon.com/efs/home?region=us-east-1
- **Cost Explorer**: https://console.aws.amazon.com/cost-management/home?region=us-east-1#/cost-explorer

---

## Emergency Procedures

### High Memory Alert
1. Check CloudWatch Logs for memory warnings
2. Identify problematic tasks: `aws ecs describe-tasks ...`
3. Manually restart task: Stop task, ECS will auto-replace
4. If widespread: Reduce `max_entries` in cache decorators
5. Emergency: Scale up task size to 8 GB

### Index Corruption
1. Check ingest service logs for errors
2. Verify lock file: `ls -l /app/data/faiss_index/*.lock`
3. Restore from backup (if configured)
4. Rebuild index from sources: `python -m src.main reingest-all`

### Complete Outage
1. Check ALB health: All targets unhealthy?
2. Check ECS tasks: All tasks stopped?
3. Check EFS: Mount target accessible?
4. Emergency rollback: `aws ecs update-service --task-definition PREVIOUS_VERSION`
5. Scale to zero and back: `aws ecs update-service --desired-count 0`, then back to 5

---

## Next Steps

1. **Read full docs**: `docs/deployment.md` (detailed guide)
2. **Review architecture**: `docs/ARCHITECTURE_DIAGRAM.md` (visual flows)
3. **Understand research**: `docs/SCALING_SUMMARY.md` (evidence-based decisions)
4. **Implement split**: Start with `query_app.py` and `ingest_app.py`
5. **Test locally**: Docker Compose with 2 services + shared volume
6. **Deploy to dev**: Single task each, verify functionality
7. **Load test**: Gradually increase to 100 → 500 → 1000 users
8. **Monitor & tune**: Adjust cache TTLs, task sizes based on real usage

**Questions?** Check docs or reach out to DevOps team.
