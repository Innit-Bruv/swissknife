# SwissKnife — Project Plan & Implementation Roadmap
> Last updated: Week 2 (mid)
> Course: Information Retrieval, BITS Pilani Goa
> Lab: Pragya Lab (Prof. Amitava Das)

---

## What We Are Trying To Do

### The Problem
Standard LLM alignment is "checkpoint-bound" — safety, helpfulness, harmlessness etc. are baked into the model during training. If you want to change the alignment objective after deployment (e.g. make it stricter on safety, or more helpful), you have to retrain the whole model. That's expensive and slow.

### The Swiss Knife Idea
Swiss Knife externalizes alignment into a swappable **decode-time head**. Instead of baking alignment into training, it enforces alignment *during generation* using a separate small model called an **auditor**.

It does this by repurposing **speculative decoding**:
- A small fast **draft model** generates candidate tokens
- An **auditor model** scores those candidates according to an alignment objective
- The best candidate wins via a **Tournament Sampling Auditor (TSA)** — a bracket-style competition among candidates that prevents degenerate outputs like "refuse everything"

The auditor is a swappable "blade" — you can hot-swap between a Safety blade, Helpfulness blade, Harmlessness blade, or Informativeness blade without touching the base model at all.

### What This Project Contributes
A simplified but complete implementation of the Swiss Knife pipeline, evaluated on:
- **Switchability** — does swapping blades actually change outputs meaningfully?
- **Robustness** — does it refuse harmful prompts correctly? Does it over-refuse safe prompts?
- **Systems realism** — how much latency does the auditor add per token?

Compared against baselines:
- Greedy decoding (no auditor)
- Vanilla speculative decoding (draft + verifier, no alignment)

### Scope (Honest, Realistic)
We implement a simplified Swiss Knife with **2–3 auditor blades**, evaluate on a **fixed prompt set of 50–100 prompts**, and compare against the two baselines above. This is a credible course project contribution and a proof-of-concept for the full paper.

---

## The Lab's Research Arc (Context)
Understanding where Swiss Knife fits:

| Paper | Question Asked | Method |
|-------|---------------|--------|
| DPO-Kernels (ACL 2025) | How do we train alignment better? | Improved DPO with kernel methods |
| Alignment Faking (arXiv Nov 2025) | What if models pretend to be aligned during training? | Game-theoretic analysis |
| Swiss Knife (this paper) | What if we skip training-time alignment entirely? | Inference-time auditor heads |

---

## System Requirements

### Why You Need a Lab GPU
Swiss Knife runs **two models simultaneously** during inference:

| Component | Model Size | VRAM Needed |
|-----------|-----------|-------------|
| Draft model | 0.5B–1B params | ~2–4 GB |
| Auditor/Reward model | 125M–350M params | ~1–2 GB |
| Buffers + KV cache | — | ~1–2 GB |
| **Total** | | **~5–8 GB minimum** |

### Compute: APPCAIR Cloud Server
Access being provisioned through APPCAIR (appcair.bits-pilani.ac.in):
- **GPU**: NVIDIA H100 (2 cards) — more than enough for this project
- **Storage**: 20TB
- **Important deadline**: Contract ends April 17, 2026 — all experiments must be completed before then
- **Environment**: Can create own virtual environment and install all packages via pip
- **How to connect**: SSH (login instructions via APPCAIR Quick Manual)

No local setup needed. Everything runs on the APPCAIR server.

---

## Week-by-Week Plan

---

### Week 1 — Learn the Stack + Get Access
**Goal: Understand how LLM generation works. Get environment running.**

#### Learning Phase (Days 1–3) — Zero code, just consume
**Day 1**
- 3Blue1Brown: *"But what is a neural network?"* (20 mins)
- 3Blue1Brown: *"Gradient descent, how neural networks learn"* (20 mins)
- 3Blue1Brown: *"Attention in transformers, visually explained"* (30 mins)

**Day 2**
- Karpathy: *"Let's build GPT from scratch"* — youtube.com/watch?v=kCc8FmEb1nY (2 hours, 1.25x speed)
- HuggingFace blog: *"How to generate text: using different decoding methods"* — huggingface.co/blog/how-to-generate (25 mins)

