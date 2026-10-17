"""Verbatim PaperQA RCS templates (Apache-2.0).
Source: Future-House/paper-qa/src/paperqa/prompts.py
Revision: 57e89f7223b0960d5ee5ea048c69e3c47e088572
Copyright FutureHouse / PaperQA contributors; see third_party/paperqa.LICENSE.
Only these two constants are copied; provider and budget integration are OncoFusion code.
"""
summary_json_prompt = 'Excerpt from {citation}\n\n---\n\n{text}\n\n---\n\nQuestion: {question}'

summary_json_system_prompt = 'Provide a summary of the relevant information that could help answer the question based on the excerpt. Your summary, combined with many others, will be given to the model to generate an answer. Respond with the following JSON format:\n\n{{\n  "summary": "...",\n  "relevance_score": 0-10\n}}\n\nwhere `summary` is relevant information from the text - {summary_length}. `relevance_score` is an integer 0-10 for the relevance of `summary` to the question.\n\nThe excerpt may or may not contain relevant information. If not, leave `summary` empty, and make `relevance_score` be 0.'
