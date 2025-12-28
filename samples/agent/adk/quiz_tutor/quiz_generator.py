# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import jsonschema
from google.adk.agents.llm_agent import LlmAgent
from google.adk.artifacts import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

logger = logging.getLogger(__name__)


QUIZ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "prompt": {"type": "string", "minLength": 1},
                    "options": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "value": {
                                    "type": "string",
                                    "enum": ["A", "B", "C", "D"],
                                },
                                "label": {"type": "string", "minLength": 1},
                            },
                            "required": ["value", "label"],
                        },
                    },
                    "correctValue": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "explanation": {"type": "string", "minLength": 1},
                },
                "required": ["id", "prompt", "options", "correctValue", "explanation"],
            },
        }
    },
    "required": ["questions"],
}


SYSTEM_INSTRUCTION = """
You are a quiz question generator.

Return ONLY valid JSON (no markdown, no code fences, no commentary).

Output JSON schema:
{
  "questions": [
    {
      "id": "q1",
      "prompt": "Question text...",
      "options": [
        {"value": "A", "label": "Option A text"},
        {"value": "B", "label": "Option B text"},
        {"value": "C", "label": "Option C text"},
        {"value": "D", "label": "Option D text"}
      ],
      "correctValue": "A",
      "explanation": "Short explanation..."
    }
  ]
}

Rules:
- Exactly 4 options per question (A/B/C/D).
- correctValue must match one of the option values.
- Keep prompts and explanations concise.
"""


@dataclass(frozen=True)
class GeneratedQuestion:
    id: str
    prompt: str
    options: list[dict[str, str]]
    correct_value: str
    explanation: str


class QuizGenerationError(Exception):
    pass


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise QuizGenerationError("LLM output did not contain a JSON object.")

    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as e:
        raise QuizGenerationError(f"Failed to parse JSON: {e}") from e


def _validate_questions(payload: dict[str, Any]) -> list[GeneratedQuestion]:
    try:
        jsonschema.validate(instance=payload, schema=QUIZ_SCHEMA)
    except jsonschema.exceptions.ValidationError as e:
        raise QuizGenerationError(f"Quiz JSON schema validation failed: {e}") from e

    questions: list[GeneratedQuestion] = []
    for q in payload["questions"]:
        # Ensure option labels include prefix (A. ...), to make the UI clearer.
        opts: list[dict[str, str]] = []
        for opt in q["options"]:
            value = opt["value"]
            label = opt["label"].strip()
            if not label.startswith(f"{value}."):
                label = f"{value}. {label}"
            opts.append({"value": value, "label": label})

        questions.append(
            GeneratedQuestion(
                id=q["id"],
                prompt=q["prompt"].strip(),
                options=opts,
                correct_value=q["correctValue"],
                explanation=q["explanation"].strip(),
            )
        )

    # Additional sanity: unique ids
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise QuizGenerationError("Question ids must be unique.")

    return questions


class QuizQuestionGenerator:
    def __init__(self):
        model = os.getenv("LITELLM_MODEL", "gemini/gemini-2.5-flash")
        self._agent = LlmAgent(
            model=LiteLlm(model=model),
            name="quiz_question_generator",
            description="Generates multiple-choice quiz questions as JSON.",
            instruction=SYSTEM_INSTRUCTION,
        )
        self._user_id = "quiz_question_generator"
        self._runner = Runner(
            app_name=self._agent.name,
            agent=self._agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )

    async def generate(
        self, *, topic: str, difficulty: int, count: int, session_id: str
    ) -> list[GeneratedQuestion]:
        topic = topic.strip()
        if not topic:
            raise QuizGenerationError("Topic is empty.")

        # Clamp
        difficulty = max(1, min(5, int(difficulty)))
        count = max(1, min(20, int(count)))

        prompt = (
            "Generate a multiple-choice quiz.\n"
            f"Topic: {topic}\n"
            f"Difficulty (1-5): {difficulty}\n"
            f"Number of questions: {count}\n"
            "Language: Japanese\n"
        )

        session = await self._runner.session_service.get_session(
            app_name=self._agent.name,
            user_id=self._user_id,
            session_id=session_id,
        )
        if session is None:
            session = await self._runner.session_service.create_session(
                app_name=self._agent.name,
                user_id=self._user_id,
                session_id=session_id,
                state={},
            )

        max_retries = 1
        attempt = 0
        last_error: str | None = None
        while attempt <= max_retries:
            attempt += 1
            logger.info(f"[quiz_generator] Generating questions attempt {attempt}")

            query_text = prompt
            if last_error:
                query_text = (
                    "Your previous output was invalid.\n"
                    f"Error: {last_error}\n"
                    "Return ONLY valid JSON that matches the required schema.\n\n"
                    + prompt
                )

            current_message = types.Content(
                role="user", parts=[types.Part.from_text(text=query_text)]
            )

            final_text: str | None = None
            async for event in self._runner.run_async(
                user_id=self._user_id,
                session_id=session.id,
                new_message=current_message,
            ):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        final_text = "\n".join(
                            [p.text for p in event.content.parts if p.text]
                        )
                    break

            if not final_text:
                last_error = "No final response text."
                continue

            try:
                payload = _extract_json_object(final_text)
                return _validate_questions(payload)[:count]
            except QuizGenerationError as e:
                last_error = str(e)
                continue

        raise QuizGenerationError(last_error or "Unknown generation error.")