**Day 3**
- HuggingFace NLP Course — Chapters 1 and 2 only — huggingface.co/learn/nlp-course/chapter1
- Speculative Decoding paper — arxiv.org/abs/2211.17192 (Abstract + Section 1 + Section 2 up to Figure 1 only)
- Re-read the Swiss Knife abstract with fresh eyes. Write 3 sentences in your own words describing what it does.

#### Coding Phase (Days 4–5) — On APPCAIR Server
No local setup. Everything on the APPCAIR server once access is confirmed.

**Day 4 — First Time SSH + Environment Setup**

SSH into the server (refer to APPCAIR Quick Manual for exact login command and credentials). Then:
```bash
# Create a virtual environment — do this once, keep it for the whole project
python3 -m venv swissknife-env
source swissknife-env/bin/activate

# Install everything needed for the project
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install transformers accelerate bitsandbytes sentencepiece protobuf
pip install trl datasets evaluate
pip install numpy pandas scipy matplotlib seaborn tqdm
pip install jupyterlab huggingface_hub pynvml einops
```

Verify GPU is visible and working:
```python
import torch
print(torch.cuda.is_available())        # must be True
print(torch.cuda.get_device_name(0))    # should print H100
print(torch.cuda.get_device_properties(0).total_memory / 1e9, "GB")  # ~80GB
```

Then load and run your first model — if this works, everything is set up correctly:
```python
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_name = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.float16,
    device_map="auto"
)
inputs = tokenizer("The capital of France is", return_tensors="pt").to("cuda")
output = model.generate(**inputs, max_new_tokens=10)
print(tokenizer.decode(output[0]))
```

**Day 5 — Manual Generation Loop**

This is the most important coding exercise before Week 2. Implement generation token-by-token manually and print top-5 candidates at each step:

```python
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_name = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16, device_map="auto")
model.eval()

prompt = "The Eiffel Tower is located in"
input_ids = tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")

with torch.no_grad():
    for step in range(10):
        outputs = model(input_ids)
        next_token_logits = outputs.logits[0, -1, :]
        probs = torch.softmax(next_token_logits, dim=-1)

        # Top-5 candidates — this is what the auditor will choose between
        top5_probs, top5_ids = torch.topk(probs, 5)
        print(f"Step {step+1} candidates:")
        for p, tid in zip(top5_probs, top5_ids):
            print(f"  '{tokenizer.decode([tid])}' — prob: {p:.4f}")

        # Greedy pick for now (auditor will replace this in Week 2)
        next_token = torch.argmax(probs).unsqueeze(0).unsqueeze(0)
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        print()
```

Stare at the output. At every step, you're seeing exactly what the auditor will score and choose between. This loop is the core of Swiss Knife.

#### Lab Access Status
- APPCAIR form submitted — access expected within 1–2 working days
- Email sent to Prof. Amitava Das
- Message sent to research scholar on the project

#### Week 1 "Done" Checklist
- [ ] Can explain what speculative decoding does in 2 sentences
- [ ] Can explain what the TSA auditor does in 2 sentences  
- [ ] Can load any HuggingFace model and generate text
- [ ] Can manually generate tokens one-by-one and see top-K candidates at each step
- [ ] Lab GPU access requested (ideally received)

---

### Week 2 — Build the Core Pipeline
**Goal: Get a working end-to-end Swiss Knife pipeline, even if slow and messy.**

> **Note**: Given the April 17 APPCAIR deadline, Week 2 is the most critical week. Start coding the moment access is confirmed.

#### Step 1 — Load the Draft Model and Reward Model Together

```python
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification
import torch

# Draft model — generates candidate tokens
draft_model_name = "Qwen/Qwen2.5-0.5B-Instruct"
draft_tokenizer = AutoTokenizer.from_pretrained(draft_model_name)
draft_model = AutoModelForCausalLM.from_pretrained(
    draft_model_name, torch_dtype=torch.float16, device_map="auto"
)

# Auditor — reward model that scores candidates
auditor_name = "OpenAssistant/reward-model-deberta-v3-large-v2"
auditor_tokenizer = AutoTokenizer.from_pretrained(auditor_name)
auditor_model = AutoModelForSequenceClassification.from_pretrained(
    auditor_name, torch_dtype=torch.float16, device_map="auto"
)

print("Both models loaded successfully")
```

