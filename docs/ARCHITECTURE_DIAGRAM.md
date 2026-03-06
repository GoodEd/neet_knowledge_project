# Scalable Architecture Diagram

## Current Architecture (Single Service - Not Scalable)

```
┌─────────────────┐
│  User Browsers  │
│  (1000 users)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│     Application Load Balancer       │
│  (No sticky sessions = ❌ broken)   │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      ECS Service (Streamlit)        │
│  ┌──────────┐ ┌──────────┐         │
│  │  Task 1  │ │  Task 2  │ ...     │
│  │ Query +  │ │ Query +  │         │
│  │ Ingest   │ │ Ingest   │         │  ❌ Write conflicts
│  └─────┬────┘ └─────┬────┘         │
└────────┼────────────┼───────────────┘
         │            │
         ▼            ▼
    ┌────────────────────────┐
    │  EFS: faiss_index/     │  ❌ Multiple writers = corruption
    └────────────────────────┘
```

**Problems:**
- ❌ WebSocket connections fail without sticky sessions
- ❌ Multiple tasks writing to FAISS index simultaneously
- ❌ Memory leaks cause OOM kills
- ❌ Cannot scale beyond 3-4 tasks safely

---

## Target Architecture (Split Services - Scales to 1000+)

```
┌──────────────────────────────────────────────────────────┐
│                     User Browsers                        │
│              (1000 concurrent connections)               │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│           Application Load Balancer (ALB)                  │
│   ✅ Sticky Sessions Enabled (AWSALB cookie)              │
│   ✅ Health Check: /_stcore/health                        │
│   ✅ WebSocket Upgrade Support (HTTP/1.1)                 │
└──────┬──────────────────────────────────┬──────────────────┘
       │                                  │
       │ Public Traffic                   │ Admin Only
       ▼                                  ▼
┌──────────────────────────┐    ┌───────────────────────┐
│  Query Service (ECS)     │    │ Ingest Service (ECS)  │
│  ┌────────────────────┐  │    │  ┌─────────────────┐  │
│  │ Task 1 (2vCPU/4GB) │  │    │  │ Admin Task (1x) │  │
│  │ - Streamlit UI     │  │    │  │ - Add content   │  │
│  │ - FAISS read-only  │  │    │  │ - Update index  │  │
│  │ - 40 sessions      │  │    │  │ - File locking  │  │
│  └────────────────────┘  │    │  └─────────────────┘  │
│  ┌────────────────────┐  │    │                       │
│  │ Task 2             │  │    │  ✅ Single writer     │
│  └────────────────────┘  │    │  ✅ Exclusive locks   │
│          ...             │    │  ✅ Atomic updates    │
│  ┌────────────────────┐  │    │                       │
│  │ Task 25-40         │  │    └───────────┬───────────┘
│  └────────────────────┘  │                │
│                          │                │ write
│  ✅ Auto-scaling 5-40    │                │ (with lock)
│  ✅ Read-only access     │                │
│  ✅ Reload every 5min    │                │
└──────────┬───────────────┘                │
           │ read                           │
           │ (concurrent safe)              │
           ▼                                ▼
    ┌─────────────────────────────────────────────┐
    │         EFS (Shared Storage)                │
    │  /data/                                     │
    │    ├── faiss_index/                         │
    │    │   ├── index.faiss       ← read by all │
    │    │   └── index.faiss.lock  ← write lock  │
    │    ├── audio/                (ingest only)  │
    │    ├── sources.json                         │
    │    └── documents/                           │
    └─────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│              CloudWatch Monitoring                     │
│  - CPU: 50-70% target                                  │
│  - Memory: Alert at 85%                                │
│  - Active connections: ~1000                           │
│  - Unhealthy targets: 0                                │
└────────────────────────────────────────────────────────┘
```

---

## Scaling Behavior Timeline

```
Time:    0 min      5 min       10 min      15 min      20 min
Users:   100        400         800         1000        600
         │          │           │           │           │
         ▼          ▼           ▼           ▼           ▼
Tasks:  ┌─┐       ┌─┐─┐─┐     ┌─┐─┐─┐─┐   ┌─┐─┐─┐─┐   ┌─┐─┐─┐
        │5│       │ 10  │     │  20   │   │  25   │   │ 15  │
        └─┘       └─────┘     └───────┘   └───────┘   └─────┘
         │          │           │           │           │
CPU:    25%        55%         68%         72%         50%
                    ↑           ↑                       ↓
                Scale-out    Scale-out             Scale-in
               (CPU > 60%)  (CPU > 60%)          (CPU < 60%)
                +2 tasks     +5 tasks              -10 tasks
                60s delay    60s delay            300s delay
```

