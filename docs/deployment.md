# AWS ECS Deployment Guide for NEET Knowledge RAG

This guide outlines a realistic and logical plan to deploy the NEET Knowledge RAG application to AWS ECS (Elastic Container Service) using Fargate.

## 1. Prerequisites

*   **AWS Account**: An active AWS account.
*   **AWS CLI**: Installed and configured (`aws configure`).
*   **Docker**: Installed locally.
*   **GitHub Repository**: Code pushed to a GitHub repository.
*   **Domain Name (Optional)**: For SSL/TLS (ACM Certificate).

## 2. Containerization (Docker)

We need to containerize the application. Create a `Dockerfile` in the root directory.

### `Dockerfile` (ARM64 & Spot Optimized)

We will use a multi-arch compatible base image and `pip` to install pre-built ARM64 wheels for FAISS and Torch.

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# ffmpeg, tesseract, and poppler are available on ARM64 debian
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    ffmpeg \
    tesseract-ocr \
    poppler-utils \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
# pip automatically downloads faiss-cpu and torch aarch64 wheels
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Create a non-root user
RUN useradd -m -u 1000 appuser
USER appuser

# Healthcheck
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Run the application
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

> **Note on Building**: To build for ARM64 on an x86 machine (like standard GitHub Actions runners), use `docker buildx`:
> ```bash
> docker buildx build --platform linux/arm64 -t <repo-url>:latest --push .
> ```

## 3. Infrastructure Setup (AWS)

We will use **AWS Fargate** for serverless container management.

### Step 3.1: ECR (Elastic Container Registry)

1.  Create an ECR repository named `neet-knowledge-rag`.
2.  Authenticate docker to your registry:
    ```bash
    aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <aws_account_id>.dkr.ecr.<region>.amazonaws.com
    ```

### Step 3.2: Networking (VPC & ALB)

1.  **VPC**: Use default or create a new VPC with public and private subnets.
2.  **Security Groups**:
    *   **ALB SG**: Allow inbound HTTP (80) and HTTPS (443) from `0.0.0.0/0`.
    *   **ECS Task SG**: Allow inbound TCP on port `8501` *only* from the ALB SG.
3.  **Application Load Balancer (ALB)**:
    *   Create an ALB in public subnets.
    *   Create a Target Group (IP type) on port `8501`.
    *   Set Health Check path to `/_stcore/health`.

### Step 3.3: Persistence (EFS) - *Critical*

The application stores the vector index (FAISS) and other data in the `data/` directory. To persist this across container restarts:

1.  **Create an EFS File System**.
2.  **Create Access Points**: Create an access point for the application (e.g., `/data`).
3.  **Security Group**: Allow inbound NFS (2049) from the **ECS Task SG**.

### Step 3.4: ECS Cluster & Task Definition

1.  **Cluster**: Create an ECS Cluster (Fargate).
2.  **Task Definition**:
    *   **Launch Type**: Fargate.
    *   **OS/Architecture**: Linux/ARM64.
    *   **Task Role**: Needs permissions for ECR pull, CloudWatch Logs, and EFS access.
    *   **Container Definition**:
        *   Image: `<aws_account_id>.dkr.ecr.<region>.amazonaws.com/neet-knowledge-rag:latest`
        *   Port Mappings: `8501`
        *   **Environment Variables**:
            *   `OPENAI_API_KEY`: (Value or ARN from Secrets Manager)
            *   `OPENAI_BASE_URL`: `https://openrouter.ai/api/v1`
            *   `OPENAI_MODEL_NAME`: `google/gemini-2.0-flash-001`
    *   **Storage (Volumes)**:
        *   Add Volume: Name `efs-data`, Source `EFS`.
        *   Select the EFS ID created in Step 3.3.
    *   **Mount Points**:
        *   Container: `neet-knowledge-rag`
        *   Source Volume: `efs-data`
        *   Container Path: `/app/data`

### Step 3.5: ECS Service & Scaling (Crucial for 1000 Users)

To handle **1000 concurrent users** cost-effectively, we will use **ARM64 Architecture (Graviton)** and **Fargate Spot Instances**. This combination can reduce compute costs by **up to 70%**.

