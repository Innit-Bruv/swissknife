import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification

print("=" * 50)
print("STEP 1: Loading draft model...")
print("=" * 50)

draft_model_name = "Qwen/Qwen2.5-0.5B-Instruct"
draft_tokenizer = AutoTokenizer.from_pretrained(draft_model_name)
draft_model = AutoModelForCausalLM.from_pretrained(
    draft_model_name,
    dtype=torch.float16,
    device_map="auto"
)
draft_model.eval()
print(f"Draft model loaded: {draft_model_name}")
print(f"VRAM used so far: {torch.cuda.memory_allocated() / 1e9:.2f} GB")

print()
print("=" * 50)
print("STEP 2: Loading auditor (reward model)...")
print("=" * 50)

auditor_name = "OpenAssistant/reward-model-deberta-v3-large-v2"
auditor_tokenizer = AutoTokenizer.from_pretrained(auditor_name)
auditor_model = AutoModelForSequenceClassification.from_pretrained(
    auditor_name,
    dtype=torch.float16,
    device_map="auto"
)
auditor_model.eval()
print(f"Auditor loaded: {auditor_name}")
print(f"VRAM used so far: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
print(f"VRAM remaining: {(torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()) / 1e9:.2f} GB")

print()
print("=" * 50)
print("STEP 3: Quick sanity check...")
print("=" * 50)

prompt = "The capital of France is"
inputs = draft_tokenizer(prompt, return_tensors="pt").to("cuda")
with torch.no_grad():
    output = draft_model.generate(**inputs, max_new_tokens=10, do_sample=False)
print(f"Draft model output: {draft_tokenizer.decode(output[0], skip_special_tokens=True)}")

test_text = "The capital of France is Paris, a beautiful city."
auditor_inputs = auditor_tokenizer(test_text, return_tensors="pt", truncation=True, max_length=512).to("cuda")
with torch.no_grad():
    auditor_output = auditor_model(**auditor_inputs)
print(f"Auditor score for test text: {auditor_output.logits[0].item():.4f}")

print()
print("All good — both models loaded and working!")
