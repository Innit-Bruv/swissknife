import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification

# Load both models
draft_model_name = "Qwen/Qwen2.5-0.5B-Instruct"
draft_tokenizer = AutoTokenizer.from_pretrained(draft_model_name)
draft_model = AutoModelForCausalLM.from_pretrained(draft_model_name, dtype=torch.float16, device_map="auto")
draft_model.eval()

auditor_name = "OpenAssistant/reward-model-deberta-v3-large-v2"
auditor_tokenizer = AutoTokenizer.from_pretrained(auditor_name)
auditor_model = AutoModelForSequenceClassification.from_pretrained(auditor_name, dtype=torch.float16, device_map="auto")
auditor_model.eval()

print("Both models loaded.")

# Auditor scoring function
def score_candidate(context_text, candidate_text):
    full_text = context_text + candidate_text
    inputs = auditor_tokenizer(full_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
    with torch.no_grad():
        output = auditor_model(**inputs)
    return output.logits[0].item()

# Full auditor-guided generation loop
def generate_with_auditor(prompt, max_new_tokens=50, K=4):
    input_ids = draft_tokenizer(prompt, return_tensors="pt").input_ids.to("cuda")
    generated_text = prompt

    for step in range(max_new_tokens):
        # Get top-K candidates from draft model
        with torch.no_grad():
            outputs = draft_model(input_ids)
            next_token_logits = outputs.logits[0, -1, :]
            probs = torch.softmax(next_token_logits, dim=-1)
            top_k_probs, top_k_ids = torch.topk(probs, K)

        # Score each candidate with auditor
        best_score = float('-inf')
        best_token_id = top_k_ids[0]

        for token_id in top_k_ids:
            candidate_text = draft_tokenizer.decode([token_id])
            score = score_candidate(generated_text, candidate_text)
            if score > best_score:
                best_score = score
                best_token_id = token_id

        # Append winning token
        next_token = best_token_id.unsqueeze(0).unsqueeze(0)
        input_ids = torch.cat([input_ids, next_token], dim=-1)
        generated_text += draft_tokenizer.decode([best_token_id])

        if best_token_id == draft_tokenizer.eos_token_id:
            break

    return generated_text

# Baseline: plain greedy
def generate_greedy(prompt, max_new_tokens=50):
    inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = draft_model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    return draft_tokenizer.decode(output[0], skip_special_tokens=True)

# Run both on same prompt and compare
prompt = "Tell me about the history of ancient Rome"

print("\n" + "=" * 50)
print("BASELINE (greedy decoding):")
print("=" * 50)
baseline = generate_greedy(prompt)
print(baseline)

print("\n" + "=" * 50)
print("SWISS KNIFE (helpfulness auditor):")
print("=" * 50)
swissknife = generate_with_auditor(prompt)
print(swissknife)

print("\nDone!")