**Auto-scaling logic:**
1. **Scale out** when CPU > 60% (add tasks within 60 seconds)
2. **Scale in** when CPU < 60% for 5 minutes (remove tasks slowly)
3. Never go below 5 tasks (min capacity)
4. Never go above 40 tasks (max capacity)

---

## Memory Usage per Task (4 GB total)

```
Task Memory Breakdown:
┌────────────────────────────────────┐  4096 MB
│                                    │
│  ┌──────────────────────────────┐  │  
│  │   FAISS Index (loaded)       │  │  1000 MB
│  └──────────────────────────────┘  │
│                                    │
│  ┌──────────────────────────────┐  │
│  │   Streamlit Base Process     │  │  100 MB
│  └──────────────────────────────┘  │
│                                    │
│  ┌──────────────────────────────┐  │
│  │   User Session 1             │  │  75 MB
│  ├──────────────────────────────┤  │
│  │   User Session 2             │  │  75 MB
│  ├──────────────────────────────┤  │
│  │   User Session 3             │  │  75 MB
│  ├──────────────────────────────┤  │
│  │   ...  (30-40 sessions)      │  │  
│  ├──────────────────────────────┤  │
│  │   User Session 40            │  │  75 MB
│  └──────────────────────────────┘  │  3000 MB
│                                    │
│  ┌──────────────────────────────┐  │
│  │   Headroom / Cache           │  │  996 MB
│  └──────────────────────────────┘  │
└────────────────────────────────────┘

Alert threshold: 3500 MB (85%)
OOM kill threshold: 4096 MB (100%)
```

**Why sessions vary:**
- Minimal session: 50 MB (just connected, no queries)
- Typical session: 75-100 MB (3-5 queries with history)
- Heavy session: 200-300 MB (20+ queries, large cached results)

---

## FAISS Index Update Flow

```
                   Admin User
                       │
                       │ 1. Upload PDF/Video
                       ▼
            ┌──────────────────────┐
            │  Ingest Service      │
            │  (ECS Task)          │
            └──────────┬───────────┘
                       │
                       │ 2. Acquire lock
                       ▼
            ┌──────────────────────┐
            │  index.faiss.lock    │ ← fcntl.LOCK_EX
            └──────────┬───────────┘
                       │
                       │ 3. Load index
                       ▼
            ┌──────────────────────┐
            │  faiss.read_index()  │
            └──────────┬───────────┘
                       │
                       │ 4. Add vectors
                       ▼
            ┌──────────────────────┐
            │  index.add(vectors)  │
            └──────────┬───────────┘
                       │
                       │ 5. Atomic write
                       ▼
            ┌──────────────────────┐
            │ index.faiss.tmp      │ ← Write new version
            │ os.rename() atomic   │
            └──────────┬───────────┘
                       │
                       │ 6. Release lock
                       ▼
            ┌──────────────────────┐
            │  index.faiss (new)   │
            └──────────┬───────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
  ┌─────────┐    ┌─────────┐    ┌─────────┐
  │ Query 1 │    │ Query 2 │    │ Query N │
  │         │    │         │    │         │
  │ Detect  │    │ Detect  │    │ Detect  │
  │ change  │    │ change  │    │ change  │
  │ (mtime) │    │ (mtime) │    │ (mtime) │
  │         │    │         │    │         │
  │ Reload  │    │ Reload  │    │ Reload  │
  │ in 5min │    │ in 5min │    │ in 5min │
  └─────────┘    └─────────┘    └─────────┘
  
  All query tasks reload independently
  (staggered by periodic check interval)
```

**Key points:**
- ✅ Only ONE writer at a time (exclusive lock)
- ✅ Readers don't block (no lock needed)
- ✅ Atomic rename prevents partial reads
- ✅ Each reader reloads independently (no coordination needed)

---

## Request Flow: User Query

```
1. User Query
   │
   │  GET /
   ▼
┌────────────────┐
│   ALB          │ → Check AWSALB cookie
│   (Port 443)   │ → Route to same task
└───────┬────────┘   (sticky session)
        │
        │ Forward to Task 15
        ▼
┌────────────────────────┐
│  ECS Task 15           │
│  (Container)           │
│                        │
│  Streamlit             │
│  ├─ Session ABC123     │ ← This user's session
│  ├─ Session DEF456     │
│  └─ Session GHI789     │
│                        │
│  2. Load from memory:  │
│     FAISS index        │
│                        │
│  3. Query vectors      │
│     index.search(...)  │
│                        │
│  4. Retrieve docs      │
│     top_k=5            │
│                        │
│  5. Call LLM           │
│     OpenRouter API     │
│                        │
│  6. Stream response    │
│     via WebSocket      │
└───────┬────────────────┘
        │
        │ WebSocket stream
        ▼
   User Browser

Total latency:
- FAISS search: 50-200ms
- LLM generation: 1-3 seconds
- Total: 1.5-3.5 seconds
```

