# AWS ECS Deployment Plan for NEET Knowledge RAG

## Executive Summary

Deploy the NEET Knowledge RAG system to AWS ECS with auto-scaling, load balancing, and persistent storage for production use. The architecture separates the web frontend from the RAG processing engine for better scalability.

---

## 1. Current Architecture Analysis

### Technology Stack
| Component | Technology | Notes |
|-----------|------------|-------|
| Frontend | Streamlit | Single-user, session-based |
| RAG Engine | LangChain | Handles document processing & retrieval |
| Vector DB | FAISS | Local file-based, in-memory |
| Embeddings | HuggingFace (all-MiniLM-L6-v2) | CPU-bound |
| LLM | OpenRouter/Gemini | External API |
| Storage | Local filesystem | `./data/` directory |

### Challenges for Production
1. **FAISS is single-instance** - Not designed for distributed/multi-instance deployments
2. **Session state** - Streamlit reinitializes on reload; chat history lost
3. **File-based storage** - No persistence across container restarts
4. **CPU-heavy processing** - Document ingestion is computationally expensive
5. **External API dependency** - LLM calls have latency considerations

---

## 2. Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AWS Cloud                                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    Application Load Balancer                        │    │
│  │                     (HTTPS, SSL Termination)                        │    │
│  └──────────────────────────────┬──────────────────────────────────────┘    │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐    │
│  │                    AWS ECS Fargate Cluster                          │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │    │
│  │  │  Streamlit │  │  Streamlit │  │  Streamlit │  ... (Auto-scaled)│    │
│  │  │  Frontend  │  │  Frontend  │  │  Frontend  │                  │    │
│  │  │  (Web)     │  │  (Web)     │  │  (Web)     │                  │    │
│  │  └─────┬───────┘  └─────┬───────┘  └─────┬───────┘                  │    │
│  │        │                │                │                          │    │
│  │        └────────────────┼────────────────┘                          │    │
│  │                         │                                             │    │
│  │         ┌──────────────▼──────────────┐                           │    │
│  │         │   Amazon ElastiCache Redis   │  ← Session/Chat History   │    │
│  │         │     (Session Store)          │                           │    │
│  │         └──────────────┬──────────────┘                           │    │
│  │                        │                                            │    │
│  │         ┌──────────────▼──────────────┐                           │    │
│  │         │    Amazon EFS (EFS)         │  ← FAISS Index + Content  │    │
│  │         │  /shared/faiss/            │  ← Shared across all      │    │
│  │         │  /shared/content/          │    Fargate instances     │    │
│  │         │  /shared/audio/            │                           │    │
│  │         └─────────────────────────────┘                           │    │
│  │                        │                                            │    │
│  │         ┌──────────────▼──────────────┐                           │    │
│  │         │    Amazon S3 Bucket         │  ← Backup / Long-term      │    │
│  │         │  /backups/                 │    (optional)             │    │
│  │         └─────────────────────────────┘                           │    │
│  │                                                                    │    │
│  │  ┌─────────────────────────────────────────────────────────────┐  │    │
│  │  │           AWS ECS Fargate - Background Task                │  │    │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │  │    │
│  │  │  │  Ingestion  │  │  Ingestion  │  │  Ingestion │        │  │    │
│  │  │  │   Worker    │  │   Worker    │  │   Worker    │       │  │    │
│  │  │  │  (Async)    │  │  (Async)    │  │  (Async)    │       │  │    │
│  │  │  └─────────────┘  └─────────────┘  └─────────────┘        │  │    │
│  │  └─────────────────────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                        External Services                           │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │     │
│  │  │ OpenRouter  │  │  YouTube    │  │   HuggingFace           │  │     │
│  │  │  (LLM)      │  │   API       │  │   (Embeddings)          │  │     │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘  │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Infrastructure Components

### 3.1 Compute Layer

| Component | AWS Service | Configuration |
|-----------|-------------|---------------|
| **Frontend Service** | ECS Fargate | Streamlit app (2-10 tasks, auto-scale) |
| **Background Worker** | ECS Fargate | Document ingestion (1-4 tasks, on-demand) |
| **Task Scheduler** | AWS EventBridge | Cron for periodic content updates |

### 3.2 Storage Layer

| Component | AWS Service | Purpose |
|-----------|-------------|---------|
| **Vector Index** | Amazon EFS | FAISS index shared across all Fargate instances |
| **Ingested Content** | Amazon EFS | PDFs, transcripts, processed content |
| **Session State** | Amazon ElastiCache Redis | Chat history, user sessions |
| **Task Queue** | Amazon SQS | Background ingestion jobs |
| **Backup (Optional)** | Amazon S3 | Long-term backup of FAISS index |

#### 3.2.1 Data Storage Strategy

This section details where each type of data is stored and why.

##### EFS (Elastic File System) — Persistent Shared Storage

All data that needs to be **shared across Fargate instances** and **persist across deployments** goes to EFS.

```
/shared/
├── data/
│   ├── faiss_index/
│   │   ├── faiss.index      # Main FAISS vector index
│   │   └── metadata.pkl    # Document metadata mapping
│   │
│   ├── content/
│   │   ├── youtube/        # Downloaded transcripts
│   │   ├── pdfs/          # Processed PDF content
│   │   └── text/           # Extracted text chunks
│   │
│   ├── audio/              # Cached audio files (yt-dlp downloads)
│   │
│   └── sources.json        # Source metadata (URLs, status, timestamps)
```

| Data Type | File(s) | Read Frequency | Write Frequency | Rationale |
|-----------|---------|----------------|----------------|-----------|
| FAISS Index | `faiss.index` | High (every query) | Low (on ingestion) | Must be shared across all instances |
| Vector Metadata | `metadata.pkl` | High (with search results) | Low (on ingestion) | Tied to FAISS index |
| Source Metadata | `sources.json` | Medium (listing sources) | Low (add/remove source) | Shared across workers |
| Downloaded Content | `content/*` | Low (re-ingestion) | Medium (new sources) | Cache for reprocessing |
| Audio Cache | `audio/*` | Low | Medium | Avoid re-downloading |

**EFS Performance Notes:**
- Use **bursting mode** (default) for cost efficiency
- For high-traffic, consider **provisioned IOPS**
- EFS costs ~$0.30/GB/month (standard) or ~$0.08/GB/month (IA)

##### Redis (ElastiCache) — Ephemeral Session Storage

Data that is **temporary, high-frequency access, or TTL-based** goes to Redis.

