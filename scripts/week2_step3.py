import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification, pipeline

# ── Load draft model ──────────────────────────────────────────────────────────
draft_model_name = "Qwen/Qwen2.5-0.5B-Instruct"
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

# ── Load safety auditor (Blade 2) ────────────────────────────────────────────
safety_name = "facebook/roberta-hate-speech-dynabench-r4-target"
safety_tokenizer = AutoTokenizer.from_pretrained(safety_name)
safety_model = AutoModelForSequenceClassification.from_pretrained(
    safety_name, device_map="auto"
)
safety_model.eval()

print("All 3 models loaded.")
print(f"VRAM used: {torch.cuda.memory_allocated() / 1e9:.2f} GB / {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

# ── Scoring functions ─────────────────────────────────────────────────────────
def score_helpfulness(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = helpfulness_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = helpfulness_model(**inputs)
    return output.logits[0].item()  # higher = more helpful

def score_safety(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = safety_tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=512
    ).to("cuda")
    with torch.no_grad():
        output = safety_model(**inputs)
    probs = torch.softmax(output.logits[0], dim=-1)
    # index 0 = non-hate (safe), index 1 = hate (unsafe)
    # we want to MAXIMISE safety, so return probability of being non-hate
    return probs[0].item()

# ── Core generation function (blade is a scoring function) ───────────────────
def generate_with_blade(prompt, score_fn, blade_name, max_new_tokens=50, K=4):
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

# ── Greedy baseline ───────────────────────────────────────────────────────────
def generate_greedy(prompt, max_new_tokens=50):
    inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    return draft_tokenizer.decode(output[0], skip_special_tokens=True)

# ── Run all three on two prompts ──────────────────────────────────────────────
prompts = [
    "Tell me about the history of ancient Rome",
    "How do I deal with someone who makes me really angry",
]

for prompt in prompts:
    print("\n" + "=" * 60)
    print(f"PROMPT: {prompt}")
    print("=" * 60)

    print("\n[BASELINE - greedy]")
    print(generate_greedy(prompt))

    print("\n[BLADE 1 - helpfulness]")
    print(generate_with_blade(prompt, score_helpfulness, "helpfulness"))

    print("\n[BLADE 2 - safety]")
    print(generate_with_blade(prompt, score_safety, "safety"))

print("\nDone!")
