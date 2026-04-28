from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI

from agent.context import ChatContext
from agent.memory import Memory
import tools.registry as registry

logger = logging.getLogger("iagent.loop")

# Cap any single tool result before it lands in memory + the message list.
# 8 KB ≈ ~2000 tokens — fits a reasonable response, blocks runaway log dumps,
# image base64, file reads, etc. that would balloon the next request.
_MAX_TOOL_RESULT_BYTES = 8000


def _truncate(s: str, limit: int = _MAX_TOOL_RESULT_BYTES) -> str:
    if not s:
        return s
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return s
    head = encoded[:limit].decode("utf-8", errors="replace")
    return head + f"\n…[truncated, original was {len(encoded)} bytes]"


async def run(
    client: AsyncOpenAI,
    model: str,
    context: ChatContext,
    memory: Memory,
    user_message: str,
) -> str:
    # Persist user turn
    await memory.append(context.chat_id, "user", content=user_message)

    # Build message list: system + history + current user message
    history = await memory.get_history(context.chat_id, limit=context.history_window)
    # Defensive: truncate any oversized historical content so old runaway
    # tool results from before _MAX_TOOL_RESULT_BYTES landed don't keep
    # blowing up requests. Affects in-flight only; DB rows are unchanged.
    for msg in history:
        if isinstance(msg.get("content"), str):
            msg["content"] = _truncate(msg["content"])
    messages: list[dict] = [{"role": "system", "content": context.system_prompt()}]
    messages.extend(history)

    tool_schemas = registry.get_schemas()

    for iteration in range(context.max_iterations):
        logger.debug("Loop iteration %d for chat %d", iteration, context.chat_id)

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            tool_choice="auto" if tool_schemas else None,
        )

        choice = response.choices[0]
        finish = choice.finish_reason

        if finish == "stop" or finish == "end_turn":
            reply = choice.message.content or ""
            await memory.append(context.chat_id, "assistant", content=reply)
            await memory.prune(context.chat_id, keep=context.history_window * 2)
            return reply

        if finish == "tool_calls":
            tool_calls = choice.message.tool_calls or []

            # Serialise the assistant turn (with tool_calls) into memory
            tc_json = json.dumps([
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ])
            await memory.append(
                context.chat_id,
                "assistant",
                content=choice.message.content,
                tool_calls=tc_json,
            )

            # Add assistant message to in-flight messages
            messages.append(choice.message)

            # Dispatch all tool calls in parallel
            results = await asyncio.gather(
                *[registry.dispatch(tc.function.name, tc.function.arguments) for tc in tool_calls]
            )

            for tc, result in zip(tool_calls, results):
                truncated = _truncate(result)
                if truncated != result:
                    logger.info(
                        "Truncated %s output: %d → %d bytes",
                        tc.function.name, len(result), len(truncated),
                    )
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": truncated,
                }
                messages.append(tool_msg)
                await memory.append(
                    context.chat_id,
                    "tool",
                    content=truncated,
                    tool_call_id=tc.id,
                )

            continue  # next iteration with updated messages

        # Any other finish reason (content_filter, length, etc.)
        reply = choice.message.content or f"[Stopped: {finish}]"
        await memory.append(context.chat_id, "assistant", content=reply)
        return reply

    return "[Error: agent loop exceeded maximum iterations]"