---

## Failure Scenarios & Recovery

### Scenario 1: Task Crashes
```
Before:                      After (15 seconds):
┌────┐ ┌────┐ ┌────┐        ┌────┐ ┌────┐ ┌────┐
│ T1 │ │ T2 │ │ T3 │        │ T1 │ │ T3 │ │ T4 │
│ 40 │ │ 40 │ │ 40 │   →    │ 40 │ │ 40 │ │ 0  │
└────┘ └─XX─┘ └────┘        └────┘ └────┘ └────┘
       Crashed                      New task launched
       (OOM kill)                   (ECS replaces)

Users on T2:
- 40 connections dropped
- Reconnect automatically (Streamlit retry)
- Load balanced to T1, T3, T4
- Lost session state (must re-query)
```

### Scenario 2: Index Update During Query
```
Timeline:
0:00  Query task loads index (v1, 10000 vectors)
0:05  User query uses v1 index → Success
0:10  Ingest task updates index (v2, 10050 vectors)
0:12  User query STILL uses v1 index → Success (old data)
0:15  Query task checks mtime, detects change
0:15  Query task reloads index (v2, 10050 vectors)
0:16  User query uses v2 index → Success (new data)

Result: Zero downtime, eventual consistency (max 5 min lag)
```

### Scenario 3: EFS Throttling
```
Symptom:
- Read latency > 5 seconds
- faiss.read_index() timeout

Detection:
CloudWatch Metric: BurstCreditBalance → 0

Solution:
1. Increase EFS throughput mode (Bursting → Provisioned)
2. Or reduce index size (use PQ compression)
3. Or cache index in EFS Intelligent Tiering

Prevention:
- Monitor BurstCreditBalance
- Alert when < 1 million credits
- Pre-provision throughput for known traffic
```

---

## Monitoring Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│  NEET RAG Production Dashboard                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Active Users: 847 / 1000        Tasks: 22 / 40            │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░ 85%      ▓▓▓▓▓▓▓▓▓░░░░░░░ 55%      │
│                                                             │
├──────────────────────────┬──────────────────────────────────┤
│  CPU Utilization         │  Memory Utilization              │
│  ┌────────────────────┐  │  ┌────────────────────┐          │
│  │         68%        │  │  │         72%        │          │
│  │  ▄▄▄▄              │  │  │    ▄▄▄▄            │          │
│  │ ▀  ▀▀▀▄▄▄▄▄       │  │  │   ▀    ▀▀▀▄▄       │          │
│  │           ▀▀▀▄▄   │  │  │              ▀▀▄   │          │
│  │                ▀  │  │  │                 ▀  │          │
│  └────────────────────┘  │  └────────────────────┘          │
│  Target: 60% (OK)        │  Alert: 85% (OK)                │
├──────────────────────────┼──────────────────────────────────┤
│  Response Time (p95)     │  Healthy Targets                 │
│  ┌────────────────────┐  │  ┌────────────────────┐          │
│  │      1.2s          │  │  │  22 / 22           │          │
│  │   ▄                │  │  │  ████████████████  │          │
│  │  ▀ ▀▄▄▄            │  │  │  All healthy ✓     │          │
│  │       ▀▀▀▄         │  │  │                    │          │
│  │           ▀        │  │  │                    │          │
│  └────────────────────┘  │  └────────────────────┘          │
│  Target: < 2s (OK)       │  Min: 3 (OK)                    │
├──────────────────────────┴──────────────────────────────────┤
│  Recent Alerts (Last 24h)                                   │
│  ⚠️  18:45 - Memory warning Task 12 (88% usage)            │
│  ✅  18:50 - Memory recovered Task 12 (74% usage)          │
│  ⚠️  22:15 - High CPU (75%) - scaled to 25 tasks           │
└─────────────────────────────────────────────────────────────┘
```

Key metrics to track:
1. **Active Connections** - WebSocket count = concurrent users
2. **CPU per task** - Should be 50-70% on average
3. **Memory per task** - Alert at 85%, investigate at 90%
4. **Response time p95** - Should be < 2 seconds
5. **Healthy targets** - Should be ≥ min_capacity (5)
6. **EFS throughput** - Watch for throttling

---

This architecture provides:
- ✅ **Linear scaling** to 1000+ users
- ✅ **Fault tolerance** (task failures auto-recover)
- ✅ **Zero-downtime deployments** (rolling updates)
- ✅ **Cost efficiency** ($1.33/user/month)
- ✅ **Operational simplicity** (serverless, no instance management)
