"""WebSocket chat endpoint for real-time agent conversations."""

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_access_token
from app.core.permissions import check_agent_access, is_agent_expired
from app.database import async_session
from app.models.agent import Agent
from app.models.audit import ChatMessage
from app.models.llm import LLMModel
from app.models.user import User

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manage WebSocket connections per agent."""

    def __init__(self):
        # agent_id_str -> list of (WebSocket, session_id_str | None)
        self.active_connections: dict[str, list[tuple]] = {}

    async def connect(self, agent_id: str, websocket: WebSocket, session_id: str = None):
        await websocket.accept()
        if agent_id not in self.active_connections:
            self.active_connections[agent_id] = []
        self.active_connections[agent_id].append((websocket, session_id))

    def disconnect(self, agent_id: str, websocket: WebSocket):
        if agent_id in self.active_connections:
            self.active_connections[agent_id] = [
                (ws, sid) for ws, sid in self.active_connections[agent_id] if ws != websocket
            ]

    async def send_message(self, agent_id: str, message: dict):
        if agent_id in self.active_connections:
            for ws, _sid in self.active_connections[agent_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    async def send_to_session(self, agent_id: str, session_id: str, message: dict):
        """Send message only to WebSocket connections matching the given session_id."""
        if agent_id in self.active_connections:
            for ws, sid in self.active_connections[agent_id]:
                if sid == session_id:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        pass

    def get_active_session_ids(self, agent_id: str) -> list[str]:
        """Return distinct session IDs for all active WS connections of an agent."""
        if agent_id not in self.active_connections:
            return []
        return list(set(sid for _ws, sid in self.active_connections[agent_id] if sid))


manager = ConnectionManager()


from fastapi import Depends
from app.core.security import get_current_user
from app.database import get_db
from app.models.user import User


@router.get("/api/chat/{agent_id}/history")
async def get_chat_history(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return web chat message history for this user + agent."""
    conv_id = f"web_{current_user.id}"
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.agent_id == agent_id, ChatMessage.conversation_id == conv_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(200)
    )
    messages = result.scalars().all()
    out = []
    for m in messages:
        entry: dict = {
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        if getattr(m, "thinking", None):
            entry["thinking"] = m.thinking
        if m.role == "tool_call":
            # Parse JSON-encoded tool call data
            try:
                import json

                data = json.loads(m.content)
                entry["content"] = ""
                entry["toolName"] = data.get("name", "")
                entry["toolArgs"] = data.get("args")
                entry["toolStatus"] = data.get("status", "done")
                entry["toolResult"] = data.get("result", "")
            except Exception:
                pass
        out.append(entry)
    return out


def _parse_text_tool_calls(text: str) -> list[dict]:
    """Parse tool calls from text format like [TOOL_CALL] {tool => "name", args => {...}}.

    Returns list of {"name": str, "args": dict}.
    """
    import re

    results = []

    # Pattern 1: [TOOL_CALL] {tool => "name", args => {...}}
    pattern1 = r'\[TOOL_CALL\]\s*\{\s*tool\s*=>\s*["\']?(\w+)["\']?\s*,\s*args\s*=>\s*(\{[^}]*\})\s*\}'
    for match in re.finditer(pattern1, text, re.DOTALL | re.IGNORECASE):
        tool_name = match.group(1)
        args_str = match.group(2)
        try:
            # Convert Ruby-style hash to JSON: --key "value" -> "key": "value"
            args = _parse_ruby_style_args(args_str)
            results.append({"name": tool_name, "args": args})
        except Exception as e:
            logger.warning(f"[ToolParse] Failed to parse args: {args_str[:100]}, error: {e}")

    # Pattern 2: Simpler format detection
    if not results:
        # Check for common tool names in text
        tool_patterns = [
            (r"send_channel_file\s*\([^)]*\)", "send_channel_file"),
            (r"send_file\s*\([^)]*\)", "send_channel_file"),
            (r"list_files\s*\([^)]*\)", "list_files"),
            (r"read_file\s*\([^)]*\)", "read_file"),
            (r"write_file\s*\([^)]*\)", "write_file"),
        ]
        for pattern, tool_name in tool_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                # Try to extract basic args
                args = _extract_simple_args(text, tool_name)
                if args:
                    results.append({"name": tool_name, "args": args})
                    break

    return results


def _parse_ruby_style_args(args_str: str) -> dict:
    """Parse Ruby-style args like --key "value" into dict."""
    import re

    args = {}

    # Remove outer braces if present
    args_str = args_str.strip()
    if args_str.startswith("{") and args_str.endswith("}"):
        args_str = args_str[1:-1]

    # Pattern: --key "value" or --key 'value'
    pattern = r'--(\w+)\s+["\']([^"\']*)["\']'
    for match in re.finditer(pattern, args_str):
        key = match.group(1)
        value = match.group(2)
        args[key] = value

    # Also try key: "value" format
    pattern2 = r'["\']?(\w+)["\']?\s*:\s*["\']([^"\']*)["\']'
    for match in re.finditer(pattern2, args_str):
        key = match.group(1)
        value = match.group(2)
        if key not in args:
            args[key] = value

    return args


def _extract_simple_args(text: str, tool_name: str) -> dict:
    """Extract simple arguments from text for common tools."""
    import re

    args = {}

    if tool_name == "send_channel_file":
        # Look for file_path pattern
        file_match = re.search(r'file_path["\']?\s*[:=]\s*["\']([^"\']+)["\']', text, re.IGNORECASE)
        if file_match:
            args["file_path"] = file_match.group(1)

        # Look for member_name pattern
        name_match = re.search(r'member_name["\']?\s*[:=]\s*["\']([^"\']+)["\']', text, re.IGNORECASE)
        if name_match:
            args["member_name"] = name_match.group(1)

        # Look for message pattern
        msg_match = re.search(r'message["\']?\s*[:=]\s*["\']([^"\']+)["\']', text, re.IGNORECASE)
        if msg_match:
            args["message"] = msg_match.group(1)

    elif tool_name == "list_files":
        path_match = re.search(r'path["\']?\s*[:=]\s*["\']([^"\']*)["\']', text, re.IGNORECASE)
        if path_match:
            args["path"] = path_match.group(1)

    elif tool_name in ("read_file", "write_file"):
        path_match = re.search(r'path["\']?\s*[:=]\s*["\']([^"\']+)["\']', text, re.IGNORECASE)
        if path_match:
            args["path"] = path_match.group(1)

    return args


def _remove_tool_call_text(text: str) -> str:
    """Remove [TOOL_CALL] blocks from text."""
    import re

    # Remove [TOOL_CALL] and everything until the closing }}
    # Match from [TOOL_CALL] to the end of the closing }}
    cleaned = re.sub(r"\[TOOL_CALL\]\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\s*", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Also remove any remaining standalone } from incomplete parsing
    if cleaned.strip() == "}":
        cleaned = ""

    # Fallback: if still contains TOOL_CALL pattern, remove everything from [TOOL_CALL] onwards
    if "[TOOL_CALL]" in cleaned.upper():
        idx = cleaned.upper().find("[TOOL_CALL]")
        cleaned = cleaned[:idx]

    # Clean up extra whitespace
    cleaned = re.sub(r"\n\s*\n", "\n\n", cleaned).strip()
    return cleaned


async def call_llm(
    model: LLMModel,
    messages: list[dict],
    agent_name: str,
    role_description: str,
    agent_id=None,
    user_id=None,
    session_id: str = "",
    on_chunk=None,
    on_tool_call=None,
    on_thinking=None,
    supports_vision=False,
) -> str:
    """Call LLM via unified client with function-calling tool loop.

    Args:
        on_chunk: Optional async callback(text: str) for streaming chunks to client.
        on_thinking: Optional async callback(text: str) for reasoning/thinking content.
        on_tool_call: Optional async callback(dict) for tool call status updates.
    """
    from app.services.agent_tools import AGENT_TOOLS, execute_tool, get_agent_tools_for_llm
    from app.services.llm_utils import create_llm_client, get_max_tokens, LLMMessage, LLMError

    # ── Token limit check & config ──
    _max_tool_rounds = 50  # default
    if agent_id:
        try:
            from app.models.agent import Agent as AgentModel

            async with async_session() as _db:
                _ar = await _db.execute(select(AgentModel).where(AgentModel.id == agent_id))
                _agent = _ar.scalar_one_or_none()
                if _agent:
                    _max_tool_rounds = _agent.max_tool_rounds or 50
                    if _agent.max_tokens_per_day and _agent.tokens_used_today >= _agent.max_tokens_per_day:
                        return f"⚠️ Daily token usage has reached the limit ({_agent.tokens_used_today:,}/{_agent.max_tokens_per_day:,}). Please try again tomorrow or ask admin to increase the limit."
                    if _agent.max_tokens_per_month and _agent.tokens_used_month >= _agent.max_tokens_per_month:
                        return f"⚠️ Monthly token usage has reached the limit ({_agent.tokens_used_month:,}/{_agent.max_tokens_per_month:,}). Please ask admin to increase the limit."
        except Exception:
            pass

    # Build rich prompt with soul, memory, skills, relationships
    from app.services.agent_context import build_agent_context

    # Look up current user's display name so the agent knows who it's talking to
    _current_user_name = None
    if user_id:
        try:
            from app.models.user import User as _UserModel

            async with async_session() as _udb:
                _ur = await _udb.execute(select(_UserModel).where(_UserModel.id == user_id))
                _u = _ur.scalar_one_or_none()
                if _u:
                    _current_user_name = _u.display_name or _u.username
        except Exception:
            pass
    static_prompt, dynamic_prompt = await build_agent_context(
        agent_id, agent_name, role_description, current_user_name=_current_user_name
    )

    # Load tools dynamically from DB
    tools_for_llm = await get_agent_tools_for_llm(agent_id) if agent_id else AGENT_TOOLS

    # Convert messages to LLMMessage format
    api_messages = [LLMMessage(role="system", content=static_prompt, dynamic_content=dynamic_prompt)]
    for msg in messages:
        api_messages.append(
            LLMMessage(
                role=msg.get("role", "user"),
                content=msg.get("content"),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
            )
        )

    # ── Vision format conversion ──
    # If the model supports vision, convert image markers in user messages
    # to OpenAI Vision API format: content becomes an array of parts.
    if supports_vision:
        import re as _re_v

        for i, msg in enumerate(api_messages):
            if msg.role != "user" or not msg.content or not isinstance(msg.content, str):
                continue
            content_str = msg.content
            # Find [image_data:data:image/...;base64,...] markers
            pattern = r"\[image_data:(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)\]"
            images = _re_v.findall(pattern, content_str)
            if not images:
                continue
            # Build content array
            text = _re_v.sub(pattern, "", content_str).strip()
            parts = []
            for img_url in images:
                parts.append({"type": "image_url", "image_url": {"url": img_url}})
            if text:
                parts.append({"type": "text", "text": text})
            # Replace the message content with the array format
            api_messages[i] = LLMMessage(
                role=msg.role,
                content=parts,  # type: ignore  # This is valid for vision models
            )
    else:
        # Strip base64 image markers for non-vision models to avoid wasting tokens
        import re as _re_strip

        _img_pattern = r"\[image_data:data:image/[^;]+;base64,[A-Za-z0-9+/=]+\]"
        for i, msg in enumerate(api_messages):
            if msg.role != "user" or not isinstance(msg.content, str):
                continue
            if "[image_data:" in msg.content:
                _n_imgs = len(_re_strip.findall(_img_pattern, msg.content))
                cleaned = _re_strip.sub(_img_pattern, "", msg.content).strip()
                if _n_imgs > 0:
                    cleaned += f"\n[用户发送了 {_n_imgs} 张图片，但当前模型不支持视觉，无法查看图片内容]"
                api_messages[i] = LLMMessage(
                    role=msg.role,
                    content=cleaned,
                )

    # Create the unified LLM client
    try:
        client = create_llm_client(
            provider=model.provider,
            api_key=model.api_key_encrypted,
            model=model.model,
            base_url=model.base_url,
            timeout=float(getattr(model, "request_timeout", None) or 120.0),
        )
    except Exception as e:
        return f"[Error] Failed to create LLM client: {e}"

    max_tokens = get_max_tokens(model.provider, model.model, getattr(model, "max_output_tokens", None))

    # ── Per-round token accumulator ──
    from app.services.token_tracker import record_token_usage, extract_usage_tokens, estimate_tokens_from_chars

    _accumulated_tokens = 0

    # ── Accumulate ALL text content across rounds (not just last round) ──
    # This ensures the final response includes all streaming text,
    # even when tool calls happen in intermediate rounds.
    _all_content_accumulated = ""

    # Tool-calling loop (configurable per agent, default 50)
    for round_i in range(_max_tool_rounds):
        # ── Dynamic tool-call limit warning (Aware engine) ──
        # Don't tell the agent about limits at the start — only warn when approaching.
        # This prevents models from rushing to complete tasks prematurely.
        _warn_threshold_80 = int(_max_tool_rounds * 0.8)
        _warn_threshold_96 = _max_tool_rounds - 2
        if round_i == _warn_threshold_80:
            api_messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        f"⚠️ 你已使用 {round_i}/{_max_tool_rounds} 轮工具调用。"
                        "如果当前任务尚未完成，请尽快保存进度到 focus.md，"
                        "并使用 set_trigger 设置续接触发器，在剩余轮次中做好收尾。"
                    ),
                )
            )
        elif round_i == _warn_threshold_96:
            api_messages.append(
                LLMMessage(
                    role="user",
                    content=f"🚨 仅剩 2 轮工具调用。请立即保存进度到 focus.md 并设置续接触发器。",
                )
            )

        try:
            # Use streaming API for real-time responses
            logger.info(f"[LLM] Round {round_i + 1}: Starting stream, on_chunk={'set' if on_chunk else 'None'}")
            response = await client.stream(
                messages=api_messages,
                tools=tools_for_llm if tools_for_llm else None,
                temperature=model.temperature,
                max_tokens=max_tokens,
                on_chunk=on_chunk,
                on_thinking=on_thinking,
            )
            logger.info(
                f"[LLM] Round {round_i + 1}: Stream done, response.content len={len(response.content or '')}, tool_calls={len(response.tool_calls or [])}"
            )
        except LLMError as e:
            # Record accumulated tokens before returning error
            logger.error(
                f"[LLM] LLMError provider={getattr(model, 'provider', '?')} "
                f"model={getattr(model, 'model', '?')} round={round_i + 1}: {e}"
            )
            if agent_id and _accumulated_tokens > 0:
                await record_token_usage(agent_id, _accumulated_tokens)
            return f"[LLM Error] {e}"
        except Exception as e:
            logger.error(
                f"[LLM] Unexpected error provider={getattr(model, 'provider', '?')} "
                f"model={getattr(model, 'model', '?')} round={round_i + 1}: "
                f"{type(e).__name__}: {str(e)[:300]}"
            )
            if agent_id and _accumulated_tokens > 0:
                await record_token_usage(agent_id, _accumulated_tokens)
            return f"[LLM call error] {type(e).__name__}: {str(e)[:200]}"

        # ── Track tokens for this round ──
        logger.debug(
            f"[LLM] stream() returned: {len(response.content or '')} chars, finish={response.finish_reason}, tools={len(response.tool_calls or [])}"
        )
        real_tokens = extract_usage_tokens(response.usage)
        if real_tokens:
            _accumulated_tokens += real_tokens
        else:
            # Fallback: estimate from message content length
            round_chars = sum(len(m.content or "") if isinstance(m.content, str) else 0 for m in api_messages) + len(
                response.content or ""
            )
            _accumulated_tokens += estimate_tokens_from_chars(round_chars)

        # ── Accumulate content from this round ──
        # Even if tool calls happen, we still want to keep any text content
        if response.content:
            if _all_content_accumulated:
                _all_content_accumulated += "\n\n" + response.content
            else:
                _all_content_accumulated = response.content

        # If no tool calls, check for text-based tool calls (models like MiniMax that don't support native function calling)
        if not response.tool_calls:
            _check_content = _all_content_accumulated or response.content or ""

            # Only parse text-based tool calls for models marked as unreliable
            _should_parse_text = getattr(model, "streaming_tool_calls_unreliable", False)

            # Also auto-detect for known problematic providers (MiniMax, etc.)
            if not _should_parse_text and hasattr(model, "provider"):
                _problematic_providers = {"minimax", "baidu"}
                if model.provider.lower() in _problematic_providers:
                    _should_parse_text = True
                    logger.info(
                        f"[LLM] Auto-detected problematic provider '{model.provider}', enabling text tool parsing"
                    )

            _parsed_tool_calls = []
            if _should_parse_text:
                # Parse [TOOL_CALL] format from text
                _parsed_tool_calls = _parse_text_tool_calls(_check_content)

            if _parsed_tool_calls:
                logger.info(
                    f"[LLM] No native tool_calls but parsed {len(_parsed_tool_calls)} from text in round {round_i + 1}"
                )
                # Execute parsed tool calls
                for _ptc in _parsed_tool_calls:
                    _tool_name = _ptc.get("name", "")
                    _tool_args = _ptc.get("args", {})
                    logger.info(f"[LLM] Executing parsed tool: {_tool_name}({_tool_args})")

                    # Notify client about tool call
                    if on_tool_call:
                        try:
                            await on_tool_call(
                                {
                                    "name": _tool_name,
                                    "args": _tool_args,
                                    "status": "running",
                                }
                            )
                        except Exception:
                            pass

                    # Execute the tool
                    _tool_result = await execute_tool(
                        _tool_name,
                        _tool_args,
                        agent_id=agent_id,
                        user_id=user_id or agent_id,
                        session_id=session_id,
                    )
                    logger.info(f"[LLM] Parsed tool result: {_tool_result[:100] if _tool_result else 'empty'}")

                    # Notify client about result
                    if on_tool_call:
                        try:
                            await on_tool_call(
                                {
                                    "name": _tool_name,
                                    "args": _tool_args,
                                    "status": "done",
                                    "result": _tool_result,
                                }
                            )
                        except Exception:
                            pass

                    # Clean the tool call syntax from response
                    _cleaned_content = _remove_tool_call_text(_check_content)

                    # Check if tool execution failed
                    _is_error = (
                        "error" in _tool_result.lower()
                        or _tool_result.startswith("Error:")
                        or _tool_result.startswith("Tool execution error")
                    )

                    # Return cleaned Agent text (not tool result) if successful
                    # Return error message if failed
                    if _is_error:
                        logger.warning(f"[LLM] Parsed tool execution failed: {_tool_result[:100]}")
                        _final_result = (
                            _cleaned_content + "\n\n⚠️ " + _tool_result if _cleaned_content else "⚠️ " + _tool_result
                        )
                    else:
                        # Tool succeeded - return Agent's original text only
                        _final_result = _cleaned_content if _cleaned_content else "✅ 已完成"

                    if agent_id and _accumulated_tokens > 0:
                        await record_token_usage(agent_id, _accumulated_tokens)
                    await client.close()
                    return _final_result

            # No tool calls found, return final content
            logger.info(
                f"[LLM] No tool calls in round {round_i + 1}, finishing. accumulated_len={len(_all_content_accumulated)}, response_content_len={len(response.content or '')}"
            )
            if agent_id and _accumulated_tokens > 0:
                await record_token_usage(agent_id, _accumulated_tokens)
            await client.close()
            # Return accumulated content if available, else current round content
            final_content = _all_content_accumulated or response.content or "[LLM returned empty content]"
            logger.info(f"[LLM] Returning final content, len={len(final_content)}")
            return final_content

        # Execute tool calls
        logger.info(
            f"[LLM] Round {round_i + 1}: {len(response.tool_calls)} tool call(s), finish_reason={response.finish_reason}"
        )

        # Add assistant message with tool calls
        api_messages.append(
            LLMMessage(
                role="assistant",
                content=response.content or None,
                tool_calls=[
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"],
                    }
                    for tc in response.tool_calls
                ],
                reasoning_content=response.reasoning_content,
            )
        )

        full_reasoning_content = response.reasoning_content or ""

        # Tools that require arguments — if LLM sends empty args, skip and ask to retry
        _TOOLS_REQUIRING_ARGS = {
            "write_file",
            "read_file",
            "delete_file",
            "read_document",
            "send_message_to_agent",
            "send_feishu_message",
            "send_email",
        }

        for tc in response.tool_calls:
            fn = tc["function"]
            tool_name = fn["name"]
            raw_args = fn.get("arguments", "{}")
            logger.info(f"[LLM] Raw arguments for {tool_name} (len={len(raw_args)}): {repr(raw_args[:300])}")
            try:
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                args = {}

            # Guard: if a tool that requires arguments received empty args,
            # return an error to LLM instead of executing (Claude sometimes
            # emits tool_use blocks with no input_json_delta events)
            if not args and tool_name in _TOOLS_REQUIRING_ARGS:
                logger.warning(f"[LLM] Empty arguments for {tool_name}, asking LLM to retry")
                api_messages.append(
                    LLMMessage(
                        role="tool",
                        content=f"Error: {tool_name} was called with empty arguments. You must provide the required parameters. Please retry with the correct arguments.",
                        tool_call_id=tc.get("id", ""),
                    )
                )
                continue

            logger.info(f"[LLM] Calling tool: {tool_name}({args})")
            # Notify client about tool call (in-progress)
            if on_tool_call:
                try:
                    await on_tool_call(
                        {
                            "name": tool_name,
                            "args": args,
                            "status": "running",
                            "reasoning_content": full_reasoning_content,
                        }
                    )
                except Exception:
                    pass

            result = await execute_tool(
                tool_name,
                args,
                agent_id=agent_id,
                user_id=user_id or agent_id,
                session_id=session_id,
            )
            logger.debug(f"[LLM] Tool result: {result[:100]}")

            # Notify client about tool call result
            if on_tool_call:
                try:
                    await on_tool_call(
                        {
                            "name": tool_name,
                            "args": args,
                            "status": "done",
                            "result": result,
                            "reasoning_content": full_reasoning_content,
                        }
                    )
                except Exception as _cb_err:
                    logger.warning(f"[LLM] on_tool_call callback error: {_cb_err}")

            # ── Vision injection for screenshot tools ──
            # If the model supports vision, try to inject the actual screenshot
            # image into the tool result so the LLM can SEE what's on screen.
            # Without this, the LLM only gets text like "Screenshot saved to ..."
            # and blindly guesses the page content.
            tool_content: str | list = str(result)
            if supports_vision and agent_id:
                try:
                    from app.services.vision_inject import try_inject_screenshot_vision
                    from app.services.agent_tools import WORKSPACE_ROOT

                    ws_path = WORKSPACE_ROOT / str(agent_id)
                    vision_content = try_inject_screenshot_vision(tool_name, str(result), ws_path)
                    if vision_content:
                        tool_content = vision_content
                        logger.info(f"[LLM] Injected screenshot vision for {tool_name}")
                except Exception as e:
                    logger.warning(f"[LLM] Vision injection failed for {tool_name}: {e}")

            api_messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=tc["id"],
                    content=tool_content,
                )
            )

    # Record tokens even on "too many rounds" exit
    if agent_id and _accumulated_tokens > 0:
        await record_token_usage(agent_id, _accumulated_tokens)
    await client.close()

    # Return accumulated content if available, with a warning
    if _all_content_accumulated:
        return _all_content_accumulated + "\n\n⚠️ [达到最大工具调用轮数，回复可能不完整]"
    return "[Error] Too many tool call rounds"


