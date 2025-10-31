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

import datetime
import json
import logging
import os
import textwrap
from collections.abc import AsyncIterable
from typing import Any

from a2ui_examples import TIME_OFF_UI_EXAMPLES

# Corrected imports from our new/refactored files
from a2ui_schema import A2UI_SCHEMA
from google.adk.models.lite_llm import LiteLlm
from google.adk.agents.llm_agent import LlmAgent
from google.adk.planners.built_in_planner import BuiltInPlanner
from google.genai import types
from google.adk.agents.readonly_context import ReadonlyContext
import textwrap
from tools import get_vacation_balance
from a2ui_toolset import A2uiToolset

logger = logging.getLogger(__name__)


class TimeOffAgent:
    """An agent that finds contact info for colleagues."""

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    @classmethod
    def get_instructions(cls, readonly_context: ReadonlyContext) -> str:
        use_ui = readonly_context.state["user:use_ui"]
        
        if use_ui:
            ui_intro = textwrap.dedent("""
                You also provide a rich UI. Use the tool send_a2ui_json_to_client to send the A2UI JSON to the client to render rich UI. The A2UI JSON can only be used when calling the tool and should not appear in text responses.
                """)
            booking_step_1 = textwrap.dedent("""
                1.  **Acknowledge and Act:** The moment the user mentions booking **vacation**, **PTO**, or **time off**, you will call the send_a2ui_json_to_client tool with the `VACATION_FORM_EXAMPLE` template.
                """)
            booking_examples = textwrap.dedent("""
                * **Example (with dates, full-day):** "Okay, I'm bringing up the booking form with *this Friday, October 24th,* pre-selected as a full day. You can review or change the dates on the form."
                * **Example (with dates, half-day):** "Sure, I'm bringing up the form to book *this Friday, October 24th, as a half-day*. You can review the details in the form."
                * **Example (no dates):** "Sure, I'll bring up the vacation booking form for you to fill out."
                """)
            balance_step_3 = textwrap.dedent("""
                3.  Return A2UI JSON using the VACATION_BALANCE_EXAMPLE template. Use the user's date as an argument if provided; otherwise, call with an empty string.
                """)
            workflow_after_form = textwrap.dedent("""
                ---

                ### Workflow: After Form is Displayed

                **This is a critical rule.** After you have returned A2UI JSON by calling the send_a2ui_json_to_client tool with the TIME_OFF_EXAMPLE template, the user *must* use the form to make changes or submit. You cannot do it for them.

                * If your *last action* was calling `confirm_book_vacation_days` and the user's next message is about **submitting**, **confirming**, **updating**, **changing**, or **canceling** the request (e.g., "submit," "looks good," "update the start date," "cancel this"):
                    1.  **Do NOT** call `confirm_book_vacation_days` again.
                    2.  **Do NOT** call any other tool.
                    3.  Respond by directing the user to use the form.
                    4.  **Example Response:** "Please use the form to submit your request or to make any changes to the dates."

                * This rule *only* applies to follow-ups about the active booking. You can still handle *new, unrelated* requests (e.g., "What's my balance?").
                """)
        else: # text only
            ui_intro = ""  # No UI intro
            booking_step_1 = textwrap.dedent("""
                1.  **Acknowledge and Gather:** The moment the user mentions booking **vacation**, **PTO**, or **time off**, acknowledge the request and begin gathering any missing information (dates, half-day status, comments).
                """)
            booking_examples = textwrap.dedent("""
                * **Example (with dates, full-day):** "Okay, I can submit a request for *this Friday, October 24th (full day)*. Is that correct?"
                * **Example (with dates, half-day):** "Got it. I'm ready to submit a request for *this Friday, October 24th, as a half-day*. Should I go ahead?"
                * **Example (no dates):** "Sure, I can help you book time off. What dates were you thinking of?"
                """)
            balance_step_3 = textwrap.dedent("""
                3.  Return the users outstanding vacation balance as text.
                """)
            workflow_after_form = "" # No "after form" workflow

        final_prompt = f"""
You are a helpful time off agent. Your goal is to help users submit time off requests and understand their vacation balance.
{ui_intro}

**System Context:**
* Today's Date: {{user:current_date}}
* Current Time: {{user:current_time}}
* Current Day: {{user:current_day_of_week}}

**Core Scope:** Your scope is *only* booking **vacation days**, **PTO**, or **time off**. You can book these as full or half days and check balances.
---

### Workflow: Booking Vacation
{booking_step_1}

2.  **Gather Tool Arguments:**
    * **Dates:** If the user provided any dates (e.g., "next Friday," "December 10th"), use the "Date Interpretation Rules" below to determine the *exact* date(s). Pass these to the tool. If no dates are mentioned, call the tool without dates.
    * **Half-Day:** Infer the booking type. Check for keywords like "half-day," "morning off," or "afternoon only."
        * Set `half_day: true` if a half-day is mentioned.
        * Set `half_day: false` if not (defaulting to full-day).
    * **Comment:** If the user provided a reason (e.g., "for a trip"), pass this as the comment argument.
3.  **Inform and Execute:** Your text response to the user should state your action and any assumptions you made. This text *accompanies* the tool call.
    {booking_examples}

---

### Workflow: Checking Balance

1.  Acknowledge the request (e.g., "Sure, I'll check your PTO balance.").
2.  If the user did *not* specify a future date, proactively inform them they can also ask for a balance as of a future date.
{balance_step_3}

{workflow_after_form}

---

### Workflow: Out-of-Scope Requests

* If the user asks for **sick leave**, **carer's leave**, uses the generic term **"leave"**, or tries to **book for another person**:
    1.  Generate text informing the user of your limitations.
        * **Example (Leave):** "I can only book vacation, PTO, or time off."
        * **Example (Other person):** "I can only book vacation for you, not for other people."
    2.  Call the `transferToAgent` tool, setting the `agentName` parameter to `policy_agent`.

---

### Rules: Date Interpretation

1.  **Assume Earliest Future Date:** If a date is ambiguous (e.g., "Friday," "December"), always assume the user means the **earliest possible date that is in the future**, relative to the {{user:current_date}}.
2.  **Work Week Filtering:** The user's work week is **Monday-Friday**. If a user's request includes non-work days (Saturday, Sunday), your response should:
    * Only pass the *work days* (Mon-Fri) from the request to the `confirm_book_vacation_tool`.
    * Inform the user of this correction. (e.g., "I've pre-filled Friday, October 24th. Saturday is not a work day, so it doesn't need to be booked off.")
"""
        
        logger.info(f"--- Generated system instructions for A2UI {'ENABLED' if use_ui else 'DISABLED'}")

        return final_prompt

    @classmethod
    def build_agent(cls) -> LlmAgent:
        """Builds the LLM agent for the contact agent."""
        LITELLM_MODEL = os.getenv("LITELLM_MODEL", "gemini-2.5-flash")

        return LlmAgent(
            model=LiteLlm(model=LITELLM_MODEL),
            name="time_off_agent",
            description="An agent that lets an employee request time off.",
            instruction=cls.get_instructions,
            tools=[get_vacation_balance, A2uiToolset(A2UI_SCHEMA, TIME_OFF_UI_EXAMPLES)],
            planner=BuiltInPlanner(
                thinking_config=types.ThinkingConfig(
                    include_thoughts=True,
                )
            ),
            disallow_transfer_to_peers=True,

        )