1.  **Service Configuration**:
    *   **Launch Type**: Fargate.
    *   **Architecture**: `ARM64` (Graviton).
    *   **Task Size**: 
        *   **CPU**: `2048` (2 vCPU)
        *   **Memory**: `4096` (4 GB)
    *   **Desired Tasks**: Start with **20** tasks.
    *   **Capacity Provider Strategy**:
        *   **Provider**: `FARGATE_SPOT` (Weight: 3) - *Run 75% of tasks on Spot (Save ~70%)*
        *   **Provider**: `FARGATE` (Weight: 1) - *Run 25% on On-Demand (Guarantee availability)*
    *   **Load Balancing**:
        *   Attach ALB.
        *   **Stickiness (MANDATORY)**: Enable sticky sessions (1 day).
    
2.  **Auto-scaling**:
    *   **Metric**: CPU Utilization (Target: 70%).
    *   **Min Tasks**: 5.
    *   **Max Tasks**: 50.

3.  **FAISS Concurrency Strategy**:
    *   **Readers**: Streamlit containers read FAISS from EFS.
    *   **Writers**: Singleton ingest task (On-Demand only) updates EFS.
    *   **Updates**: Restart Streamlit service to reload index.

## 4. CI/CD Pipeline (GitHub Actions)

Create `.github/workflows/deploy.yml` to automate deployment.

### Secrets Required in GitHub:
*   `AWS_ACCESS_KEY_ID`
*   `AWS_SECRET_ACCESS_KEY`
*   `AWS_REGION`
*   `ECR_REPOSITORY` (e.g., `neet-knowledge-rag`)

### Workflow File (`.github/workflows/deploy.yml`)

```yaml
name: Deploy to Amazon ECS

on:
  push:
    branches:
      - main

env:
  AWS_REGION: us-east-1                   # set this to your preferred AWS region, e.g. us-west-1
  ECR_REPOSITORY: neet-knowledge-rag      # set this to your Amazon ECR repository name
  ECS_SERVICE: neet-rag-service           # set this to your Amazon ECS service name
  ECS_CLUSTER: neet-rag-cluster           # set this to your Amazon ECS cluster name
  ECS_TASK_DEFINITION: .aws/task-def.json # path to your Amazon ECS task definition file
  CONTAINER_NAME: neet-knowledge-rag      # set this to the name of the container in the containerDefinitions section of your task definition

jobs:
  deploy:
    name: Deploy
    runs-on: ubuntu-latest
    environment: production

    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v1
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v1

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v2

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2

      - name: Build and push multi-arch image to Amazon ECR
        id: build-image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          # Build for ARM64 (Graviton) and AMD64 (Standard)
          docker buildx build \
            --platform linux/arm64 \
            --push \
            -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG \
            -t $ECR_REGISTRY/$ECR_REPOSITORY:latest .
          echo "image=$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" >> $GITHUB_OUTPUT

      - name: Download task definition
        run: |
          aws ecs describe-task-definition --task-definition neet-rag-task --query taskDefinition > task-definition.json

      - name: Fill in the new image ID in the Amazon ECS task definition
        id: task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: task-definition.json
          container-name: ${{ env.CONTAINER_NAME }}
          image: ${{ steps.build-image.outputs.image }}

      - name: Deploy Amazon ECS task definition
        uses: aws-actions/amazon-ecs-deploy-task-definition@v1
        with:
          task-definition: ${{ steps.task-def.outputs.task-definition }}
          service: ${{ env.ECS_SERVICE }}
          cluster: ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true

### Task Definition JSON (`.aws/task-def.json`)

Ensure your task definition includes the `runtimePlatform` for ARM64:

```json
{
  "runtimePlatform": {
    "cpuArchitecture": "ARM64",
    "operatingSystemFamily": "LINUX"
  },
  "containerDefinitions": [
    ...
  ]
}
```
```

## 5. Environment Variables & Secrets

For sensitive data (API Keys):
1.  **AWS Systems Manager Parameter Store** or **Secrets Manager**: Store `OPENAI_API_KEY`.
2.  **Task Definition**: Reference the secret ARN in the `secrets` section of the container definition, rather than plain text `environment` variables.

## 6. Monitoring & Logging

*   **CloudWatch Logs**: Enabled by default in Fargate task definition (`awslogs` driver).
*   **Container Insights**: Enable on the ECS Cluster for metrics (CPU, Memory).
*   **Application Insights**: Consider setting up CloudWatch Application Insights for deeper visibility into Python errors.