| Data Type | Key Pattern | TTL | Rationale |
|-----------|-------------|-----|-----------|
| Chat History | `chat:{session_id}` | 1 hour | Ephemeral, per-session |
| Query Cache | `query:{hash}` | 24 hours | Avoid re-querying LLM |
| Rate Limiting | `rate:{user_id}` | 1 minute | Prevent abuse |
| API Tokens | `token:{user_id}` | Variable | Auth sessions |

**Redis Configuration:**
```hcl
# ElastiCache Redis settings
node_type = "cache.t3.micro"  # Start small, scale up
num_cache_clusters = 2         # Multi-AZ for HA
auth_token_enabled = true       # Encryption at rest
transit_encryption_enabled = true
```

##### S3 (Simple Storage Service) — Backup & Long-term

Data that is **rarely accessed but needs durability** goes to S3.

| Data Type | Bucket Path | Retention | Rationale |
|-----------|-------------|-----------|-----------|
| FAISS Backup | `s3://neet-knowledge-backup/faiss/` | 90 days | Disaster recovery |
| Source Export | `s3://neet-knowledge-backup/sources/` | Indefinite | Audit trail |
| Logs | `s3://neet-knowledge-logs/ecs/` | 30 days | Compliance |

**S3 Configuration:**
```hcl
# S3 bucket with lifecycle
lifecycle_rule {
  id      = "archive-old-data"
  enabled = true
  
  transition {
    days          = 30
    storage_class = "STANDARD_IA"  # Cheaper after 30 days
  }
  
  transition {
    days          = 90
    storage_class = "GLACIER"      # Archive after 90 days
  }
}
```

##### Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER REQUEST                                    │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                      Fargate Container                                │  │
│  │                                                                       │  │
│  │   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │  │
│  │   │  Streamlit  │───▶│   RAG       │───▶│   LLM       │            │  │
│  │   │  / FastAPI  │    │   Engine    │    │   (API)     │            │  │
│  │   └─────────────┘    └──────┬──────┘    └─────────────┘            │  │
│  │                             │                                         │  │
│  │         ┌──────────────────┼──────────────────┐                     │  │
│  │         ▼                  ▼                  ▼                     │  │
│  │   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐             │  │
│  │   │   Query     │   │    Chat     │   │   Source   │             │  │
│  │   │   Cache    │   │   History   │   │   Config   │             │  │
│  │   │  (Redis)   │   │  (Redis)    │   │   (EFS)    │             │  │
│  │   └─────────────┘   └─────────────┘   └──────┬──────┘             │  │
│  │                                                │                     │  │
│  │                                                ▼                     │  │
│  │   ┌─────────────────────────────────────────────────────┐          │  │
│  │   │              FAISS Vector Index (EFS)               │          │  │
│  │   └─────────────────────────────────────────────────────┘          │  │
│  │                                                                       │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              STORAGE LAYER                                  │
│                                                                             │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐          │
│  │   EFS           │   │   Redis        │   │   S3           │          │
│  │                 │   │   (Cluster)    │   │   (Bucket)     │          │
│  │  /shared/data/  │   │                │   │                │          │
│  │                 │   │  • chat:*      │   │  /backups/     │          │
│  │  • faiss_index │   │  • query:*     │   │  /exports/     │          │
│  │  • content/    │   │  • rate:*      │   │  /logs/        │          │
│  │  • sources.json│   │                │   │                │          │
│  │                 │   │  TTL: 1h-24h  │   │  Retention:    │          │
│  │  Persistent    │   │  Ephemeral     │   │  30-90 days   │          │
│  └─────────────────┘   └─────────────────┘   └─────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

##### File System Structure on EFS

```bash
# Directories created on EFS mount
/shared/
├── data/
│   ├── faiss_index/
│   │   ├── index_flat_l2_384.bin    # Main FAISS index
│   │   ├── index_meta.json          # Index configuration
│   │   └── documents.pkl            # Original documents
│   │
│   ├── content/
│   │   ├── youtube/
│   │   │   └── {video_id}/
│   │   │       ├── metadata.json
│   │   │       ├── transcript.vtt
│   │   │       └── chunks/
│   │   │
│   │   ├── pdfs/
│   │   │   └── {source_id}/
│   │   │       ├── metadata.json
│   │   │       └── chunks/
│   │   │
│   │   └── text/
│   │       └── {source_id}/
│   │           └── chunks/
│   │
│   ├── audio/
│   │   └── {source_id}.webm
│   │
│   └── sources.json                  # Source registry
│
└── logs/                            # Application logs
    └── {date}.log
```

##### Code Integration

```python
# src/utils/storage_paths.py
import os
from dataclasses import dataclass

@dataclass
class StoragePaths:
    """Centralized storage path configuration"""
    
    # EFS base (mounted at /shared/data in containers)
    base_dir: str = os.getenv("DATA_DIR", "/shared/data")
    
    @property
    def faiss_index_dir(self) -> str:
        return os.path.join(self.base_dir, "faiss_index")
    
    @property
    def content_dir(self) -> str:
        return os.path.join(self.base_dir, "content")
    
    @property
    def audio_dir(self) -> str:
        return os.path.join(self.base_dir, "audio")
    
    @property
    def sources_file(self) -> str:
        return os.path.join(self.base_dir, "sources.json")
    
    @property
    def faiss_index_file(self) -> str:
        return os.path.join(self.faiss_index_dir, "index.bin")
    
    @property
    def metadata_file(self) -> str:
        return os.path.join(self.faiss_index_dir, "documents.pkl")
    
    def ensure_dirs(self):
        """Create all directories if they don't exist"""
        for path in [
            self.faiss_index_dir,
            self.content_dir,
            self.audio_dir,
            os.path.join(self.content_dir, "youtube"),
            os.path.join(self.content_dir, "pdfs"),
            os.path.join(self.content_dir, "text"),
        ]:
            os.makedirs(path, exist_ok=True)

# Usage
paths = StoragePaths()
paths.ensure_dirs()
# paths.faiss_index_dir -> "/shared/data/faiss_index"
```

