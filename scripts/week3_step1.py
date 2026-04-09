import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification

# ── Load draft model (Llama 1B) ───────────────────────────────────────────────
draft_model_name = "meta-llama/Llama-3.2-1B-Instruct"
draft_tokenizer = AutoTokenizer.from_pretrained(draft_model_name)
draft_model = AutoModelForCausalLM.from_pretrained(
    draft_model_name, dtype=torch.float16, device_map="auto"
)
draft_model.eval()

# ── Load helpfulness auditor (Blade 1) ───────────────────────────────────────
helpfulness_name = "OpenAssistant/reward-model-deberta-v3-large-v2"
helpfulness_tokenizer = AutoTokenizer.from_pretrained(helpfulness_name)
helpfulness_model = AutoModelForSequenceClassification.from_pretrained(
    helpfulness_name, dtype=torch.float16, device_map="auto"
)
helpfulness_model.eval()

# ── Load updated safety auditor (Blade 2) ────────────────────────────────────
safety_name = "unitary/unbiased-toxic-roberta"
safety_tokenizer = AutoTokenizer.from_pretrained(safety_name)
safety_model = AutoModelForSequenceClassification.from_pretrained(
    safety_name, device_map="auto"
)
safety_model.eval()

print(f"All models loaded. VRAM: {torch.cuda.memory_allocated() / 1e9:.2f} GB / {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

# ── Scoring functions ─────────────────────────────────────────────────────────
def score_helpfulness(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = helpfulness_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = helpfulness_model(**inputs)
    return output.logits[0].item()

def score_safety(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = safety_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = safety_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    return probs[0].item()

# ── FLAT SCORING generation ───────────────────────────────────────────────────
def generate_flat(prompt, score_fn, max_new_tokens=80, K=4):
    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt

    for step in range(max_new_tokens):
        with torch.no_grad():
            outputs = draft_model(input_ids)
            next_token_logits = outputs.logits[0, -1, :]
            probs = torch.softmax(next_token_logits, dim=-1)
            top_k_probs, top_k_ids = torch.topk(probs, K)

        best_score = float('-inf')
        best_token_id = top_k_ids[0]

        for token_id in top_k_ids:
            candidate_text = draft_tokenizer.decode([token_id])
            score = score_fn(generated_text, candidate_text)
            if score > best_score:
                best_score = score
                best_token_id = token_id

        next_token = best_token_id.unsqueeze(0).unsqueeze(0)
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        generated_text += draft_tokenizer.decode([best_token_id])

        if best_token_id == draft_tokenizer.eos_token_id:
            break

    return generated_text

# ── TOURNAMENT SAMPLING generation ───────────────────────────────────────────
def knockout_tournament(candidates, score_fn, context_text):
    """Run a knockout bracket among candidates. Returns winning token id."""
    remaining = list(candidates)

    while len(remaining) > 1:
        next_round = []
        for i in range(0, len(remaining) - 1, 2):
            text_a = draft_tokenizer.decode([remaining[i]])
            text_b = draft_tokenizer.decode([remaining[i + 1]])
            score_a = score_fn(context_text, text_a)
            score_b = score_fn(context_text, text_b)
            winner = remaining[i] if score_a >= score_b else remaining[i + 1]
            next_round.append(winner)
        if len(remaining) % 2 == 1:
            next_round.append(remaining[-1])
        remaining = next_round

    return remaining[0]

def generate_tournament(prompt, score_fn, max_new_tokens=80, K=4):
    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt

    for step in range(max_new_tokens):
        with torch.no_grad():
            outputs = draft_model(input_ids)
            next_token_logits = outputs.logits[0, -1, :]
            probs = torch.softmax(next_token_logits, dim=-1)
            top_k_probs, top_k_ids = torch.topk(probs, K)

        best_token_id = knockout_tournament(
            top_k_ids.tolist(), score_fn, generated_text
        )
        # Fix: explicitly put token on cuda
        best_token_id = torch.tensor(best_token_id, device="cuda")

        next_token = best_token_id.unsqueeze(0).unsqueeze(0)
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        generated_text += draft_tokenizer.decode([best_token_id])

        if best_token_id == draft_tokenizer.eos_token_id:
            break

    return generated_text

# ── Greedy baseline ───────────────────────────────────────────────────────────
def generate_greedy(prompt, max_new_tokens=80):
    inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False
        )
    return draft_tokenizer.decode(output[0], skip_special_tokens=True)

# ── Run all on test prompts ───────────────────────────────────────────────────
prompts = [
    "Tell me about the history of ancient Rome",
    "How do I deal with someone who makes me really angry",
    "What are some tips for staying productive while working from home",
]

for prompt in prompts:
    print("\n" + "=" * 60)
    print(f"PROMPT: {prompt}")
    print("=" * 60)

    print("\n[BASELINE - greedy]")
    print(generate_greedy(prompt))

    print("\n[FLAT SCORING - helpfulness blade]")
    print(generate_flat(prompt, score_helpfulness))

    print("\n[TOURNAMENT - helpfulness blade]")
    print(generate_tournament(prompt, score_helpfulness))

    print("\n[FLAT SCORING - safety blade]")
    print(generate_flat(prompt, score_safety))

    print("\n[TOURNAMENT - safety blade]")
    print(generate_tournament(prompt, score_safety))

print("\nDone!")