@router.websocket("/ws/chat/{agent_id}")
async def websocket_chat(
    websocket: WebSocket,
    agent_id: uuid.UUID,
    token: str = Query(...),
    session_id: str = Query(None),
):
    """WebSocket endpoint for real-time chat with an agent.

    Flow:
    1. Client connects with JWT token + optional session_id as query params
    2. Server accepts immediately so browser onopen fires quickly
    3. Server authenticates and checks agent access
    4. If session_id provided, uses it; otherwise finds/creates the user's latest session
    5. Client sends messages as JSON: {"content": "..."}
    6. Server calls the agent's configured LLM and sends response back
    7. Messages are persisted to chat_messages table under the session
    """
    # Accept immediately so browser sees onopen without waiting for DB setup
    await websocket.accept()

    # Authenticate
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except Exception:
        await websocket.send_json({"type": "error", "content": "Authentication failed"})
        await websocket.close(code=4001)
        return

    # Verify access and load agent + model
    agent_name = ""
    agent_type = ""  # Track agent type for OpenClaw routing
    role_description = ""
    welcome_message = ""
    llm_model = None
    fallback_llm_model = None
    history_messages = []

    try:
        async with async_session() as db:
            logger.info(f"[WS] Looking up user {user_id}")
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                logger.info("[WS] User not found")
                await websocket.send_json({"type": "error", "content": "User not found"})
                await websocket.close(code=4001)
                return

            logger.info(f"[WS] Checking agent access for {agent_id}")
            agent, _ = await check_agent_access(db, user, agent_id)
            # Check agent expiry
            if is_agent_expired(agent):
                await websocket.send_json(
                    {
                        "type": "error",
                        "content": "This Agent has expired and is off duty. Please contact your admin to extend its service.",
                    }
                )
                await websocket.close(code=4003)
                return
            agent_name = agent.name
            agent_type = agent.agent_type or ""
            role_description = agent.role_description or ""
            welcome_message = agent.welcome_message or ""
            from app.models.agent import DEFAULT_CONTEXT_WINDOW_SIZE

            ctx_size = agent.context_window_size or DEFAULT_CONTEXT_WINDOW_SIZE
            logger.info(
                f"[WS] Agent: {agent_name}, type: {agent_type}, model_id: {agent.primary_model_id}, ctx: {ctx_size}"
            )

            # Load the agent's primary model
            if agent.primary_model_id:
                model_result = await db.execute(select(LLMModel).where(LLMModel.id == agent.primary_model_id))
                llm_model = model_result.scalar_one_or_none()
                # Treat disabled models as unavailable at runtime
                if llm_model and not llm_model.enabled:
                    logger.info(f"[WS] Primary model {llm_model.model} is disabled, skipping")
                    llm_model = None
                else:
                    logger.info(f"[WS] Primary model loaded: {llm_model.model if llm_model else 'None'}")

            # Load fallback model
            if agent.fallback_model_id:
                fb_result = await db.execute(select(LLMModel).where(LLMModel.id == agent.fallback_model_id))
                fallback_llm_model = fb_result.scalar_one_or_none()
                # Treat disabled fallback models as unavailable
                if fallback_llm_model and not fallback_llm_model.enabled:
                    logger.info(f"[WS] Fallback model {fallback_llm_model.model} is disabled, skipping")
                    fallback_llm_model = None
                elif fallback_llm_model:
                    logger.info(f"[WS] Fallback model loaded: {fallback_llm_model.model}")

            # Config-level fallback: primary missing -> use fallback
            if not llm_model and fallback_llm_model:
                llm_model = fallback_llm_model
                fallback_llm_model = None  # No further fallback available
                logger.info(f"[WS] Primary model unavailable, using fallback: {llm_model.model}")

            # Resolve or create chat session
            from app.models.chat_session import ChatSession
            from sqlalchemy import select as _sel
            from datetime import datetime as _dt, timezone as _tz

            conv_id = session_id
            if conv_id:
                # Validate the session belongs to this agent and to this user (no hijacking others' sessions).
                try:
                    _sid = uuid.UUID(conv_id)
                except (ValueError, TypeError):
                    conv_id = None
                    _existing = None
                else:
                    _sr = await db.execute(
                        _sel(ChatSession).where(
                            ChatSession.id == _sid,
                            ChatSession.agent_id == agent_id,
                        )
                    )
                    _existing = _sr.scalar_one_or_none()
                    if not _existing:
                        conv_id = None
                    elif _existing.source_channel != "agent" and str(_existing.user_id) != str(user_id):
                        await websocket.send_json({"type": "error", "content": "Not authorized for this session"})
                        await websocket.close(code=4003)
                        return
            if not conv_id:
                # Find most recent session for this user+agent
                _sr = await db.execute(
                    _sel(ChatSession)
                    .where(ChatSession.agent_id == agent_id, ChatSession.user_id == user_id)
                    .order_by(ChatSession.last_message_at.desc().nulls_last(), ChatSession.created_at.desc())
                    .limit(1)
                )
                _latest = _sr.scalar_one_or_none()
                if _latest:
                    conv_id = str(_latest.id)
                else:
                    # Create a default session
                    now = _dt.now(_tz.utc)
                    _new_session = ChatSession(
                        agent_id=agent_id,
                        user_id=user_id,
                        title=f"Session {now.strftime('%m-%d %H:%M')}",
                        source_channel="web",
                        created_at=now,
                    )
                    db.add(_new_session)
                    await db.commit()
                    await db.refresh(_new_session)
                    conv_id = str(_new_session.id)
                    logger.info(f"[WS] Created default session {conv_id}")

            try:
                history_result = await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.agent_id == agent_id, ChatMessage.conversation_id == conv_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(ctx_size)
                )
                history_messages = list(reversed(history_result.scalars().all()))
                logger.info(f"[WS] Loaded {len(history_messages)} history messages for session {conv_id}")
            except Exception as e:
                logger.warning(f"[WS] History load failed (non-fatal): {e}")
    except Exception as e:
        logger.error(f"[WS] Setup error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        await websocket.send_json({"type": "error", "content": "Setup failed"})
        await websocket.close(code=4002)  # Config error — client should NOT retry
        return

    agent_id_str = str(agent_id)
    if agent_id_str not in manager.active_connections:
        manager.active_connections[agent_id_str] = []
    manager.active_connections[agent_id_str].append((websocket, conv_id))
    logger.info(f"[WS] Ready! Agent={agent_name}")

    # Send session_id to frontend so Take Control can reference the correct session
    await websocket.send_json({"type": "connected", "session_id": conv_id})

    # Build conversation context from history
    # IMPORTANT: Include tool_call messages so the LLM maintains tool-calling behavior.
    # Without them, Claude sees user→assistant-text patterns and learns to skip tools.
    conversation: list[dict] = []
    for msg in history_messages:
        if msg.role == "tool_call":
            # Convert stored tool_call JSON into OpenAI-format assistant+tool pair
            try:
                import json as _j_hist

                tc_data = _j_hist.loads(msg.content)
                tc_name = tc_data.get("name", "unknown")
                tc_args = tc_data.get("args", {})
                tc_result = tc_data.get("result", "")
                tc_id = f"call_{msg.id}"  # synthetic tool_call_id
                # Assistant message with tool_calls array
                asst_msg = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc_id,
                            "type": "function",
                            "function": {"name": tc_name, "arguments": _j_hist.dumps(tc_args, ensure_ascii=False)},
                        }
                    ],
                }
                if tc_data.get("reasoning_content"):
                    asst_msg["reasoning_content"] = tc_data["reasoning_content"]
                conversation.append(asst_msg)
                # Tool result message.
                # Sanitize any stale [ImageID: ...] markers left by the ephemeral
                # screenshot cache — those images are gone from memory and would
                # confuse the LLM if sent as-is.
                from app.services.vision_inject import sanitize_history_tool_result

                sanitized_result = sanitize_history_tool_result(str(tc_result))
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": sanitized_result[:500],
                    }
                )
            except Exception:
                continue  # Skip malformed tool_call records
        else:
            entry = {"role": msg.role, "content": msg.content}
            if hasattr(msg, "thinking") and msg.thinking:
                entry["thinking"] = msg.thinking
            conversation.append(entry)

    try:
        # Send welcome message on new session (no history)
        if welcome_message and not history_messages:
            await websocket.send_json({"type": "done", "role": "assistant", "content": welcome_message})

        while True:
            logger.info(f"[WS] Waiting for message from {agent_name}...")
            data = await websocket.receive_json()

            # Set a unique trace ID for this specific message processing
            from app.core.logging_config import set_trace_id
            import uuid as _trace_uuid

            trace_id = str(_trace_uuid.uuid4())[:12]
            set_trace_id(trace_id)

            content = data.get("content", "")
            display_content = data.get("display_content", "")  # User-facing display text
            file_name = data.get("file_name", "")  # Original file name for attachment display
            logger.info(f"[WS] Received: {content[:50]}")

            if not content:
                continue

            # ── Quota checks ──
            try:
                from app.services.quota_guard import (
                    check_conversation_quota,
                    increment_conversation_usage,
                    check_agent_expired,
                    check_agent_llm_quota,
                    increment_agent_llm_usage,
                    QuotaExceeded,
                    AgentExpired,
                )

                await check_conversation_quota(user_id)
                await check_agent_expired(agent_id)
            except QuotaExceeded as qe:
                await websocket.send_json({"type": "done", "role": "assistant", "content": f"⚠️ {qe.message}"})
                continue
            except AgentExpired as ae:
                await websocket.send_json({"type": "done", "role": "assistant", "content": f"⚠️ {ae.message}"})
                continue

            # Add user message to conversation (full LLM context)
            conversation.append({"role": "user", "content": content})

            # Save user message — display_content for history display, content for LLM
            # Prefix with [file:name] if there's a file attachment so history can show it
            saved_content = display_content if display_content else content
            if file_name:
                saved_content = f"[file:{file_name}]\n{saved_content}"
            async with async_session() as db:
                user_msg = ChatMessage(
                    agent_id=agent_id,
                    user_id=user_id,
                    role="user",
                    content=saved_content,
                    conversation_id=conv_id,
                )
                db.add(user_msg)
                # Update session last_message_at + auto-title on first message
                from app.models.chat_session import ChatSession as _CS
                from datetime import datetime as _dt2, timezone as _tz2

                _now = _dt2.now(_tz2.utc)
                _sess_r = await db.execute(select(_CS).where(_CS.id == uuid.UUID(conv_id)))
                _sess = _sess_r.scalar_one_or_none()
                if _sess:
                    _sess.last_message_at = _now
                    if not history_messages and _sess.title.startswith("Session "):
                        # Use display_content for title (avoids raw base64/markers)
                        title_src = display_content if display_content else content
                        # Clean up common prefixes from image/file messages
                        clean_title = title_src.replace("[图片] ", "📷 ").replace("[image_data:", "").strip()
                        if file_name and not clean_title:
                            clean_title = f"📎 {file_name}"
                        _sess.title = clean_title[:40] if clean_title else content[:40]
                await db.commit()
            logger.info("[WS] User message saved")

            # ── OpenClaw routing: insert into gateway_messages instead of LLM ──
            if agent_type == "openclaw":
                from app.models.gateway_message import GatewayMessage as GwMsg

                async with async_session() as db:
                    gw_msg = GwMsg(
                        agent_id=agent_id,
                        sender_user_id=user_id,
                        conversation_id=conv_id,
                        content=content,
                        status="pending",
                    )
                    db.add(gw_msg)
                    await db.commit()
                logger.info("[WS] OpenClaw: message queued for gateway poll")
                await websocket.send_json(
                    {
                        "type": "done",
                        "role": "assistant",
                        "content": "Message forwarded to OpenClaw agent. Waiting for response...",
                    }
                )
                continue

            # Detect task creation intent
            import re

            task_match = re.search(
                r"(?:创建|新建|添加|建一个|帮我建|create|add)(?:一个|a )?(?:任务|待办|todo|task)[，,：：:\\s]*(.+)",
                content,
                re.IGNORECASE,
            )

            # Track thinking content for storage (initialize before condition)
            thinking_content = []

            # Call LLM with streaming
            if llm_model:
                try:
                    logger.info(f"[WS] Calling LLM {llm_model.model} (streaming)...")

                    # Accumulate partial content for abort handling
                    partial_chunks: list[str] = []

                    async def stream_to_ws(text: str):
                        """Send each chunk to client in real-time."""
                        partial_chunks.append(text)
                        await websocket.send_json({"type": "chunk", "content": text})

                    # Track which agentbay live URLs have been sent to avoid redundant pushes
                    _sent_live_envs: set[str] = set()

                    async def tool_call_to_ws(data: dict):
                        """Send tool call info to client and persist completed ones."""
                        # ── AgentBay live preview: embed screenshot URL in tool_call message ──
                        # We embed live preview data directly in the tool_call payload
                        # because separate WebSocket messages get silently dropped by nginx.
                        if data.get("status") == "done":
                            try:
                                from app.services.agentbay_live import (
                                    detect_agentbay_env,
                                    get_desktop_screenshot,
                                    get_browser_snapshot,
                                )
                                import re as _re_live

                                tool_name = data.get("name", "")
                                env = detect_agentbay_env(tool_name)
                                if env:
                                    tool_result = data.get("result", "") or ""
                                    if env == "desktop":
                                        b64_url = await get_desktop_screenshot(agent_id, session_id=conv_id)
                                        if b64_url:
                                            data["live_preview"] = {"env": env, "screenshot_url": b64_url}
                                            logger.info(f"[WS][LivePreview] Embedded {env} base64 in tool_call")
                                    elif env == "browser":
                                        b64_url = await get_browser_snapshot(agent_id, session_id=conv_id)
                                        if b64_url:
                                            data["live_preview"] = {"env": env, "screenshot_url": b64_url}
                                            logger.info(f"[WS][LivePreview] Embedded {env} base64 in tool_call")
                                    elif env == "code":
                                        data["live_preview"] = {"env": "code", "output": tool_result[:5000]}
                            except Exception as _lp_err:
                                logger.warning(f"[WS][LivePreview] Embed failed: {_lp_err}")

                        await websocket.send_json({"type": "tool_call", **data})

                        # Save completed tool calls to DB so they persist in chat history
                        if data.get("status") == "done":
                            try:
                                import json as _json_tc

                                async with async_session() as _tc_db:
                                    tc_msg = ChatMessage(
                                        agent_id=agent_id,
                                        user_id=user_id,
                                        role="tool_call",
                                        content=_json_tc.dumps(
                                            {
                                                "name": data.get("name", ""),
                                                "args": data.get("args"),
                                                "status": "done",
                                                "result": (data.get("result") or "")[:500],
                                                "reasoning_content": data.get("reasoning_content"),
                                            }
                                        ),
                                        conversation_id=conv_id,
                                    )
                                    _tc_db.add(tc_msg)
                                    await _tc_db.commit()
                            except Exception as _tc_err:
                                logger.warning(f"[WS] Failed to save tool_call: {_tc_err}")

                    # Track thinking content for storage
                    thinking_content = []

                    async def thinking_to_ws(text: str):
                        """Send thinking chunks to client for collapsible display."""
                        thinking_content.append(text)
                        await websocket.send_json({"type": "thinking", "content": text})

                    import asyncio as _aio

                    # Run call_llm as a cancellable task
                    llm_task = _aio.create_task(
                        call_llm(
                            llm_model,
                            conversation[-ctx_size:],
                            agent_name,
                            role_description,
                            agent_id=agent_id,
                            user_id=user_id,
                            session_id=conv_id,
                            on_chunk=stream_to_ws,
                            on_tool_call=tool_call_to_ws,
                            on_thinking=thinking_to_ws,
                            supports_vision=getattr(llm_model, "supports_vision", False),
                        )
                    )

                    # Listen for abort while LLM is running
                    aborted = False
                    queued_messages: list[dict] = []
                    while not llm_task.done():
                        try:
                            msg = await _aio.wait_for(websocket.receive_json(), timeout=0.5)
                            if msg.get("type") == "abort":
                                logger.info(f"[WS] Abort received, cancelling LLM task")
                                llm_task.cancel()
                                aborted = True
                                break
                            else:
                                # Queue non-abort messages for later
                                queued_messages.append(msg)
                        except _aio.TimeoutError:
                            continue
                        except WebSocketDisconnect:
                            llm_task.cancel()
                            raise

                    if aborted:
                        # Wait for task to finish cancelling
                        try:
                            await llm_task
                        except (_aio.CancelledError, Exception):
                            pass
                        partial_text = "".join(partial_chunks).strip()
                        if partial_text:
                            assistant_response = partial_text + "\n\n*[Generation stopped]*"
                        else:
                            assistant_response = "*[Generation stopped]*"
                        logger.info(f"[WS] LLM aborted, partial: {assistant_response[:80]}")
                    else:
                        assistant_response = await llm_task
                        logger.info(f"[WS] LLM response: {assistant_response[:80]}")

                    # Update last_active_at
                    from datetime import datetime, timezone as tz

                    async with async_session() as _db:
                        from app.models.agent import Agent as AgentModel

                        _ar = await _db.execute(select(AgentModel).where(AgentModel.id == agent_id))
                        _agent = _ar.scalar_one_or_none()
                        if _agent:
                            _agent.last_active_at = datetime.now(tz.utc)
                            await _db.commit()

                    # Increment quota usage
                    try:
                        await increment_conversation_usage(user_id)
                        await increment_agent_llm_usage(agent_id)
                    except Exception:
                        pass

                    # Log activity
                    from app.services.activity_logger import log_activity

                    await log_activity(
                        agent_id,
                        "chat_reply",
                        f"Replied to web chat: {assistant_response[:80]}",
                        detail={"channel": "web", "user_text": content[:200], "reply": assistant_response[:500]},
                    )
                except WebSocketDisconnect:
                    raise
                except Exception as e:
                    logger.error(f"[WS] LLM error: {e}")
                    import traceback

                    traceback.print_exc()
                    # Runtime fallback: primary model failed -> retry with fallback model
                    if fallback_llm_model:
                        logger.info(f"[WS] Primary model failed, retrying with fallback: {fallback_llm_model.model}")
                        try:
                            await websocket.send_json(
                                {
                                    "type": "info",
                                    "content": f"Primary model error, switching to fallback model ({fallback_llm_model.model})...",
                                }
                            )
                            assistant_response = await call_llm(
                                fallback_llm_model,
                                conversation[-ctx_size:],
                                agent_name,
                                role_description,
                                agent_id=agent_id,
                                user_id=user_id,
                                session_id=conv_id,
                                on_chunk=stream_to_ws,
                                on_tool_call=tool_call_to_ws,
                                on_thinking=thinking_to_ws,
                                supports_vision=getattr(fallback_llm_model, "supports_vision", False),
                            )
                            logger.info(f"[WS] Fallback LLM response: {assistant_response[:80]}")
                        except Exception as e2:
                            logger.error(f"[WS] Fallback LLM also failed: {e2}")
                            traceback.print_exc()
                            assistant_response = f"[LLM call error] Primary: {str(e)[:100]} | Fallback: {str(e2)[:100]}"
                    else:
                        assistant_response = f"[LLM call error] {str(e)[:200]}"
            else:
                assistant_response = (
                    f"⚠️ {agent_name} has no LLM model configured. Please select a model in the agent's Settings tab."
                )

            # If task creation detected, create a real Task record
            if task_match:
                task_title = task_match.group(1).strip()
                if task_title:
                    try:
                        from app.models.task import Task
                        from app.services.task_executor import execute_task
                        import asyncio as _asyncio

                        async with async_session() as db:
                            task = Task(
                                agent_id=agent_id,
                                title=task_title,
                                created_by=user_id,
                                status="pending",
                                priority="medium",
                            )
                            db.add(task)
                            await db.commit()
                            await db.refresh(task)
                            task_id = task.id
                        _asyncio.create_task(execute_task(task_id, agent_id))
                        assistant_response += f"\n\n📋 Task synced to task board: [{task_title}]"
                        logger.info(f"[WS] Created task: {task_title}")
                    except Exception as e:
                        logger.error(f"[WS] Failed to create task: {e}")

            # Add assistant response to conversation
            conversation.append({"role": "assistant", "content": assistant_response})

            # Save assistant message
            async with async_session() as db:
                asst_msg = ChatMessage(
                    agent_id=agent_id,
                    user_id=user_id,
                    role="assistant",
                    content=assistant_response,
                    thinking="".join(thinking_content) if thinking_content else None,
                    conversation_id=conv_id,
                )
                db.add(asst_msg)
                await db.commit()
            logger.info("[WS] Assistant message saved")

            # Send done signal with final content (for non-streaming clients)
            await websocket.send_json(
                {
                    "type": "done",
                    "role": "assistant",
                    "content": assistant_response,
                }
            )
            logger.info("[WS] Response done sent to client")

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected: {agent_name}")
        manager.disconnect(agent_id_str, websocket)
    except Exception as e:
        logger.error(f"[WS] Error in message loop: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        manager.disconnect(agent_id_str, websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