```python
# src/utils/content_manager.py - Updated for EFS
import json
import os
from storage_paths import StoragePaths

class ContentSourceManager:
    """Manages content sources with EFS-backed storage"""
    
    def __init__(self, storage: StoragePaths = None):
        self.storage = storage or StoragePaths()
        self._ensure_sources_file()
    
    def _ensure_sources_file(self):
        """Create sources.json if it doesn't exist"""
        if not os.path.exists(self.storage.sources_file):
            os.makedirs(os.path.dirname(self.storage.sources_file), exist_ok=True)
            with open(self.storage.sources_file, 'w') as f:
                json.dump([], f)
    
    def get_all_sources(self):
        """Load sources from EFS"""
        with open(self.storage.sources_file, 'r') as f:
            return json.load(f)
    
    def save_sources(self, sources):
        """Save sources to EFS"""
        with open(self.storage.sources_file, 'w') as f:
            json.dump(sources, f, indent=2)
    
    def add_youtube(self, url: str, title: str = None):
        """Add YouTube source"""
        sources = self.get_all_sources()
        source_id = f"yt_{len(sources)}"
        sources.append({
            "id": source_id,
            "url": url,
            "title": title or url,
            "type": "youtube",
            "status": "pending",
            "created_at": "..."
        })
        self.save_sources(sources)
        return source_id
```

---

### 3.3 Networking

| Component | AWS Service | Configuration |
|-----------|-------------|---------------|
| **Load Balancer** | Application Load Balancer | HTTPS (ACM), path-based routing |
| **VPC** | VPC with public/private subnets | 2 AZs minimum |
| **DNS** | Route 53 | Custom domain with SSL |

### 3.4 Security

| Component | AWS Service | Purpose |
|-----------|-------------|---------|
| **Secrets** | AWS Secrets Manager | API keys, credentials |
| **SSL/TLS** | AWS Certificate Manager | HTTPS for custom domain |
| **IAM Roles** | ECS Task Roles | Minimal permission scope |

---

## 4. Implementation Plan

### Phase 1: Containerization

#### 4.1.1 Create Dockerfile for Streamlit Frontend

```dockerfile
# Dockerfile.frontend
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory (EFS mount point in production)
# In production: /shared/data is mounted from EFS
ENV DATA_DIR=/shared/data
RUN mkdir -p ${DATA_DIR}/faiss_index ${DATA_DIR}/content ${DATA_DIR}/audio

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_HEADLESS=true

# Expose Streamlit port
EXPOSE 8501

# Run Streamlit
CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0"]
```

#### 4.1.2 Create Dockerfile for Background Worker

```dockerfile
# Dockerfile.worker
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# EFS mount point
ENV DATA_DIR=/shared/data
RUN mkdir -p ${DATA_DIR}/faiss_index ${DATA_DIR}/content ${DATA_DIR}/audio

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main", "worker"]
```

#### 4.1.3 Create docker-compose.yml for local testing

```yaml
version: '3.8'

services:
  streamlit:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "8501:8501"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL}
      - OPENAI_MODEL_NAME=${OPENAI_MODEL_NAME}
      - AWS_REGION=us-east-1
      - REDIS_URL=redis://redis:6379
      - DATA_DIR=/shared/data  # EFS mount point in production
    volumes:
      - ./data:/shared/data    # Local volume simulating EFS mount
    depends_on:
      - redis

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL}
      - AWS_REGION=us-east-1
      - SQS_QUEUE_URL=${SQS_QUEUE_URL}
      - DATA_DIR=/shared/data
    volumes:
      - ./data:/shared/data
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

---

### Phase 2: AWS Infrastructure (Terraform)

#### 4.2.0 Reuse Existing AWS Foundation

You already have foundational infrastructure in `ap-south-1`:

- Existing ECS cluster: `np-pgrest`
- ECS cluster ARN: `arn:aws:ecs:ap-south-1:559387212220:cluster/np-pgrest`
- Existing ALB: `goodedlb`
- ALB ARN: `arn:aws:elasticloadbalancing:ap-south-1:559387212220:loadbalancer/app/goodedlb/9d02326a4f081eda`

Plan update: **reuse these instead of creating new cluster/ALB**.

- Create new ECS services inside `np-pgrest`.
- Create new target groups + listener rules on `goodedlb`.
- Keep all app-specific resources new (EFS, Redis, SQS, IAM roles, task definitions).
- Use Terraform `data` sources for existing resources to avoid drift.

ALB listener decision based on your listener dump:

- Port `8443` is already occupied by listener ARN `arn:aws:elasticloadbalancing:ap-south-1:559387212220:listener/app/goodedlb/9d02326a4f081eda/d00664a12035ae7f`.
- Certificate on `8443`: `arn:aws:acm:ap-south-1:559387212220:certificate/79433978-2cfe-439f-b6b4-b5dbe672f399`.
- For this app, create a **new HTTPS listener on a new port** (example: `7443`) and reuse the same certificate ARN from `8443`.

#### 4.2.1 Terraform Configuration Structure

```
deploy/
├── main.tf                 # Main configuration
├── variables.tf            # Input variables
├── outputs.tf             # Output values
├── ecs/
│   ├── cluster.tf         # ECS cluster definition
│   ├── services.tf       # Frontend & worker services
│   ├── tasks.tf           # Task definitions (with EFS volumes)
│   └── iam.tf             # ECS task roles
├── efs/
│   └── main.tf            # EFS filesystem for shared storage
├── s3/
│   └── bucket.tf          # S3 bucket for backups (optional)
├── elasticache/
│   └── redis.tf           # ElastiCache Redis
├── sqs/
│   └── queue.tf           # SQS for background jobs
├── alb/
│   └── main.tf            # Load balancer
└── secrets/
    └── main.tf            # Secrets Manager
```

#### 4.2.2 Key Terraform Resources

```hcl
# ecs/cluster.tf (reuse existing cluster)
data "aws_ecs_cluster" "shared" {
  cluster_name = "np-pgrest"
}

# alb/main.tf (reuse existing ALB)
data "aws_lb" "shared" {
  arn = "arn:aws:elasticloadbalancing:ap-south-1:559387212220:loadbalancer/app/goodedlb/9d02326a4f081eda"
}

# efs/main.tf - EFS Filesystem for FAISS Index
resource "aws_efs_file_system" "neet_shared" {
  creation_token = "neet-knowledge-${var.environment}"
  encrypted      = true
  kms_key_id     = aws_kms_key.efs.arn
  
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"  # Move to Infrequent Access
  }
}