## 7. Scaling to 1000+ Concurrent Users

### 7.1 Architecture Overview

To support 1000 concurrent users, we implement a **split architecture**:

```
┌────────────────────────────────────────────────────────────────┐
│                     Application Load Balancer                   │
│              (WebSocket Support + Sticky Sessions)              │
└────────────┬───────────────────────────────────┬───────────────┘
             │                                   │
             ▼                                   ▼
┌────────────────────────────┐      ┌────────────────────────────┐
│  Query Service (ECS)       │      │  Ingest Service (ECS)      │
│  - Multiple tasks (20-40)  │      │  - Single task             │
│  - Read-only FAISS access  │      │  - Write operations only   │
│  - Auto-scaling enabled    │      │  - Manual scaling          │
└────────────┬───────────────┘      └────────────┬───────────────┘
             │                                   │
             │          ┌────────────────────────┘
             │          │
             ▼          ▼
    ┌─────────────────────────┐
    │   EFS (Shared Storage)  │
    │  - FAISS Index (read)   │
    │  - Audio files          │
    │  - Source metadata      │
    └─────────────────────────┘
```

### 7.2 FAISS Concurrency Strategy

**Key Constraints:**
- ✅ FAISS CPU indices are **thread-safe for concurrent reads**
- ❌ FAISS is **NOT thread-safe for writes** (requires mutual exclusion)
- ⚠️ Each container must **load its own copy** of the index into memory (cannot share memory-mapped files across processes)

**Solution: Read/Write Separation**

#### Query Service (Read-Only)
```python
# Load FAISS index into memory on container startup
# src/rag/vector_store.py

class VectorStoreManager:
    def __init__(self, index_path: str):
        self.index_path = index_path
        self.index = None
        self.last_reload = None
        
    def load_index(self):
        """Load FAISS index from EFS into container memory"""
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
            self.last_reload = time.time()
            logger.info(f"Loaded FAISS index with {self.index.ntotal} vectors")
    
    def maybe_reload(self, check_interval: int = 300):
        """Reload index if file has been modified"""
        if time.time() - self.last_reload > check_interval:
            mtime = os.path.getmtime(self.index_path)
            if mtime > self.last_reload:
                logger.info("Index file modified, reloading...")
                self.load_index()
```

#### Ingest Service (Write-Only)
```python
# Separate service for index updates with file locking
import fcntl

def update_index_with_lock(index_path: str, new_vectors):
    """Update FAISS index with exclusive file lock"""
    lock_file = f"{index_path}.lock"
    
    with open(lock_file, 'w') as lock:
        # Acquire exclusive lock
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        
        try:
            # Load existing index
            index = faiss.read_index(index_path)
            
            # Add new vectors
            index.add(new_vectors)
            
            # Write updated index atomically
            temp_path = f"{index_path}.tmp"
            faiss.write_index(index, temp_path)
            os.rename(temp_path, index_path)
            
            logger.info(f"Index updated: {index.ntotal} total vectors")
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
```

**Implementation Steps:**
1. Split `app.py` into two separate applications:
   - `query_app.py`: Read-only Streamlit interface (no ingestion)
   - `ingest_app.py`: Admin interface for adding/updating content
2. Deploy as two separate ECS services with different task definitions
3. Implement index reload mechanism in query service (check every 5 minutes)

### 7.3 Streamlit Session Stickiness

**Critical:** Streamlit requires **sticky sessions** because it uses WebSockets for real-time updates.

#### ALB Configuration

WebSockets are **inherently sticky** when target group stickiness is enabled:

```bash
# Enable sticky sessions on ALB target group
aws elbv2 modify-target-group-attributes \
  --target-group-arn <your-target-group-arn> \
  --attributes \
    Key=stickiness.enabled,Value=true \
    Key=stickiness.type,Value=lb_cookie \
    Key=stickiness.lb_cookie.duration_seconds,Value=86400
```

**Terraform Example:**
```hcl
resource "aws_lb_target_group" "streamlit_query" {
  name     = "streamlit-query-tg"
  port     = 8501
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/_stcore/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
  }

  stickiness {
    enabled         = true
    type            = "lb_cookie"
    cookie_duration = 86400  # 24 hours
  }

  deregistration_delay = 30
}
```

**Why this works:**
- ALB inserts a `AWSALB` cookie on first request
- All subsequent requests (including WebSocket upgrade) route to the same target
- No additional WebSocket-specific configuration needed

