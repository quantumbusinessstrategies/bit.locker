from __future__ import annotations

from typing import Any


class FormWorker:
    def prepare(self, item: dict[str, Any]) -> dict[str, Any]:
        copy_text = str(item.get("copy_paste_form_answers") or "").strip()
        instructions = str(item.get("claim_instructions") or "").strip()
        exact_next = str(item.get("exact_next_step") or "").strip()
        if copy_text or instructions:
            return {
                "worked": True,
                "summary": "Prepared reusable form answers and claim instructions for the official flow.",
                "next_action": exact_next or "Use prepared answers in the official form after owner approval.",
                "completion": 70,
            }
        return {
            "worked": False,
            "summary": "No prepared form packet was available yet.",
            "next_action": exact_next or "Gather official form requirements and draft safe copy/paste answers.",
            "completion": 50,
        }