resource "aws_efs_mount_target" "neet" {
  count = length(var.private_subnet_ids)
  
  file_system_id = aws_efs_file_system.neet_shared.id
  subnet_id      = var.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "faiss" {
  file_system_id = aws_efs_file_system.neet_shared.id
  
  root_directory {
    path = "/shared"
    creation_info {
      owner_uid   = "1000"
      owner_gid   = "1000"
      permissions = "755"
    }
  }
  
  posix_user {
    gid = 1000
    uid = 1000
  }
}

# S3 bucket for backups (optional)
resource "aws_s3_bucket" "backup_storage" {
  bucket = "neet-knowledge-backup-${var.environment}"
  
  lifecycle {
    rule {
      id      = "expire-old-versions"
      enabled = true
      expiration {
        days = 90
      }
    }
  }
}

# elasticache/redis.tf
resource "aws_elasticache_subnet_group" "neet" {
  name       = "neet-knowledge-subnet-${var.environment}"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "neet_redis" {
  replication_group_id = "neet-knowledge-${var.environment}"
  engine              = "redis"
  engine_version      = "7.0"
  node_type           = "cache.t3.micro"
  number_cache_clusters = 2
  
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token_enabled         = true
  
  subnet_group_name   = aws_elasticache_subnet_group.neet.name
  security_group_ids  = [aws_security_group.redis.id]
}

# ECS Task Definition with EFS Volume Mount
resource "aws_ecs_task_definition" "streamlit" {
  family                   = "neet-knowledge-streamlit"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"  # 1 vCPU
  memory                   = "2048"  # 2 GB
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn           = aws_iam_role.ecs_task.arn

  volume {
    name = "shared-data"
    
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.neet_shared.id
      root_directory     = "/"
      transit_encryption = "ENABLED"
      
      authorization_config {
        access_point_id = aws_efs_access_point.faiss.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "streamlit"
      image     = "${var.ecr_streamlit_image}"
      essential = true
      
      portMappings = [
        {
          containerPort = 8501
          protocol      = "tcp"
        }
      ]
      
      environment = [
        { name = "PYTHONUNBUFFERED", value = "1" },
        { name = "DATA_DIR", value = "/shared/data" }
      ]
      
      mountPoints = [
        {
          sourceVolume  = "shared-data"
          containerPath = "/shared/data"
          readOnly     = false
        }
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/neet-knowledge-streamlit"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

# ECS Service - Frontend
resource "aws_ecs_service" "streamlit" {
  name            = "neet-knowledge-streamlit-${var.environment}"
  cluster         = data.aws_ecs_cluster.shared.id
  task_definition = aws_ecs_task_definition.streamlit.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.streamlit.arn
    container_name  = "streamlit"
    container_port  = 8501
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

# Auto-scaling
resource "aws_appautoscaling_target" "streamlit" {
  max_capacity       = 10
  min_capacity       = 2
  resource_id        = "service/${data.aws_ecs_cluster.shared.cluster_name}/${aws_ecs_service.streamlit.name}"
  scalable_dimension = "ecs:service:DesiredCount"
}

resource "aws_appautoscaling_policy" "streamlit_cpu" {
  name               = "streamlit-cpu-scaling-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.streamlit.resource_id
  scalable_dimension = aws_appautoscaling_target.streamlit.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70
  }
}
```

---

### Phase 3: Application Modifications

#### 4.3.1 Environment Configuration

```python
# src/utils/config.py - Enhanced for AWS with EFS
import os
import boto3
from botocore.exceptions import ClientError

class Config:
    # AWS Configuration
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    
    # EFS Configuration (shared across all Fargate instances)
    # In production: /shared/data is mounted from EFS
    # In local dev: ./data directory
    DATA_DIR = os.getenv("DATA_DIR", "/shared/data")
    
    # Paths within EFS mount
    FAISS_INDEX_DIR = os.path.join(DATA_DIR, "faiss_index")
    CONTENT_DIR = os.path.join(DATA_DIR, "content")
    AUDIO_DIR = os.path.join(DATA_DIR, "audio")
    
    # Ensure directories exist
    @classmethod
    def ensure_dirs(cls):
        """Create necessary directories on EFS"""
        for dir_path in [cls.FAISS_INDEX_DIR, cls.CONTENT_DIR, cls.AUDIO_DIR]:
            os.makedirs(dir_path, exist_ok=True)
    
    # Redis Configuration
    REDIS_URL = os.getenv("REDIS_URL")
    REDIS_SESSION_TTL = 3600  # 1 hour
    
    # SQS Configuration
    SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
    
    # Vector DB Settings
    VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE", "faiss_efs")  # Uses EFS
    
    @staticmethod
    def get_secret(secret_name):
        """Retrieve secret from AWS Secrets Manager"""
        client = boto3.client("secretsmanager", region_name=Config.AWS_REGION)
        try:
            get_secret_value_response = client.get_secret_value(SecretId=secret_name)
            return get_secret_value_response["SecretString"]
        except ClientError as e:
            raise Exception(f"Failed to retrieve secret: {e}")
```

#### 4.3.2 EFS-backed FAISS Vector Store

```python
# src/rag/efs_vector_store.py
import faiss
import os
import numpy as np

class EFSFAISSVectorStore:
    """FAISS vector store with EFS persistence (shared across all instances)"""
    
    def __init__(self, index_dir: str, dimension: int = 384, index_name: str = "faiss.index"):
        """
        Args:
            index_dir: EFS mount path (e.g., /shared/data/faiss_index)
            dimension: Embedding dimension (384 for all-MiniLM-L6-v2)
            index_name: Name of the FAISS index file
        """
        self.index_dir = index_dir
        self.index_path = os.path.join(index_dir, index_name)
        self.dimension = dimension
        self.index = None
        self.metadata = []  # Track document metadata
        self.metadata_path = os.path.join(index_dir, "metadata.pkl")
        
        # Ensure index directory exists
        os.makedirs(index_dir, exist_ok=True)
        
        self._load_or_create()
    
    def _load_or_create(self):
        """Load existing index from EFS or create new one"""
        import pickle
        
        # Load FAISS index
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
        else:
            # Use IVF index for better performance on larger datasets
            # nlist = number of clusters (adjust based on data size)
            quantizer = faiss.IndexFlatL2(self.dimension)
            self.index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist=100)
            self.index.train(np.random.randn(1000, self.dimension).astype('float32'))
        
        # Load metadata
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path, 'rb') as f:
                self.metadata = pickle.load(f)
    
    def save(self):
        """Persist index to EFS"""
        import pickle
        
        faiss.write_index(self.index, self.index_path)
        
        with open(self.metadata_path, 'wb') as f:
            pickle.dump(self.metadata, f)
    
    def add_vectors(self, vectors, metadata: list = None):
        """
        Add vectors to index
        
        Args:
            vectors: numpy array of shape (n, dimension)
            metadata: list of metadata dicts for each vector
        """
        if isinstance(vectors, list):
            vectors = np.array(vectors).astype('float32')
        
        self.index.add(vectors)
        
        if metadata:
            self.metadata.extend(metadata)
        else:
            self.metadata.extend([{}] * len(vectors))
        
        self.save()  # Persist to EFS
    
    def search(self, query_vector, k: int = 5):
        """
        Search similar vectors
        
        Args:
            query_vector: numpy array of shape (dimension,) or (1, dimension)
            k: number of results to return
            
        Returns:
            distances: numpy array of distances
            indices: numpy array of indices
        """
        if query_vector.ndim == 1:
            query_vector = query_vector.reshape(1, -1)
        
        distances, indices = self.index.search(query_vector.astype('float32'), k)
        return distances, indices
    
    def get_metadata(self, indices: list) -> list:
        """Retrieve metadata for given indices"""
        return [self.metadata[i] if i < len(self.metadata) else {} for i in indices]
    
    def delete_index(self):
        """Delete the index files from EFS"""
        import os
        for path in [self.index_path, self.metadata_path]:
            if os.path.exists(path):
                os.remove(path)
```

#### Usage Example

```python
from src.rag.efs_vector_store import EFSFAISSVectorStore
from src.utils.config import Config

# Initialize (uses EFS path in production, local path in dev)
Config.ensure_dirs()
vector_store = EFSFAISSVectorStore(
    index_dir=Config.FAISS_INDEX_DIR,
    dimension=384  # all-MiniLM-L6-v2
)

# Add documents
vectors = embeddings  # numpy array
metadata = [{"source": "yt_video_1", "chunk": 0}, ...]
vector_store.add_vectors(vectors, metadata=metadata)

# Search
query_embedding = query_model.embed_query("What is cell division?")
distances, indices = vector_store.search(query_embedding, k=5)
results = vector_store.get_metadata(indices[0])
```

#### 4.3.3 Redis Session Management

```python
# src/utils/session_manager.py
import redis
import json
from datetime import timedelta

class SessionManager:
    """Redis-backed session management for Streamlit"""
    
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
    
    def get_chat_history(self, session_id: str) -> list:
        """Retrieve chat history for a session"""
        key = f"chat:{session_id}"
        data = self.redis.get(key)
        return json.loads(data) if data else []
    
    def save_chat_history(self, session_id: str, messages: list, ttl: int = 3600):
        """Save chat history with TTL"""
        key = f"chat:{session_id}"
        self.redis.setex(key, ttl, json.dumps(messages))
    
    def clear_session(self, session_id: str):
        """Clear session data"""
        self.redis.delete(f"chat:{session_id}")
```

#### 4.3.4 SQS Background Job Queue

```python
# src/jobs/queue.py
import boto3
import json

class IngestionQueue:
    """SQS-based background job queue"""
    
    def __init__(self, queue_url: str):
        self.sqs = boto3.client("sqs")
        self.queue_url = queue_url
    
    def submit_job(self, source_url: str, source_type: str, user_id: str = None):
        """Submit ingestion job"""
        message = {
            "source_url": source_url,
            "source_type": source_type,
            "user_id": user_id
        }
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(message)
        )
    
    def process_jobs(self):
        """Process pending jobs (worker function)"""
        while True:
            response = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=10
            )
            
            if "Messages" in response:
                for message in response["Messages"]:
                    job = json.loads(message["Body"])
                    self._process_job(job)
                    self.sqs.delete_message(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=message["ReceiptHandle"]
                    )
    
    def _process_job(self, job: dict):
        """Process a single ingestion job"""
        # Import and run ingestion logic
        from src.main import ingest_content
        ingest_content(job["source_url"], job["source_type"])
```

---

### Phase 4: CI/CD Pipeline

#### 4.4.1 GitHub Actions Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy to AWS ECS

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  AWS_REGION: us-east-1
  ECR_REGISTRY: ${{ secrets.AWS_ACCOUNT_ID }}.dkr.ecr.${{ env.AWS_REGION }}.amazonaws.com

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          
      - name: Run tests
        run: |
          python tests/test_rag.py

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
      
    steps:
      - uses: actions/checkout@v4
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      
      - name: Login to Amazon ECR
        run: |
          aws ecr get-login-password --region ${{ env.AWS_REGION }} | \
            docker login --username AWS --password-stdin ${{ env.ECR_REGISTRY }}
      
      - name: Build and push Streamlit image
        run: |
          docker build -f Dockerfile.frontend -t ${{ env.ECR_REGISTRY }}/neet-knowledge-streamlit:${{ github.sha }} .
          docker push ${{ env.ECR_REGISTRY }}/neet-knowledge-streamlit:${{ github.sha }}
      
      - name: Build and push Worker image
        run: |
          docker build -f Dockerfile.worker -t ${{ env.ECR_REGISTRY }}/neet-knowledge-worker:${{ github.sha }} .
          docker push ${{ env.ECR_REGISTRY }}/neet-knowledge-worker:${{ github.sha }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
      
    steps:
      - uses: actions/checkout@v4
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster np-pgrest \
            --service neet-knowledge-streamlit \
            --force-new-deployment \
            --region ${{ env.AWS_REGION }}
```

---

### Phase 5: DNS and SSL

```hcl
# alb/dns.tf
resource "aws_route53_zone" "main" {
  name = "neetprep.com"
}

# Reuse existing ALB (goodedlb)
data "aws_lb" "shared" {
  arn = "arn:aws:elasticloadbalancing:ap-south-1:559387212220:loadbalancer/app/goodedlb/9d02326a4f081eda"
}

# Port 8443 is already in use on this ALB.
# Lock this app to a dedicated new HTTPS listener on port 7443.

# Reuse the same ACM certificate currently used by port 8443
variable "shared_certificate_arn" {
  type    = string
  default = "arn:aws:acm:ap-south-1:559387212220:certificate/79433978-2cfe-439f-b6b4-b5dbe672f399"
}

# Create app-specific target group
resource "aws_lb_target_group" "streamlit" {
  name        = "neet-streamlit-${var.environment}"
  port        = 8501
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }
}

# Dedicated listener for this app on a new port
resource "aws_lb_listener" "neet_https" {
  load_balancer_arn = data.aws_lb.shared.arn
  port              = 7443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = var.shared_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.streamlit.arn
  }
}

resource "aws_acm_certificate" "main" {
  domain_name       = "pyq.neetprep.com"
  validation_method = "DNS"
  
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "main" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "pyq.neetprep.com"
  type    = "A"
  
  alias {
    name                   = data.aws_lb.shared.dns_name
    zone_id                = data.aws_lb.shared.zone_id
    evaluate_target_health = true
  }
}
```

---

## 5. Scalability Considerations

### 5.1 Horizontal Scaling

| Component | Scaling Strategy | Metrics |
|-----------|------------------|---------|
| Streamlit/FastAPI | ECS Service Auto Scaling | CPU > 70%, Request Count |
| Worker | ECS Service Auto Scaling | SQS Queue Depth |
| Redis | ElastiCache Redis Cluster | Memory, Connections |
| EFS | N/A (scales automatically) | N/A |
| S3 (Backup) | N/A (infinite) | N/A |

### 5.2 Performance Optimizations

1. **FAISS Index Optimization**
   - Use IVF (Inverted File) index for large datasets (already in EFS implementation)
   - Quantization (PQ) for memory efficiency
   - EFS performance mode: Set to `maxIO` for high throughput

2. **Caching Strategy**
   - Redis for session data (1-hour TTL)
   - EFS for persistent data (instant access, no download needed)
   - CloudFront CDN for static assets

3. **EFS Performance Tuning**
   ```hcl
   # efs/main.tf - High performance mode
   resource "aws_efs_file_system" "neet_shared" {
     # ... other settings ...
     
     throughput_mode = "bursting"  # or "provisioned" for guaranteed IOPS
     # For high traffic, use provisioned throughput:
     # provisioned_throughput_mibps = 100
   }
   ```

4. **LLM Rate Limiting**
   - Implement request queuing
   - Cache frequent queries
   - Use cheaper models for simple queries

### 5.3 Cost Optimization

| Resource | Configuration | Monthly Cost (Est.) |
|----------|---------------|---------------------|
| ECS Fargate (2-10 tasks) | 0.5-2 vCPU, 1-4 GB | $50-200 |
| ElastiCache Redis | t3.micro, 2 nodes | $30-50 |
| Amazon EFS | ~10 GB, Standard storage | $3-10 |
| ALB | Data processed | $15-30 |
| Data Transfer | Outbound to internet | $10-50 |
| Route 53 | 1 hosted zone | $0.50 |
| Secrets Manager | 2 secrets | $1.00 |
| CloudWatch Logs | 5 GB | $0.75/GB |
| S3 Backup (Optional) | ~10 GB | $2.50 |
| **Total** | | **$110-350/month** |

> **Note:** EFS costs ~$0.30/GB/month for standard storage. For typical NEET content (few GB), this is ~$3-10/month vs S3's ~$2.50. The benefit is instant index access without S3 download latency.

---

## 6. Deployment Checklist

### Pre-deployment
- [ ] AWS account with appropriate permissions
- [ ] Domain name registered
- [ ] SSL certificate (via ACM)
- [ ] API keys in Secrets Manager:
  - `OPENAI_API_KEY`
  - `YOUTUBE_API_KEY` (optional)

### Infrastructure
- [ ] Terraform apply complete
- [ ] Existing ECS cluster validated (`np-pgrest`)
- [ ] EFS filesystem created and mounted
- [ ] S3 bucket configured (for backups)
- [ ] ElastiCache Redis running
- [ ] New HTTPS listener created on `goodedlb` (recommended port `7443`) using cert `arn:aws:acm:ap-south-1:559387212220:certificate/79433978-2cfe-439f-b6b4-b5dbe672f399`
- [ ] Route53 DNS pointing to existing ALB

### Application
- [ ] Docker images pushed to ECR
- [ ] ECS task definitions created (with EFS volumes)
- [ ] ECS services deployed
- [ ] Auto-scaling policies attached

### Verification
- [ ] Health check endpoint working
- [ ] Streamlit UI accessible
- [ ] Chat functionality working
- [ ] Source ingestion working
- [ ] Redis session storage working
- [ ] EFS persistence working (FAISS index shared across instances)

---

## 7. Security Best Practices

1. **IAM Roles**: Use task roles with minimal permissions
2. **Secrets**: Never commit API keys; use Secrets Manager
3. **VPC**: Deploy in private subnets
4. **Security Groups**: Restrict inbound traffic to ALB only
5. **SSL/TLS**: Force HTTPS
6. **Input Validation**: Sanitize user inputs
7. **Rate Limiting**: Protect against abuse

---

## 8. Monitoring & Observability

### CloudWatch Dashboards

```hcl
# cloudwatch/dashboard.tf
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "neet-knowledge-${var.environment}"
  
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ServiceName", "neet-knowledge-streamlit"],
            [".", "MemoryUtilization", ".", "."]
          ]
          period = 300
          stat   = "Average"
          region = var.aws_region
          title  = "ECS Service Metrics"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/ElastiCache", "DatabaseMemoryUsagePercentage", "ReplicationGroupId", "neet-knowledge-${var.environment}"]
          ]
          period = 300
          stat   = "Maximum"
          region = var.aws_region
          title  = "Redis Memory Usage"
        }
      }
    ]
  })
}
```

### Alarms

```hcl
# cloudwatch/alarms.tf
resource "aws_cloudwatch_metric_alarm" "streamlit_cpu_high" {
  alarm_name          = "neet-knowledge-streamlit-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods = 2
  metric_name        = "CPUUtilization"
  namespace          = "AWS/ECS"
  period             = 300
  statistic          = "Average"
  threshold          = 80
  
  dimensions = {
    ServiceName = "neet-knowledge-streamlit-${var.environment}"
    ClusterName = "neet-knowledge-${var.environment}"
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}
```

---

## Phase 2: FastAPI + React Migration (Optional)

> **Trigger**: When Streamlit scaling limits are reached (>100 concurrent users, latency issues, or need for custom UX)

### When to Migrate

| Trigger Metric | Threshold | Action |
|----------------|-----------|--------|
| Concurrent users | > 100 | Evaluate migration |
| P99 latency | > 3 seconds | Profile, then migrate |
| User feedback | "UI needs improvement" | Plan migration |
| Feature needs | Real-time collab, custom flows | Migrate |

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            AWS Cloud                                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    Application Load Balancer                        │    │
│  │                  (Path-based routing)                               │    │
│  │                  /api/* → FastAPI    / → React (S3 + CloudFront)   │    │
│  └──────────────────────────────┬──────────────────────────────────────┘    │
│                                 │                                            │
│  ┌──────────────────────────────▼──────────────────────────────────────┐    │
│  │                    AWS ECS Fargate Cluster                          │    │
│  │                                                                    │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │    │
│  │  │  FastAPI    │  │  FastAPI    │  │  FastAPI    │  ...         │    │
│  │  │  Backend    │  │  Backend    │  │  Backend    │              │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘              │    │
│  │                                                                    │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │    │
│  │  │  Ingestion  │  │  Ingestion  │  │  Ingestion │              │    │
│  │  │   Worker    │  │   Worker    │  │   Worker    │              │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘              │    │
│  └──────────────────────────────┬──────────────────────────────────────┘    │
│                                 │                                            │
│         ┌──────────────────────┼──────────────────────┐                    │
│         ▼                      ▼                      ▼                    │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                 │
│  │  ElastiCache│     │     EFS     │     │     SQS     │                 │
│  │    Redis    │     │  (FAISS)    │     │   (Queue)   │                 │
│  └─────────────┘     └─────────────┘     └─────────────┘                 │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    Amazon CloudFront                                 │    │
│  │                  (React Static Files)                               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Steps

#### Phase 2.1: Create FastAPI Backend

```python
# api/main.py
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import redis
import os

from src.rag.neet_rag import NEETRAG
from src.utils.config import Config

app = FastAPI(title="NEET Knowledge API")

# CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://pyq.neetprep.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis for session management
redis_client = redis.from_url(Config.REDIS_URL)

# RAG system (singleton)
rag_system = None

def get_rag():
    global rag_system
    if rag_system is None:
        rag_system = NEETRAG(
            llm_provider="openai",
            llm_model=os.getenv("OPENAI_MODEL_NAME", "google/gemini-2.0-flash-001"),
            llm_base_url=os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        )
    return rag_system

# Request/Response Models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    sources: List[dict]
    session_id: str

class SourceAddRequest(BaseModel):
    url: str
    source_type: str  # "youtube" or "pdf"
    title: Optional[str] = None

# API Endpoints
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, rag = Depends(get_rag)):
    """Chat with the knowledge base"""
    session_id = request.session_id or "default"
    
    # Get chat history from Redis
    chat_key = f"chat:{session_id}"
    history = redis_client.get(chat_key)
    messages = eval(history) if history else []
    
    # Add user message
    messages.append({"role": "user", "content": request.message})
    
    # Get response from RAG
    response = rag.query(request.message)
    
    # Add assistant response
    messages.append({
        "role": "assistant", 
        "content": response.get("answer", "")
    })
    
    # Save to Redis (24 hour TTL)
    redis_client.setex(chat_key, 86400, str(messages))
    
    return ChatResponse(
        answer=response.get("answer", ""),
        sources=response.get("sources", []),
        session_id=session_id
    )

@app.post("/api/sources/add")
async def add_source(request: SourceAddRequest):
    """Add a new content source"""
    from src.utils.content_manager import ContentSourceManager
    from src.jobs.queue import IngestionQueue
    
    source_manager = ContentSourceManager()
    queue = IngestionQueue(Config.SQS_QUEUE_URL)
    
    if request.source_type == "youtube":
        source_id = source_manager.add_youtube(request.url, request.title)
    elif request.source_type == "pdf":
        source_id = source_manager.add_pdf(request.url, request.title)
    else:
        raise HTTPException(status_code=400, detail="Invalid source type")
    
    # Submit to queue for background processing
    queue.submit_job(request.url, request.source_type)
    
    return {"status": "success", "source_id": source_id}

@app.get("/api/sources")
async def list_sources():
    """List all content sources"""
    from src.utils.content_manager import ContentSourceManager
    source_manager = ContentSourceManager()
    sources = source_manager.get_all_sources()
    
    return {
        "sources": [
            {
                "id": s.id,
                "title": s.title,
                "url": s.url,
                "type": s.source_type,
                "status": s.status,
                "last_updated": s.last_updated
            }
            for s in sources
        ]
    }

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

# Streaming endpoint for real-time responses
@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream chat responses token-by-token"""
    from fastapi.responses import StreamingResponse
    
    async def generate():
        rag = get_rag()
        async for token in rag.astream_query(request.message):
            yield f"data: {token}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )
```

#### Phase 2.2: Create React Frontend

```tsx
// frontend/src/App.tsx
import React, { useState, useEffect } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { SourceList } from './components/SourceList';
import { Sidebar } from './components/Sidebar';
import './App.css';

function App() {
  const [sessionId] = useState(() => 
    localStorage.getItem('session_id') || 
    crypto.randomUUID()
  );
  
  useEffect(() => {
    localStorage.setItem('session_id', sessionId);
  }, [sessionId]);

  return (
    <div className="app-container">
      <Sidebar />
      <main className="main-content">
        <ChatPanel sessionId={sessionId} />
      </main>
    </div>
  );
}

export default App;
```

```tsx
// frontend/src/components/ChatPanel.tsx
import React, { useState, useRef } from 'react';
import { useChat } from '../hooks/useChat';

export function ChatPanel({ sessionId }: { sessionId: string }) {
  const [input, setInput] = useState('');
  const { messages, sendMessage, isLoading } = useChat(sessionId);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(scrollToBottom, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    
    await sendMessage(input);
    setInput('');
  };

  return (
    <div className="chat-panel">
      <div className="messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            <div className="message-content">{msg.content}</div>
            {msg.sources && (
              <div className="sources">
                {msg.sources.map((source: any, i: number) => (
                  <a key={i} href={source.timestamp_url || source.source} target="_blank">
                    {source.title || source.source}
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      
      <form onSubmit={handleSubmit} className="input-area">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about NEET 2025..."
          disabled={isLoading}
        />
        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Thinking...' : 'Send'}
        </button>
      </form>
    </div>
  );
}
```

```tsx
// frontend/src/hooks/useChat.ts
import { useState, useCallback } from 'react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  sources?: any[];
}

export function useChat(sessionId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = useCallback(async (content: string) => {
    setMessages(prev => [...prev, { role: 'user', content }]);
    setIsLoading(true);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: content, session_id: sessionId })
      });
      
      const data = await response.json();
      
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer,
        sources: data.sources
      }]);
    } catch (error) {
      console.error('Chat error:', error);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  return { messages, sendMessage, isLoading };
}
```

#### Phase 2.3: Update Terraform for FastAPI

```hcl
# ecs/task-definitions/fastapi.tf
resource "aws_ecs_task_definition" "fastapi" {
  family                   = "neet-knowledge-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn           = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "fastapi"
      image     = "${var.ecr_fastapi_image}"
      essential = true
      
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      
      environment = [
        { name = "PYTHONUNBUFFERED", value = "1" },
        { name = "DATA_DIR", value = "/shared/data" }
      ]
      
      mountPoints = [
        {
          sourceVolume  = "shared-data"
          containerPath = "/shared/data"
        }
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/neet-knowledge-api"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

# API Service
resource "aws_ecs_service" "fastapi" {
  name            = "neet-knowledge-api-${var.environment}"
  cluster         = data.aws_ecs_cluster.shared.id
  task_definition = aws_ecs_task_definition.fastapi.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name  = "fastapi"
    container_port  = 8000
  }
}

# ALB path routing
resource "aws_lb_listener_rule" "api_routing" {
  listener_arn = aws_lb_listener.neet_https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }
}
```

#### Phase 2.4: S3 + CloudFront for React

```hcl
# s3/cloudfront.tf
resource "aws_s3_bucket" "frontend" {
  bucket = "neet-knowledge-frontend-${var.environment}"
}

resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

resource "aws_cloudfront_distribution" "frontend" {
  origin {
    domain_name = aws_s3_bucket_frontend.website_endpoint
    origin_id   = "S3-frontend"
  }

  enabled             = true
  default_root_object = "index.html"

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    compress             = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  price_class = "PriceClass_100"  # India + Asia
}

# Route53 alias to CloudFront
resource "aws_route53_record" "frontend" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "pyq.neetprep.com"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}
```

#### Phase 2.5: CI/CD for React + FastAPI

```yaml
# .github/workflows/deploy-phase2.yml
name: Deploy FastAPI + React

on:
  push:
    branches: [main]
    paths:
      - 'api/**'
      - 'frontend/**'

jobs:
  test-api:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install and test API
        run: |
          cd api
          pip install -r requirements.txt
          pytest tests/

  build-and-push:
    needs: test-api
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # ... AWS credentials setup ...
      
      - name: Build FastAPI image
        run: |
          docker build -f api/Dockerfile -t ${{ env.ECR_REGISTRY }}/neet-knowledge-api:${{ github.sha }} ./api
          docker push ${{ env.ECR_REGISTRY }}/neet-knowledge-api:${{ github.sha }}
      
      - name: Build and deploy React
        run: |
          cd frontend
          npm install
          npm run build
          aws s3 sync build/ s3://neet-knowledge-frontend-${{ vars.ENVIRONMENT }}
          aws cloudfront create-invalidation --distribution-id ${{ vars.CF_DIST_ID }} --paths "/*"

  deploy-api:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      # ... AWS credentials ...
      
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster np-pgrest \
            --service neet-knowledge-api \
            --force-new-deployment
```

### Migration Checklist

- [ ] Create FastAPI backend with all Streamlit endpoints
- [ ] Move RAG logic to reusable backend module
- [ ] Create React frontend components
- [ ] Set up S3 + CloudFront for static hosting
- [ ] Update ALB for path-based routing
- [ ] Add WebSocket support for streaming (optional)
- [ ] Update CI/CD pipeline
- [ ] Run load tests
- [ ] Blue-green or canary deployment
- [ ] Monitor and rollback plan

### Cost Comparison: Phase 1 vs Phase 2

| Component | Streamlit | FastAPI + React | Change |
|-----------|-----------|-----------------|--------|
| ECS (Frontend) | 2-10 tasks | 2-10 tasks | Same |
| ECS (Backend) | — | 2-10 tasks | +$30-100 |
| CloudFront | — | ~$10/month | +$10 |
| S3 (Frontend) | — | $1/month | +$1 |
| **Total** | $110-350 | $140-460 | +$30-110 |

### Benefits of FastAPI + React

| Aspect | Improvement |
|--------|-------------|
| Latency | ~50-70% reduction (no full app rerun) |
| Concurrent users | 100 → 1000+ |
| UX flexibility | Full control over UI |
| Streaming | Native support |
| Mobile support | Same API for future apps |
| Developer experience | TypeScript + Python type safety |

---

## Final DNS Cutover Steps (`pyq.neetprep.com`)

1. Confirm ACM certificate in `ap-south-1` covers `pyq.neetprep.com` (or wildcard `*.neetprep.com`).
2. Create ECS service in cluster `np-pgrest` and verify target group health is green.
3. Create ALB HTTPS listener on `goodedlb` at **port `7443`** using cert `arn:aws:acm:ap-south-1:559387212220:certificate/79433978-2cfe-439f-b6b4-b5dbe672f399`.
4. Set listener default action to forward to `aws_lb_target_group.streamlit`.
5. Create/Update Route53 alias record `pyq.neetprep.com` in hosted zone `neetprep.com` pointing to `goodedlb`.
6. Validate before announcing:
   - `https://pyq.neetprep.com:7443/` loads
   - health checks pass
   - chat and ingestion workflows work end-to-end
7. Monitor post-cutover for 30-60 minutes (ALB 5xx, target health, ECS logs, app latency).
8. Rollback plan: point Route53 alias back to previous target and keep prior listener/target group unchanged until stable.

## Summary

This deployment plan transforms the local Streamlit application into a scalable, production-ready system on AWS ECS. Key architectural changes:

1. **Local FAISS → EFS-backed FAISS**: All Fargate instances share the same index in real-time
2. **Local files → EFS + Redis**: Shared storage for vectors/content, session state in Redis
3. **Single instance → Auto-scaling**: Handles demand spikes
4. **Background processing → SQS workers**: Async ingestion

### Why EFS Instead of S3?

| Factor | EFS | S3 |
|--------|-----|-----|
| **Startup time** | Instant (no download) | ~seconds per request |
| **Write consistency** | Real-time (NFS) | Requires upload after each write |
| **Complexity** | Simple (local path) | Need S3 sync logic |
| **Cost** | ~$3-10/month | ~$2.50/month |
| **Performance** | ~1-5ms latency | ~10-100ms latency |

The estimated cost is **$110-350/month** depending on usage, making it viable for educational platforms serving NEET students.