#### Step 2 — Write the Auditor Scoring Function

Given a piece of text (context + candidate token), the auditor returns a score:

```python
def score_candidate(context_text, candidate_text, auditor_tokenizer, auditor_model):
    """Score how good candidate_text is as a continuation of context_text."""
    full_text = context_text + candidate_text
    inputs = auditor_tokenizer(full_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        outputs = auditor_model(**inputs)
    # Reward model outputs a single score — higher is better
    score = outputs.logits[0].item()
    return score
```

#### Step 3 — Build the Auditor-Guided Generation Loop

This is the core of Swiss Knife — flat scoring version (no tournament yet):

```python
def generate_with_auditor(prompt, draft_model, draft_tokenizer,
                           auditor_model, auditor_tokenizer,
                           max_new_tokens=50, K=4):
    """Generate text using draft model candidates scored by auditor."""

    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt

    for step in range(max_new_tokens):
        # Step 1: Get top-K candidate tokens from draft model
        with torch.no_grad():
            outputs = draft_model(input_ids)
            next_token_logits = outputs.logits[0, -1, :]
            probs = torch.softmax(next_token_logits, dim=-1)
            top_k_probs, top_k_ids = torch.topk(probs, K)

        # Step 2: Score each candidate with the auditor
        best_score = float('-inf')
        best_token_id = top_k_ids[0]

        for token_id in top_k_ids:
            candidate_text = draft_tokenizer.decode([token_id])
            score = score_candidate(generated_text, candidate_text,
                                    auditor_tokenizer, auditor_model)
            if score > best_score:
                best_score = score
                best_token_id = token_id

        # Step 3: Append winning token
        next_token = best_token_id.unsqueeze(0).unsqueeze(0)
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        generated_text += draft_tokenizer.decode([best_token_id])

        # Stop at EOS
        if best_token_id == draft_tokenizer.eos_token_id:
            break

    return generated_text

# Test it
result = generate_with_auditor(
    "Tell me about the history of Rome",
    draft_model, draft_tokenizer,
    auditor_model, auditor_tokenizer
)
print(result)
```

#### Step 4 — Run Baseline (Greedy) and Compare

```python
# Baseline: plain greedy decoding, no auditor
inputs = draft_tokenizer("Tell me about the history of Rome", return_tensors="pt").to("cuda")
baseline_output = draft_model.generate(**inputs, max_new_tokens=50, do_sample=False)
baseline_text = draft_tokenizer.decode(baseline_output[0], skip_special_tokens=True)

print("=== BASELINE (greedy) ===")
print(baseline_text)
print()
print("=== SWISS KNIFE (helpfulness auditor) ===")
print(result)
```

Look at the difference. If the outputs differ meaningfully, the pipeline is working.

#### Week 2 "Done" Checklist
- [x] Both models load on H100 without errors
- [x] Auditor scoring function works and returns a number
- [x] Full auditor-guided generation loop runs end-to-end
- [x] Baseline greedy output and Swiss Knife output visibly differ on at least one prompt
- [x] Code runs stably on 5+ different prompts without crashing
- [x] Two blades implemented and swappable (helpfulness + safety)
- [x] Llama-3.2-1B confirmed working as draft model
- [x] Outputs stable and non-degenerate across all prompts (after span-level fix)

---

### Week 3 — Add Tournament + Multiple Blades
**Goal: Implement TSA tournament logic. Make blades swappable.**

#### What Was Built
1. Knockout tournament implemented (K=4 → K=8)
2. All 5 blades matching the paper abstract exactly:
   - Blade 1: Helpfulness — `OpenAssistant/reward-model-deberta-v3-large-v2`
   - Blade 2: Harmlessness — `facebook/roberta-hate-speech-dynabench-r4-target`
   - Blade 3: Safety — `unitary/unbiased-toxic-roberta`
   - Blade 4: Informativeness — `cross-encoder/nli-deberta-v3-small`
   - Blade 5: Style — `s-nlp/roberta-base-formality-ranker`
3. Discovered token-level scoring causes degeneration for classifier-type models
4. Switched to **span-level scoring** (SPAN_LEN=5) — fixes degeneration across all blades
5. All 5 blades now producing coherent, meaningfully different outputs

