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

import json
import logging
from typing import Any, List, override

from a2a.server.agent_execution import  RequestContext

from google.adk.agents.invocation_context import new_invocation_context_id
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.a2a.converters.request_converter import AgentRunRequest
from google.adk.a2a.executor.a2a_agent_executor import (A2aAgentExecutorConfig, A2aAgentExecutor)
from a2a import types as a2a_types

import datetime

from agent import TimeOffAgent
import part_converter
logger = logging.getLogger(__name__)


class TimeOffAgentExecutor(A2aAgentExecutor):
    """Contact AgentExecutor Example."""

    def __init__(self, base_url: str):
        # Instantiate two agents: one for UI and one for text-only.
        # The appropriate one will be chosen at execution time.
        self._base_url = base_url
        agent = TimeOffAgent.build_agent()        
        runner = Runner(
            app_name=agent.name,
            agent=agent,
            artifact_service=InMemoryArtifactService(),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
        )
        config = A2aAgentExecutorConfig(
            event_converter = part_converter.convert_event_to_a2a_events
        )
        super().__init__(runner = runner, config = config)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        use_ui: bool = False,  # This will be passed by the a2ui wrapper
    ) -> None:
        # Save locally so we can add it to the session in _prepare_session
        # TODO: pull this dynamically from the RequestContext
        self.use_ui = True # Force for now.

        return await super().execute(context=context, event_queue=event_queue)

    async def _handle_request(
            self,
            context: RequestContext,
            event_queue: EventQueue
    ):
        # Handle user actions.
        for i, part in enumerate(context.message.parts if context.message else []):
            if isinstance(part.root, a2a_types.DataPart) and "userAction" in part.root.data:
                if "userAction" in part.root.data:
                    ui_event_part = part.root.data["userAction"]
                    
                    logger.info(f"--- TimeOffAgentExecutor received a2ui ClientEvent: {ui_event_part}")
                    
                    action = ui_event_part.get("actionName")
                    ctx = ui_event_part.get("context", {})

                    if action == "submit_vacation_request":
                        contact_name = ctx.get("startDate", "")
                        department = ctx.get("endDate", "")
                        daily_quantity = ctx.get("dailyQuantity", "")
                        type_ = ctx.get("type", "")
                        comment = ctx.get("comment", "")
                        
                        # For demo just replace the part to the agent what was submitted
                        context.message.parts[i] = a2a_types.Part(root=a2a_types.TextPart(text=f"User submitted vacation request with data: {contact_name}, {department}, {daily_quantity}, {type_}, {comment}"))

                        logger.info(f"--- TimeOffAgentExecutor processed user action submit_vacation_request")


        return await super()._handle_request(context=context, event_queue=event_queue)


    @override
    async def _prepare_session(
        self,
        context: RequestContext,
        run_request: AgentRunRequest,
        runner: Runner,
    ):
        session = await super()._prepare_session(context, run_request, runner)

        if "base_url" not in session.state:
            session.state["base_url"] = self._base_url

        # These are used in the system instruction.
        now = datetime.datetime.now()
        await runner.session_service.append_event(
            session,
            Event(
                invocation_id=new_invocation_context_id(),
                author="system",
                actions=EventActions(state_delta={
                    "user:current_date": now.strftime("%Y-%m-%d"),
                    "user:current_time": now.strftime("%H:%M"),
                    "user:current_day_of_week": now.strftime("%A"),
                    "user:use_ui": self.use_ui, # TODO: pull this dynamically from the RequestContext
                })
            ),
        )

        return session