### 7.4 Task CPU/Memory Sizing for 1000 Users

**Measured Streamlit Memory Consumption:**
- Idle container: 50-100 MB
- **Per active user session: 150-300 MB** (depends on session_state usage)
- FAISS index in memory: 500 MB - 2 GB (depends on corpus size)

**Recommended Configuration: Many Small Tasks (Preferred)**

```yaml
Task Definition:
  CPU: 2048 (2 vCPU)
  Memory: 4096 MB (4 GB)
  
Capacity Planning:
  - FAISS index: 1 GB
  - Base Streamlit: 100 MB
  - Available for sessions: 3 GB
  - Sessions per task: 30-40 concurrent users (3000 MB / 100 MB)
  
Scaling:
  - Target: 1000 concurrent users
  - Tasks needed: 25-35 tasks
  - With buffer: 40 max tasks
```

**Alternative: Fewer Large Tasks**

```yaml
Task Definition:
  CPU: 4096 (4 vCPU)
  Memory: 8192 MB (8 GB)
  
Capacity Planning:
  - FAISS index: 1 GB
  - Base Streamlit: 100 MB
  - Available for sessions: 7 GB
  - Sessions per task: 70-90 concurrent users
  
Scaling:
  - Target: 1000 concurrent users
  - Tasks needed: 12-15 tasks
  - With buffer: 20 max tasks
```

**Which to choose?**
- **Small tasks**: Better fault isolation, faster cold starts, lower cost with variable load
- **Large tasks**: Better for very large FAISS indexes (>3GB), slightly lower overhead

### 7.5 Auto-Scaling Configuration

```bash
# Register scalable target
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/neet-rag-cluster/neet-rag-query-service \
  --min-capacity 5 \
  --max-capacity 40

# Target tracking: CPU utilization
aws application-autoscaling put-scaling-policy \
  --policy-name cpu-target-tracking \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/neet-rag-cluster/neet-rag-query-service \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://scaling-policy.json
```

**scaling-policy.json:**
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

**Scaling Parameters Explained:**
- **Target: 60% CPU**: Leaves headroom for traffic spikes
- **Min: 5 tasks**: Handles ~150-250 baseline users
- **Max: 40 tasks**: Supports 1200-1600 peak users
- **Scale-out cooldown: 60s**: Fast response to load increases
- **Scale-in cooldown: 300s**: Prevents flapping during variable load

### 7.6 Memory Management Best Practices

**Problem:** Streamlit has known memory leaks with `session_state` and cached data.

**Solutions:**

#### 1. Clear Session State Properly
```python
# app.py - Add session timeout
import streamlit as st
from datetime import datetime, timedelta

# Check session age
if 'created_at' not in st.session_state:
    st.session_state.created_at = datetime.now()

session_age = datetime.now() - st.session_state.created_at
if session_age > timedelta(hours=2):
    st.session_state.clear()
    st.rerun()
```

#### 2. Use TTL on Cached Data
```python
# Cache FAISS index with TTL
@st.cache_resource(ttl=3600)  # Reload every hour
def load_vector_store():
    return VectorStoreManager(index_path="/app/data/faiss_index")

# Cache with max entries
@st.cache_data(ttl=600, max_entries=100)
def get_query_results(query: str):
    return rag.query(query)
```

#### 3. Monitor Memory Usage
```python
# Add memory monitoring
import psutil
import os

def check_memory():
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / 1024 / 1024
    if mem_mb > 3500:  # 3.5 GB warning threshold for 4GB task
        logger.warning(f"High memory usage: {mem_mb:.1f} MB")
        return True
    return False

# In main app loop
if check_memory():
    st.warning("High memory usage detected. Please refresh the page.")
```

### 7.7 Cost Estimation (US-East-1) - ARM64 Spot Optimized

By switching to **ARM64 (Graviton)** and **Fargate Spot**, we can achieve significant savings:

**Unit Costs (2 vCPU / 4 GB):**
- **x86 On-Demand**: ~$0.058/hour
- **ARM64 On-Demand**: ~$0.046/hour (*~20% savings*)
- **ARM64 Spot**: ~$0.014/hour (*~76% savings*)

**Monthly Cost Scenarios (20 Tasks):**