#### Key Finding: Token-Level vs Span-Level
Token-level scoring works for conversational reward models (helpfulness, style) but causes degeneration for sentence classifiers (toxicity, NLI). Span-level scoring — generating 5-token spans as candidates instead of single tokens — fixes this by giving classifiers enough context to produce meaningful scores.

#### Week 3 "Done" Checklist
- [x] Tournament sampling implemented and tested (K=8)
- [x] All 5 blades working and swappable
- [x] Same prompt gives meaningfully different outputs under different blades
- [x] System runs stably without crashing on all test prompts
- [x] Span-level scoring implemented and confirmed working (SPAN_LEN=5)
- [x] Safety blade identifies harmful prompts and provides crisis resources
- [x] Stronger NLI model for informativeness (MoritzLaurer DeBERTa-v3-large)
- [x] Weighted combination for safety (0.7 safety + 0.3 draft prob)
- [x] max_new_tokens increased to 150
- [x] All blades producing clean, coherent, meaningfully different outputs
- [ ] Feedback from Prof. Das received
- [ ] Final evaluation prompt set designed (15-20 prompts)

---

### Week 4 — Evaluation + Results
**Goal: Produce actual numbers. Write up findings.**

#### Prompt Set
Build a fixed set of ~50–100 prompts across three categories:
- **Benign prompts** (e.g. "Explain how photosynthesis works") — test helpfulness/informativeness
- **Borderline prompts** (e.g. "How do I pick a lock?") — test safety vs helpfulness tradeoff
- **Clearly harmful prompts** (e.g. explicit harmful requests) — test refusal correctness

#### Metrics to Measure

| Dimension | Metric | How to Measure |
|-----------|--------|---------------|
| Switchability | Do outputs change across blades? | Run same prompts under each blade, compare outputs with a scoring model |
| Robustness | Refusal rate on harmful prompts | Count how often it refuses clearly harmful prompts |
| Robustness | Over-refusal rate on benign prompts | Count how often it wrongly refuses safe prompts |
| Systems realism | Latency per token (ms) | Python `time` module, average over 50 prompts |
| Systems realism | Auditor calls per token | Counter in generation loop |

#### Baselines to Compare Against
1. **Greedy decoding** — just `model.generate()` with no auditor
2. **Vanilla speculative decoding** — draft + verifier (no alignment auditor)
3. **Swiss Knife (each blade)** — your implementation

#### Week 4 "Done" Checklist
- [ ] All 3 baselines implemented and runnable
- [ ] Evaluation loop runs over full prompt set automatically
- [ ] Numbers recorded in a table (even a simple CSV is fine)
- [ ] Can describe what the results show in plain English

---

## Key Resources

| Resource | Link | When to Use |
|----------|------|-------------|
| Karpathy GPT video | youtube.com/watch?v=kCc8FmEb1nY | Week 1, Day 2 |
| 3Blue1Brown neural nets | youtube.com/3blue1brown | Week 1, Day 1 |
| HuggingFace NLP Course (Ch 1–2) | huggingface.co/learn/nlp-course | Week 1, Day 3 |
| HuggingFace generate blog | huggingface.co/blog/how-to-generate | Week 1, Day 2 |
| Speculative decoding paper | arxiv.org/abs/2211.17192 | Week 1, Day 3 |
| PyTorch docs | pytorch.org/tutorials | Reference throughout |
| HuggingFace transformers docs | huggingface.co/docs/transformers | Reference throughout |

---

## Models to Use

| Role | Model | Size | Where |
|------|-------|------|-------|
| Draft model | Qwen2.5-0.5B-Instruct | 0.5B | HuggingFace |
| Draft model (bigger) | Llama-3.2-1B-Instruct | 1B | HuggingFace |
| Helpfulness auditor | OpenAssistant/reward-model-deberta-v3-large-v2 | 350M | HuggingFace |
| Safety auditor | unitary/toxic-bert | 110M | HuggingFace |

---

