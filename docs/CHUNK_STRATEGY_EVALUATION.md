# Evaluation: Chunk Size & Overlap for NEET Content

## Context
- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2`
- **Model Limit**: 256 tokens (max input sequence length)
- **Current Settings**: `chunk_size = 1000`, `chunk_overlap = 200` (characters)

## Analysis

### 1. Token Limit Mismatch
- **1000 characters** corresponds to roughly **250-400 tokens** (English text varies, ~4 chars/token is a heuristic, but scientific terms can be token-heavy).
- **Risk**: The current `chunk_size` of 1000 likely exceeds the 256-token limit of the `all-MiniLM-L6-v2` model.
- **Consequence**: The embedding model **truncates** the input. The last ~30-40% of a 1000-char chunk might be completely ignored during vector generation. The retrieval system won't "see" that content.

### 2. Subject-Specific Considerations (NEET)

| Subject | Content Nature | Optimal Strategy |
|---------|----------------|------------------|
| **Physics** | Formulas, problem statements, logical derivations. | **Smaller Chunks**: Need precise retrieval of specific formulas or laws. Splitting a problem statement is bad, but 1000 chars is usually too long for a single concept. |
| **Chemistry** | Reactions, properties, exceptions. | **Smaller Chunks**: "Trends in periodic table" or "Reaction of Phenol" are distinct facts. High precision is preferred over broad context. |
| **Biology** | Descriptive processes (Digestion, Reproduction). | **Medium Chunks**: Processes need context. Cutting "Krebs cycle" in half hurts. However, specific fact retrieval ("dimensions of RBC") needs precision. |

## Recommendations

### 1. Reduce Chunk Size to ~500-600 Characters
- **Why**: 600 chars ≈ 150-180 tokens. This fits comfortably within the 256-token limit of `all-MiniLM-L6-v2`.
- **Benefit**: 
    - **No Truncation**: Every word in the chunk contributes to the vector.
    - **Higher Precision**: Search results will be more chemically/physically accurate.
    - **Less Noise**: LLM receives focused context, reducing hallucination risk.

### 2. Maintain or Slightly Increase Overlap Ratio
- **Current**: 20% (200/1000)
- **Proposed**: **150 characters** (approx 25-30% of new size).
- **Why**: Since chunks are smaller, the risk of splitting a sentence or critical clause increases. A healthy overlap ensures semantic continuity.

### 3. Proposed Config Change
```yaml
processing:
  chunk_size: 600    # Reduced from 1000 to fit embedding model limits
  chunk_overlap: 150 # Adjusted for smaller chunks
```

## Conclusion
The current 1000-char setting is **suboptimal** for the specific embedding model in use. It likely causes silent data loss (truncation) during indexing. Reducing to **600** is strongly recommended for technical/scientific content to ensure high-fidelity retrieval.
