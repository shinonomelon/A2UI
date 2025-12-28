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

import logging
from dataclasses import dataclass, field
from typing import Any

from quiz_generator import GeneratedQuestion, QuizGenerationError, QuizQuestionGenerator

logger = logging.getLogger(__name__)

SURFACE_ID = "default"


@dataclass
class QuizResult:
    question_id: str
    prompt: str
    selected: str
    correct: str
    explanation: str
    is_correct: bool


@dataclass
class QuizSession:
    topic: str = ""
    difficulty: int = 3
    count: int = 5
    questions: list[GeneratedQuestion] = field(default_factory=list)
    index: int = 0
    score: int = 0
    results: list[QuizResult] = field(default_factory=list)
    phase: str = "setup"  # setup | question | feedback | result


def _to_int(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            v = value.strip()
            if v == "":
                return default
            return int(float(v))
    except Exception:
        return default
    return default


def _first_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return ""


def _text_component(component_id: str, text: str, usage_hint: str | None = None) -> dict:
    payload: dict[str, Any] = {"text": {"literalString": text}}
    if usage_hint:
        payload["usageHint"] = usage_hint
    return {"id": component_id, "component": {"Text": payload}}


def _button_component(
    component_id: str,
    text_id: str,
    label: str,
    action_name: str,
    *,
    primary: bool = False,
    context: list[dict[str, Any]] | None = None,
) -> list[dict]:
    components = [
        {"id": text_id, "component": {"Text": {"text": {"literalString": label}}}},
        {
            "id": component_id,
            "component": {
                "Button": {
                    "child": text_id,
                    "primary": primary,
                    "action": (
                        {"name": action_name, "context": context}
                        if context
                        else {"name": action_name}
                    ),
                }
            },
        },
    ]
    return components


class QuizTutorAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self, *, use_ui: bool):
        self._use_ui = use_ui
        self._generator = QuizQuestionGenerator()
        self._sessions: dict[str, QuizSession] = {}

    def _get_session(self, session_id: str) -> QuizSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = QuizSession()
        return self._sessions[session_id]

    async def handle_text(self, query: str, session_id: str) -> tuple[str, list[dict]]:
        # Text entry is used only to open the setup UI (prefilling topic).
        topic = (query or "").strip()
        session = self._get_session(session_id)
        if topic:
            session.topic = topic
        session.phase = "setup"
        return "クイズの設定を選んでください。", self._render_setup(session)

    async def handle_ui_action(
        self, action_name: str, ctx: dict[str, Any], session_id: str
    ) -> tuple[str, list[dict]]:
        session = self._get_session(session_id)

        if action_name == "restart_quiz":
            # Keep last topic if present.
            session.questions = []
            session.index = 0
            session.score = 0
            session.results = []
            session.phase = "setup"
            return "最初からやり直します。", self._render_setup(session)

        if action_name == "start_quiz":
            logger.info(f"start_quiz ctx: {ctx}")
            logger.info(f"start_quiz session.topic: {session.topic}")
            topic = (ctx.get("quiz_topic") or session.topic or "").strip()
            difficulty = _to_int(ctx.get("quiz_difficulty"), session.difficulty)
            count = _to_int(ctx.get("quiz_count"), session.count)
            logger.info(f"start_quiz resolved topic: {topic}, difficulty: {difficulty}, count: {count}")

            difficulty = max(1, min(5, difficulty))
            count = max(3, min(10, count))

            if not topic:
                session.topic = ""
                session.phase = "setup"
                return "トピックを入力してください。", self._render_setup(session)

            session.topic = topic
            session.difficulty = difficulty
            session.count = count
            session.index = 0
            session.score = 0
            session.results = []
            session.phase = "question"

            try:
                session.questions = await self._generator.generate(
                    topic=topic,
                    difficulty=difficulty,
                    count=count,
                    session_id=session_id,
                )
            except QuizGenerationError as e:
                session.phase = "setup"
                return f"クイズ生成に失敗しました: {e}", self._render_setup(session)

            return "クイズを開始します。", self._render_question(session)

        if action_name == "submit_answer":
            if not session.questions:
                session.phase = "setup"
                return "まずクイズを開始してください。", self._render_setup(session)

            selected = _first_string(ctx.get("selected"))
            if not selected:
                return "選択肢を選んでから回答してください。", self._render_question(session)

            q = session.questions[session.index]
            is_correct = selected == q.correct_value
            if is_correct:
                session.score += 1

            session.results.append(
                QuizResult(
                    question_id=q.id,
                    prompt=q.prompt,
                    selected=selected,
                    correct=q.correct_value,
                    explanation=q.explanation,
                    is_correct=is_correct,
                )
            )
            session.phase = "feedback"
            return ("正解です。" if is_correct else "不正解です。"), self._render_feedback(
                session, is_correct=is_correct, selected=selected
            )

        if action_name == "next_question":
            if not session.questions:
                session.phase = "setup"
                return "まずクイズを開始してください。", self._render_setup(session)

            # If we're already at the end, just show results.
            if session.index >= len(session.questions) - 1:
                session.phase = "result"
                return "結果です。", self._render_result(session)

            session.index += 1
            session.phase = "question"
            return "次の問題です。", self._render_question(session)

        # Unknown action
        return f"未対応の操作です: {action_name}", self._render_setup(session)

    def _render_setup(self, session: QuizSession) -> list[dict]:
        # UI: topic + difficulty + count
        components: list[dict] = [
            {"id": "root", "component": {"Column": {"children": {"explicitList": [
                "title",
                "topic",
                "difficulty-label",
                "difficulty-slider",
                "count-label",
                "count-slider",
                "start-button",
                "restart-button",
            ]}}}},
            _text_component("title", "クイズ生成", "h1"),
            {
                "id": "topic",
                "component": {
                    "TextField": {
                        "label": {"literalString": "トピック"},
                        "text": {"path": "/quiz/topic"},
                        "textFieldType": "shortText",
                    }
                },
            },
            _text_component("difficulty-label", "難易度 (1-5)", "h5"),
            {
                "id": "difficulty-slider",
                "component": {
                    "Slider": {
                        "minValue": 1,
                        "maxValue": 5,
                        "value": {"path": "/quiz/difficulty"},
                    }
                },
            },
            _text_component("count-label", "問題数 (3-10)", "h5"),
            {
                "id": "count-slider",
                "component": {
                    "Slider": {
                        "minValue": 3,
                        "maxValue": 10,
                        "value": {"path": "/quiz/count"},
                    }
                },
            },
        ]

        components += _button_component(
            "start-button",
            "start-button-text",
            "開始",
            "start_quiz",
            primary=True,
            context=[
                {"key": "quiz_topic", "value": {"path": "/quiz/topic"}},
                {"key": "quiz_difficulty", "value": {"path": "/quiz/difficulty"}},
                {"key": "quiz_count", "value": {"path": "/quiz/count"}},
            ],
        )
        components += _button_component(
            "restart-button",
            "restart-button-text",
            "リセット",
            "restart_quiz",
            primary=False,
        )

        data_model_contents = [
            {
                "key": "quiz",
                "valueMap": [
                    {"key": "topic", "valueString": session.topic or ""},
                    {"key": "difficulty", "valueNumber": session.difficulty},
                    {"key": "count", "valueNumber": session.count},
                ],
            }
        ]

        return [
            {
                "beginRendering": {
                    "surfaceId": SURFACE_ID,
                    "root": "root",
                    "styles": {"primaryColor": "#4F46E5", "font": "Roboto"},
                }
            },
            {"surfaceUpdate": {"surfaceId": SURFACE_ID, "components": components}},
            {
                "dataModelUpdate": {
                    "surfaceId": SURFACE_ID,
                    "path": "/",
                    "contents": data_model_contents,
                }
            },
        ]

    def _render_question(self, session: QuizSession) -> list[dict]:
        q = session.questions[session.index]
        progress = f"Q{session.index + 1}/{len(session.questions)}"
        # Initialize with first option as default selection
        default_selection = q.options[0]["value"] if q.options else ""

        components: list[dict] = [
            {"id": "root", "component": {"Column": {"children": {"explicitList": [
                "title",
                "progress",
                "question",
                "choices",
                "submit-button",
                "restart-button",
            ]}}}},
            _text_component("title", "クイズ", "h1"),
            _text_component("progress", progress, "caption"),
            _text_component("question", q.prompt, "h3"),
            {
                "id": "choices",
                "component": {
                    "MultipleChoice": {
                        "selections": {"path": "/quiz/currentSelections"},
                        "options": [
                            {
                                "label": {"literalString": opt["label"]},
                                "value": opt["value"],
                            }
                            for opt in q.options
                        ],
                        "maxAllowedSelections": 1,
                    }
                },
            },
        ]

        components += _button_component(
            "submit-button",
            "submit-button-text",
            "回答",
            "submit_answer",
            primary=True,
            context=[
                {"key": "questionIndex", "value": {"path": "/quiz/currentQuestionIndex"}},
                {"key": "selected", "value": {"path": "/quiz/currentSelections"}},
            ],
        )
        components += _button_component(
            "restart-button",
            "restart-button-text",
            "最初から",
            "restart_quiz",
            primary=False,
        )

        # Initialize currentSelections with first option so HTML select default matches data model
        import json
        default_selections_json = json.dumps([default_selection]) if default_selection else "[]"

        data_model_contents = [
            {
                "key": "quiz",
                "valueMap": [
                    {"key": "topic", "valueString": session.topic},
                    {"key": "difficulty", "valueNumber": session.difficulty},
                    {"key": "count", "valueNumber": session.count},
                    {"key": "currentQuestionIndex", "valueNumber": session.index},
                    {"key": "currentSelections", "valueString": default_selections_json},
                ],
            }
        ]

        return [
            {"beginRendering": {"surfaceId": SURFACE_ID, "root": "root"}},
            {"surfaceUpdate": {"surfaceId": SURFACE_ID, "components": components}},
            {
                "dataModelUpdate": {
                    "surfaceId": SURFACE_ID,
                    "path": "/",
                    "contents": data_model_contents,
                }
            },
        ]

    def _render_feedback(
        self, session: QuizSession, *, is_correct: bool, selected: str
    ) -> list[dict]:
        q = session.questions[session.index]
        result_title = "正解" if is_correct else "不正解"
        progress = f"Q{session.index + 1}/{len(session.questions)}"

        components: list[dict] = [
            {"id": "root", "component": {"Column": {"children": {"explicitList": [
                "title",
                "progress",
                "result",
                "correct",
                "explanation",
                "next-button",
                "restart-button",
            ]}}}},
            _text_component("title", "解答", "h1"),
            _text_component("progress", progress, "caption"),
            _text_component("result", f"{result_title}（あなたの回答: {selected}）", "h3"),
            _text_component("correct", f"正解: {q.correct_value}", "body"),
            _text_component("explanation", f"解説: {q.explanation}", "body"),
        ]

        # Next: if last question, show result
        next_label = "結果へ" if session.index >= len(session.questions) - 1 else "次へ"
        components += _button_component(
            "next-button",
            "next-button-text",
            next_label,
            "next_question",
            primary=True,
        )
        components += _button_component(
            "restart-button",
            "restart-button-text",
            "最初から",
            "restart_quiz",
            primary=False,
        )

        data_model_contents = [
            {
                "key": "quiz",
                "valueMap": [
                    {"key": "topic", "valueString": session.topic},
                    {"key": "currentQuestionIndex", "valueNumber": session.index},
                    {"key": "score", "valueNumber": session.score},
                ],
            }
        ]

        return [
            {"beginRendering": {"surfaceId": SURFACE_ID, "root": "root"}},
            {"surfaceUpdate": {"surfaceId": SURFACE_ID, "components": components}},
            {
                "dataModelUpdate": {
                    "surfaceId": SURFACE_ID,
                    "path": "/",
                    "contents": data_model_contents,
                }
            },
        ]

    def _render_result(self, session: QuizSession) -> list[dict]:
        total = len(session.questions)
        score = session.score

        components: list[dict] = [
            {"id": "root", "component": {"Column": {"children": {"explicitList": [
                "title",
                "score",
                "result-list",
                "restart-button",
            ]}}}},
            _text_component("title", "結果", "h1"),
            _text_component("score", f"スコア: {score}/{total}", "h2"),
            {
                "id": "result-list",
                "component": {
                    "List": {
                        "direction": "vertical",
                        "children": {
                            "template": {
                                "componentId": "result-card",
                                "dataBinding": "/results",
                            }
                        },
                    }
                },
            },
            {"id": "result-card", "component": {"Card": {"child": "result-card-body"}}},
            {
                "id": "result-card-body",
                "component": {
                    "Column": {
                        "children": {
                            "explicitList": [
                                "result-status",
                                "result-question",
                                "result-answers",
                            ]
                        }
                    }
                },
            },
            _text_component("result-status", "状態: ", "h4"),
            _text_component("result-question", "問題: ", "body"),
            _text_component("result-answers", "回答: ", "body"),
        ]

        components += _button_component(
            "restart-button",
            "restart-button-text",
            "もう一度",
            "restart_quiz",
            primary=True,
        )

        # Build results map for template binding. We store strings only (Text expects string).
        results_value_map: list[dict[str, Any]] = []
        for i, r in enumerate(session.results):
            results_value_map.append(
                {
                    "key": str(i),
                    "valueMap": [
                        {
                            "key": "status",
                            "valueString": "正解" if r.is_correct else "不正解",
                        },
                        {"key": "prompt", "valueString": r.prompt},
                        {
                            "key": "answers",
                            "valueString": f"あなた: {r.selected} / 正解: {r.correct}",
                        },
                    ],
                }
            )

        data_model_contents = [
            {"key": "results", "valueMap": results_value_map},
        ]

        # Patch template bindings: Use data context paths inside template.
        # In v0.8, Text.text.path relative to item is plain key (e.g., "status").
        # We update the Text components to bind by path.
        for c in components:
            if c.get("id") == "result-status":
                c["component"]["Text"]["text"] = {"path": "status"}
            elif c.get("id") == "result-question":
                c["component"]["Text"]["text"] = {"path": "prompt"}
            elif c.get("id") == "result-answers":
                c["component"]["Text"]["text"] = {"path": "answers"}

        return [
            {"beginRendering": {"surfaceId": SURFACE_ID, "root": "root"}},
            {"surfaceUpdate": {"surfaceId": SURFACE_ID, "components": components}},
            {
                "dataModelUpdate": {
                    "surfaceId": SURFACE_ID,
                    "path": "/",
                    "contents": data_model_contents,
                }
            },
        ]