## Server Setup
- **Instance name**: `bits-goa-students-sliced-Swissknife`
- **SSH command**: `ssh -i C:\Users\sheeb\.ssh\id_rsa -p 11421 root@inst-eu-2.cloudexe.tech`
- **GPU**: NVIDIA H100 MIG slice — 10.5GB VRAM
- **Virtual env**: `/root/swissknife-env` — activate with `source /root/swissknife-env/bin/activate`
- **Run jobs with**: `cloudexe --gpuspec EUNH100_0.14x1 -- /root/swissknife-env/bin/python /root/script.py`
- **HF token**: Set in `~/.bashrc` as `HF_TOKEN`
- **Torch version**: 2.6.0+cu124
- **Transformers version**: 5.5.1

---

## Scripts Written So Far

| Script | What it does | Status |
|--------|-------------|--------|
| `/root/test.py` | Verifies torch + GPU working | ✅ Done |
| `/root/verify.py` | Checks all packages installed | ✅ Done |
| `/root/week2_step1.py` | Loads both models, checks VRAM, sanity check | ✅ Done |
| `/root/week2_step2.py` | Full pipeline — helpfulness blade vs greedy baseline | ✅ Done |
| `/root/week2_step3.py` | Two blades (helpfulness + safety) vs greedy, Qwen 0.5B draft | ✅ Done |
| `/root/week2_step4.py` | Same as step3 but with Llama-3.2-1B draft model | ⏳ Waiting for Llama access |

---

## Models Confirmed Working

| Model | Role | Size | Status |
|-------|------|------|--------|
| Qwen/Qwen2.5-0.5B-Instruct | Draft model | 0.5B | ✅ Working |
| OpenAssistant/reward-model-deberta-v3-large-v2 | Helpfulness auditor (Blade 1) | 350M | ✅ Working |
| facebook/roberta-hate-speech-dynabench-r4-target | Safety auditor (Blade 2) | 125M | ✅ Working |
| meta-llama/Llama-3.2-1B-Instruct | Draft model (upgrade) | 1B | ⏳ Waiting for HF access approval |

---

## Key Findings So Far

- All 5 blades now fit comfortably in 10.5GB VRAM (using ~5.41GB at peak)
- Helpfulness blade consistently produces structured, assistant-like responses
- Safety blade on harmful prompts: identifies emotional abuse explicitly and provides crisis hotlines unprompted — strongest result of the project
- Span-level scoring (SPAN_LEN=5) fixed all degeneration issues from token-level scoring
- Informativeness blade has no safety signal — will answer harmful prompts literally (important finding for paper)
- Style blade produces clearly distinct formal register — best blade for demonstrating switchability
- All 5 blades produce coherent, meaningfully different outputs on all test prompts

---

## What We Are Waiting For
- Feedback from Prof. Das on blade choices, reward models, and evaluation approach

## What Happens Next (In Order)
1. Show Prof. Das current results — get feedback
2. Design final evaluation prompt set (15-20 prompts) based on his guidance
3. Build automated evaluation framework with metrics (Week 4)
4. Run full evaluation sweep over prompt set
5. Record all metrics into CSV and write up findings

---

## Current Status
- [x] Speculative decoding paper read
- [x] 3Blue1Brown videos watched
- [x] Karpathy video
- [x] HuggingFace NLP Course Ch 1–2
- [x] APPCAIR server access confirmed
- [x] Virtual environment set up at `/root/swissknife-env`
- [x] All packages installed (torch 2.6, transformers 5.5.1)
- [x] GPU verified — H100 MIG slice, 10.5GB VRAM
- [x] HuggingFace token configured
- [x] Llama-3.2-1B-Instruct access approved and working
- [x] Flat scoring pipeline working end to end
- [x] All 5 blades implemented matching paper abstract exactly
- [x] Knockout tournament implemented (K=8)
- [x] Span-level scoring implemented (SPAN_LEN=5)
- [x] Stronger NLI model for informativeness
- [x] Weighted combination for safety blade
- [x] max_new_tokens=150
- [x] All blades producing clean, coherent, meaningfully different outputs
- [x] Experiment results tracked in `swissknife_experiments.md`
- [x] **Week 3 implementation complete**
- [ ] Prof. Das feedback received
- [ ] Final evaluation prompt set designed (15-20 prompts)
- [ ] Automated evaluation framework built
- [ ] Full evaluation run completed
- [ ] Results recorded in CSV
- [ ] Writeup done

---
*This document is a living file — updated as the project progresses.*
