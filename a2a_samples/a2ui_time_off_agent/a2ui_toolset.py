import json
import uuid
import jsonschema
import logging
from typing import Any, List, Optional

from a2a import types as a2a_types
from google.genai import types as genai_types

from google.adk.tools.base_tool import BaseTool
from google.adk.tools import base_toolset
from google.adk.tools.tool_context import ToolContext
from google.adk.a2a.converters import part_converter
from a2ui_ext import a2ui_MIME_TYPE
from google.adk.a2a.converters import event_converter
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext

logger = logging.getLogger(__name__)


class A2uiToolset(base_toolset.BaseToolset):
  """A toolset that provides A2UI Tools and can be enabled/disabled."""

  def __init__(self, a2ui_schema: str, a2ui_examples: str):
    super().__init__()
    self._ui_tools = [SendA2uiJsonToClientTool(a2ui_schema=a2ui_schema, a2ui_examples=a2ui_examples)]

  async def get_tools(
      self,
      readonly_context: Optional[ReadonlyContext] = None,
  ) -> List[BaseTool]:
    use_ui = readonly_context.state["user:use_ui"]
    logger.info(f"--- A2UI is {'ENABLED' if use_ui else 'DISABLED'} in A2uiToolset, adding ui tools")
    return self._ui_tools if use_ui else []

class SendA2uiJsonToClientTool(BaseTool):
    TOOL_NAME = "send_a2ui_json_to_client"
    A2UI_JSON_ARG_NAME = "a2ui_json"

    def __init__(self, a2ui_schema: str, a2ui_examples: str):
        super().__init__(
            name=self.TOOL_NAME, 
            description="Sends A2UI JSON to the client to render rich UI for the user."                
                        "Args:" 
                        f"    {self.A2UI_JSON_ARG_NAME}: Valid A2UI JSON Schema to send to the client. The A2UI JSON Schema definition is between ---BEGIN A2UI JSON SCHEMA--- and ---END A2UI JSON SCHEMA--- in the system instructions.")
        
        self._a2ui_schema = a2ui_schema
        self._a2ui_examples = a2ui_examples

        try:
            # First, load the schema for a *single message*
            single_message_schema = json.loads(a2ui_schema)

            # The prompt instructs the LLM to return a *list* of messages.
            # Therefore, our validation schema must be an *array* of the single message schema.
            self.a2ui_schema_object = {"type": "array", "items": single_message_schema}
            logger.info("A2UI_SCHEMA successfully loaded.")
        except json.JSONDecodeError as e:
            logger.error(f"CRITICAL: Failed to parse A2UI_SCHEMA: {e}")
            raise e

    def _get_declaration(self) -> genai_types.FunctionDeclaration | None:
        return genai_types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    self.A2UI_JSON_ARG_NAME: genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="valid A2UI JSON Schema to send to the client.",
                    ),
                },
                required=[self.A2UI_JSON_ARG_NAME],
            ),
        )
    
    async def process_llm_request(
        self, *, tool_context: ToolContext, llm_request: genai_types.LlmRequest
    ) -> None:
        await super().process_llm_request(tool_context=tool_context, llm_request=llm_request)
        
        # TODO: This approach is inefficient, as the LLM does not need the A2UI schema and examples unless it has already decided to call the tool.
        # Move the schema and examples the parameter properties.
        llm_request.append_instructions([f"""    
 ---BEGIN A2UI JSON SCHEMA---
{self._a2ui_schema}
---END A2UI JSON SCHEMA---                                       

{self._a2ui_examples}
"""])
        
        logger.info(f"--- SendA2uiJsonToClientTool added a2ui_schema and examples to system instructions")

    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> Any:
        try:
            a2ui_json = args.get(self.A2UI_JSON_ARG_NAME)
            if not a2ui_json:
                raise ValueError(f"Failed to call tool {self.TOOL_NAME} because missing required arg {self.A2UI_JSON_ARG_NAME} ")
            
            a2ui_json_payload = json.loads(a2ui_json)
            jsonschema.validate(
                instance=a2ui_json_payload, schema=self.a2ui_schema_object
            )

            logger.info(f"--- SendA2uiJsonToClientTool validated call to tool {self.TOOL_NAME} with {self.A2UI_JSON_ARG_NAME}")

            # Don't do a second LLM inference call for the None response
            tool_context.actions.skip_summarization = True
            
            return None
        except Exception as e:
            logger.error(f"--- SendA2uiJsonToClientTool failed to call tool {self.TOOL_NAME}: {e}")

 