| Configuration | Hourly | Monthly (720h) | Annual Savings |
|---------------|--------|----------------|----------------|
| **x86 On-Demand** | $1.16 | **$835** | - |
| **ARM64 On-Demand** | $0.92 | **$662** | $2,076 |
| **ARM64 Spot (100%)** | $0.28 | **$201** | **$7,608** |
| **Mixed (25% OD / 75% Spot)** | $0.44 | **$316** | **$6,228** |

**Recommendation**: Use **Mixed Strategy** (25% On-Demand base, 75% Spot scaling) for the best balance of cost and reliability.

**Additional Costs:**
- EFS: ~$0.30/GB/month
- ALB: ~$60/month
- **Estimated Total**: **~$400-500/month** (vs ~$1,500 for x86 On-Demand).

### Step 7.8 Deployment Checklist

- [ ] Build multi-arch image (`linux/arm64`) using `docker buildx`
- [ ] Configure ECS Task Definition for `ARM64` architecture
- [ ] Use `FARGATE_SPOT` Capacity Provider Strategy (e.g., 75% Spot, 25% On-Demand)
- [ ] Split application into query (Spot) and ingest (On-Demand) services
- [ ] Implement FAISS index reload mechanism
- [ ] Configure ALB target group with sticky sessions
- [ ] Set health check to `/_stcore/health`
- [ ] Enable WebSocket support on ALB (HTTP/1.1 upgrade headers)
- [ ] Size tasks: 2 vCPU / 4 GB for 30-40 users per task
- [ ] Configure auto-scaling: min 5, max 40, target 60% CPU
- [ ] Add memory monitoring and session timeout
- [ ] Enable CloudWatch Container Insights
- [ ] Set up CloudWatch Alarms for:
  - High memory utilization (>80%)
  - Task launch failures
  - ALB target health checks
  - EFS throughput limits

### 7.9 Monitoring Metrics to Track

```bash
# Key CloudWatch metrics to monitor:
1. ECSServiceAverageCPUUtilization - Target: 50-70%
2. ECSServiceAverageMemoryUtilization - Alert: >85%
3. TargetResponseTime - Target: <1000ms
4. HealthyHostCount - Alert if < 3
5. UnHealthyHostCount - Alert if > 0
6. ActiveConnectionCount - Track concurrent WebSocket connections
7. EFS BurstCreditBalance - Alert if depleting (scale EFS if needed)
```

## 8. Troubleshooting

### WebSocket Connection Failures
**Symptom:** "WebSocket connection failed" in browser console

**Solutions:**
1. Verify ALB security group allows inbound 443/80
2. Check ECS task security group allows 8501 from ALB
3. Ensure sticky sessions enabled on target group
4. Verify health check path: `/_stcore/health`
5. Check CloudWatch Logs for Streamlit errors

### High Memory Usage
**Symptom:** Tasks being killed by OOM (Out of Memory)

**Solutions:**
1. Reduce `max_entries` in `@st.cache_data` decorators
2. Add session timeout mechanism (clear old sessions)
3. Profile memory usage: `pip install memory-profiler`
4. Consider increasing task memory size
5. Implement periodic container restarts (task definition revision)

### FAISS Index Not Updating
**Symptom:** New content not appearing in search results

**Solutions:**
1. Check ingest service logs for errors
2. Verify EFS mount point accessible: `ls -la /app/data/`
3. Ensure query service reloading index (check reload logs)
4. Test file lock mechanism: `lsof /app/data/faiss_index/*.lock`
5. Manually trigger index reload via admin endpoint

### Slow Query Performance
**Symptom:** Search taking >5 seconds

**Solutions:**
1. Profile FAISS index size: `index.ntotal` should be <5M vectors
2. Consider FAISS index optimization (IVF, PQ compression)
3. Increase task CPU allocation (more cores help FAISS)
4. Use FAISS GPU indices if index is very large (>10M vectors)
5. Implement query result caching with higher TTL

## References

- [FAISS Threading Documentation](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls)
- [AWS ALB Sticky Sessions Guide](https://docs.aws.amazon.com/prescriptive-guidance/latest/load-balancer-stickiness/)
- [Streamlit Scaling Best Practices](https://discuss.streamlit.io/t/how-to-scale-streamlit-app-for-multiple-concurrent-users-on-aws/58709)
- [ECS Task Sizing Guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/capacity-tasksize.html)
