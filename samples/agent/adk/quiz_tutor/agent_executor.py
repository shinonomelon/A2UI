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

import logging
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Part, Task, TaskState, TextPart, UnsupportedOperationError
from a2a.utils import new_agent_parts_message, new_task
from a2a.utils.errors import ServerError
from a2ui.a2ui_extension import create_a2ui_part, try_activate_a2ui_extension

from agent import QuizTutorAgent

logger = logging.getLogger(__name__)


class QuizTutorAgentExecutor(AgentExecutor):
    """Quiz Tutor AgentExecutor (A2UI)."""

    def __init__(self):
        self.ui_agent = QuizTutorAgent(use_ui=True)
        self.text_agent = QuizTutorAgent(use_ui=False)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info(f"--- Client requested extensions: {context.requested_extensions} ---")
        use_ui = try_activate_a2ui_extension(context)

        agent = self.ui_agent if use_ui else self.text_agent

        action_name: str | None = None
        action_ctx: dict[str, Any] = {}
        if context.message and context.message.parts:
            for part in context.message.parts:
                if isinstance(part.root, DataPart) and isinstance(part.root.data, dict):
                    if "userAction" in part.root.data and isinstance(
                        part.root.data["userAction"], dict
                    ):
                        ui_event = part.root.data["userAction"]
                        action_name = ui_event.get("name")
                        action_ctx = ui_event.get("context", {}) or {}

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        try:
            if action_name:
                text, messages = await agent.handle_ui_action(
                    action_name, action_ctx, task.context_id
                )
            else:
                query = context.get_user_input()
                text, messages = await agent.handle_text(query, task.context_id)

            final_parts: list[Part] = []
            if text.strip():
                final_parts.append(Part(root=TextPart(text=text.strip())))
            if use_ui and messages:
                for msg in messages:
                    final_parts.append(create_a2ui_part(msg))

            if not final_parts:
                final_parts = [Part(root=TextPart(text="OK."))]

            await updater.update_status(
                TaskState.input_required,
                new_agent_parts_message(final_parts, task.context_id, task.id),
                final=False,
            )
        except Exception as e:
            logger.exception("QuizTutorAgentExecutor error")
            await updater.update_status(
                TaskState.input_required,
                new_agent_parts_message(
                    [Part(root=TextPart(text=f"エラーが発生しました: {e}"))],
                    task.context_id,
                    task.id,
                ),
                final=False,
            )

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())

