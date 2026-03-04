# Embedding Model Comparison for NEET RAG

This document evaluates alternative embedding models to `paraphrase-multilingual-MiniLM-L12-v2` for future scaling or accuracy improvements.

## Current Model
**`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`**
- **Type**: Open Source (HuggingFace)
- **Max Tokens**: 128 (Very Short)
- **Dimensions**: 384
- **Size**: ~470MB
- **Multilingual**: Yes (50+ languages including Hindi)
- **Verdict**: Good for MVP and speed, but 128-token limit forces very small chunks (400 chars), risking context loss in complex physics/biology explanations.

---

## Recommended Alternatives

### 1. The Balanced Upgrade: `intfloat/multilingual-e5-base`
- **Type**: Open Source
- **Max Tokens**: **512** (4x current capacity)
- **Dimensions**: 768
- **Multilingual**: Yes (Strong performance)
- **Pros**: 
  - Significant upgrade in context window (allows ~1500-2000 char chunks).
  - Consistently ranks higher on MTEB (Massive Text Embedding Benchmark).
- **Cons**: 
  - Slower inference than MiniLM.
  - Requires larger vector storage (768 dim vs 384 dim).

### 2. The Heavy Hitter: `BAAI/bge-m3`
- **Type**: Open Source
- **Max Tokens**: **8192**
- **Dimensions**: 1024
- **Multilingual**: Excellent
- **Pros**: 
  - Massive context window (can embed entire pages or long transcripts).
  - Supports "Hybrid Search" (Dense + Sparse) out of the box.
  - State-of-the-art for multilingual retrieval.
- **Cons**: 
  - Heavy compute requirement (inference is slow on CPU).
  - Large storage footprint.

### 3. The Managed Option: `OpenAI text-embedding-3-small`
- **Type**: Paid API
- **Max Tokens**: **8191**
- **Dimensions**: 1536
- **Multilingual**: Excellent
- **Cost**: ~$0.02 / 1M tokens (Very cheap)
- **Pros**: 
  - Zero infrastructure management (no CPU/RAM load on Fargate).
  - Huge context window.
  - Consistent performance.
- **Cons**: 
  - Privacy/Data governance (data leaves AWS).
  - Latency depends on OpenAI API.

## Summary Recommendation

| Goal | Recommendation | Config Change Needed |
|------|----------------|----------------------|
| **Speed / MVP** | Keep **MiniLM-L12** | `chunk_size: 400` |
| **Accuracy Upgrade** | Switch to **Multilingual-E5-Base** | `chunk_size: 1500`, `dim: 768` |
| **Zero Ops / Scale** | Switch to **OpenAI** | `provider: openai`, `chunk_size: 3000` |

### Migration Strategy
If switching models later:
1. Update `config.yaml` with new model name.
2. Update `processing.chunk_size` to match new token limit.
3. **Important**: You must **re-ingest all content**. Old vectors (384d) will not match new vectors (768d/1536d) and FAISS will error out.
