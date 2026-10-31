"""Experimental AstrBot adapter. Requires documented modern Agent hooks.

Only observed events from administrator-configured routes reach the bridge.
No model provider/key lookup, platform login, unsolicited messages, or private
reasoning capture is performed by this plugin.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.message import TextPart, UserMessageSegment
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.cron.events import CronMessageEvent

from .bridge import AdapterError, Bridge, Router
from .source_client import SourceClient


@register("love_house", "myflww", "爱之屋 Agent 经历记忆（实验适配）", "0.2.0")
class LoveHousePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.router = Router([])
        self._worker = None
        self._last_warning = None
        self._configured = False
        self._build_routes()

    def _build_routes(self):
        bindings = self.config.get("bindings", [])
        if not isinstance(bindings, list) or len(bindings) > 100:
            raise AdapterError("来源配置须为不超过100项的列表")
        bridges = []
        for item in bindings:
            if not isinstance(item, dict):
                raise AdapterError("来源绑定格式不正确")
            config_path = Path(str(item.get("source_config_path", ""))).expanduser()
            if not config_path.is_absolute() or not config_path.is_file():
                raise AdapterError("请选择在此服务器生成的私有来源配置文件")
            client = SourceClient(config_path, timeout=1.0)
            bridges.append(Bridge(config_path.parent / "astrbot-journal", client,
                runtime_agent_id=item.get("runtime_agent_id"), allowed_umos=item.get("allowed_umos", []),
                platform=item.get("platform", "qq")))
        self.router = Router(bridges)
        self._configured = bool(bridges)

    def _route(self, event):
        if self.config.get("enabled", False) is not True:
            return None
        bridge = self.router.for_umo(getattr(event, "unified_msg_origin", None))
        if bridge is None:
            return None
        scheduled = isinstance(event, CronMessageEvent)
        if scheduled and self.config.get("record_scheduled_outputs", False) is not True:
            return None
        if not self._platform_matches(event, bridge.platform, scheduled=scheduled):
            # A configured label is not evidence of the actual platform. In
            # particular, ChatUI/WebChat must not become a QQ observation.
            return None
        try:
            source = bridge.client.status()
            if (source.get('enabled') is not True or source.get('revoked') is not False
                    or source.get('runtime_agent_id') != bridge.runtime_agent_id
                    or source.get('source_id') != bridge.source_id or source.get('adapter') != 'astrbot'
                    or bridge.platform not in source.get('platforms', []) and '*' not in source.get('platforms', [])):
                return None
            return bridge
        except Exception:
            self._warn('source_configuration')
            return None

    @staticmethod
    def _platform_matches(event, configured, *, scheduled=False):
        try:
            actual_name = event.get_platform_name()
            actual_id = event.get_platform_id()
            umo = event.unified_msg_origin
        except Exception:
            return False
        if (not isinstance(actual_name, str) or not actual_name or len(actual_name) > 200
                or not isinstance(actual_id, str) or not actual_id or len(actual_id) > 200
                or not isinstance(umo, str) or umo.split(":", 1)[0] != actual_id):
            return False
        if scheduled:
            # Only _route may enable this for a real CronMessageEvent. AstrBot
            # keeps the original delivery UMO/id but uses name='cron'.
            return actual_name == "cron"
        # AstrBot's core QQ adapters expose these names and an administrator-
        # chosen instance ID. Generic bridges such as Satori are not QQ proof.
        aliases = {"qq": {"qq", "aiocqhttp", "qq_official", "qq_official_webhook"}}
        return actual_name in aliases.get(configured, {configured})

    @staticmethod
    def _message_id(event):
        # Without a stable platform ID, do not substitute a timestamp/UUID and
        # pretend retries can be deduplicated across restarts.
        value = getattr(getattr(event, "message_obj", None), "message_id", None)
        if value is None or not str(value).strip():
            raise AdapterError("平台未提供稳定消息编号，未自动记成完整轮次")
        return str(value)

    def _warn(self, code):
        # Metadata-only and rate-limited: no exception repr, UMO, path, body,
        # provider object or token can be printed accidentally by a failure.
        import time
        stamp = time.monotonic()
        if self._last_warning is None or stamp - self._last_warning > 60:
            self._last_warning = stamp
            logger.warning("[LoveHouse] 记忆适配暂不可用 (%s)；聊天继续，已暂存记录保留。", code)

    async def initialize(self):
        self._start_worker()

    @filter.on_astrbot_loaded()
    async def loaded(self):
        self._start_worker()

    def _start_worker(self):
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self):
        while True:
            if self.config.get("enabled", False) is True:
                for bridge in self.router.bridges:
                    try:
                        await asyncio.to_thread(bridge.flush, 8)
                    except Exception:
                        self._warn("background_queue")
            await asyncio.sleep(2)

    async def terminate(self):
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    @staticmethod
    def _origin(event):
        return {"execution_origin": "scheduled" if isinstance(event, CronMessageEvent) else "message",
                "actual_platform": event.get_platform_name()}

    async def _material(self, event, bridge, message_id):
        marker = "love_house_material_" + bridge.source_id
        material = event.get_extra(marker)
        if not isinstance(material, str):
            material = await asyncio.wait_for(asyncio.to_thread(bridge.read_material,
                event.unified_msg_origin, message_id, event.message_str), timeout=1.2)
            event.set_extra(marker, material)
        return material

    @filter.on_agent_begin()
    async def recall_before_agent(self, event: AstrMessageEvent, run_context: ContextWrapper[AstrAgentContext]):
        bridge = self._route(event)
        if bridge is None or event.get_extra("love_house_request_material_" + bridge.source_id) is True:
            return
        try:
            messages = getattr(run_context, "messages", None)
            if not isinstance(messages, list):
                raise AdapterError("宿主未提供可追加的运行消息")
            material = await self._material(event, bridge, self._message_id(event))
            if any(getattr(part, "text", None) == material
                   for message in messages if isinstance(getattr(message, "content", None), list)
                   for part in message.content):
                return
            message = UserMessageSegment(content=[TextPart(text=material).mark_as_temp()])
            message._no_save = True
            messages.append(message)
            # Scheduler instructions are retrieval queries only. No synthetic
            # user turn or run/tool history is copied into the memory journal.
        except Exception:
            self._warn("agent_begin_recall")

    @filter.on_llm_request()
    async def recall_before_request(self, event: AstrMessageEvent, req: ProviderRequest):
        bridge = self._route(event)
        if bridge is None:
            return
        try:
            message_id = self._message_id(event)
            if not isinstance(event, CronMessageEvent):
                await asyncio.to_thread(bridge.stage_received, event.unified_msg_origin, message_id,
                    event.message_str, occurred_at=getattr(event.message_obj, "timestamp", None),
                    sender_id=event.get_sender_id())
            # A tool-loop may prepare several requests for one received event.
            # Rehearsal is not proportional to the number of loop steps.
            material = await self._material(event, bridge, message_id)
            if any(getattr(part, 'text', None) == material for part in req.extra_user_content_parts):
                return
            req.extra_user_content_parts.append(TextPart(text=material).mark_as_temp())
            event.set_extra("love_house_request_material_" + bridge.source_id, True)
        except Exception:
            self._warn("recall_or_stage")

    @filter.on_agent_done()
    async def final_generation(self, event: AstrMessageEvent, run_context: ContextWrapper[AstrAgentContext], resp: LLMResponse):
        bridge = self._route(event)
        if bridge is None or resp is None:
            return
        try:
            if getattr(resp, "is_chunk", False) or bool(getattr(resp, "tools_call_name", [])):
                return
            role = getattr(resp, "role", "")
            termination = "failed" if role == "err" else "cancelled" if self._reported_abort(run_context, resp) else None
            if termination:
                text = ("宿主报告本次运行失败，未取得完整助手输出；不代表外部操作失败。" if termination == "failed"
                        else "宿主报告本次输出已停止，没有完整助手输出；不代表外部操作失败。")
                await asyncio.to_thread(bridge.stage_observation, event.unified_msg_origin,
                    self._message_id(event), text, stage="execution_terminal", failed=termination == "failed",
                    execution_status=termination, **self._origin(event))
                return
            await asyncio.to_thread(bridge.stage_final, event.unified_msg_origin, self._message_id(event),
                getattr(resp, "completion_text", ""), is_chunk=getattr(resp, "is_chunk", False),
                has_tool_calls=bool(getattr(resp, "tools_call_name", [])), role=getattr(resp, "role", ""),
                aborted=self._aborted(event, run_context, resp), **self._origin(event))
        except Exception:
            self._warn("final_generation")

    @staticmethod
    def _aborted(event, run_context, resp):
        stopped = getattr(event, "is_stopped", None)
        if callable(stopped) and stopped():
            return True
        return LoveHousePlugin._reported_abort(run_context, resp)

    @staticmethod
    def _reported_abort(run_context, resp):
        if any(getattr(resp, flag, False) is True for flag in ("aborted", "cancelled")):
            return True
        # AstrBot 4.29.3 reports interruption as role=assistant, then calls done.
        # Detect its exact public synthetic pair; never persist that stop notice
        # as successful output and never inspect reasoning/provider completion.
        messages = getattr(run_context, "messages", None)
        if getattr(resp, "completion_text", None) != "Output stopped." or not isinstance(messages, list) or len(messages) < 2:
            return False
        def plain(message):
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(part.text for part in content if isinstance(part, TextPart))
            return None
        return (getattr(messages[-2], "role", None) == "user" and plain(messages[-2]) == "Stop output."
                and getattr(messages[-1], "role", None) == "assistant" and plain(messages[-1]) == "Output stopped.")

    @filter.on_llm_tool_respond()
    async def observation(self, event: AstrMessageEvent, tool, tool_args: dict | None, tool_result):
        bridge = self._route(event)
        if bridge is None or tool_result is None or self.config.get("record_observations", True) is not True:
            return
        try:
            # Inspect public text blocks only. Parameters, tool identities,
            # private reasoning and raw provider completions are not a diary.
            content = getattr(tool_result, "content", None)
            if not isinstance(content, list):
                return
            texts = [part.text for part in content
                     if getattr(part, "type", None) == "text" and isinstance(getattr(part, "text", None), str)]
            if not texts:
                return
            await asyncio.to_thread(bridge.stage_observation, event.unified_msg_origin,
                self._message_id(event), "\n".join(texts), stage="observed_result",
                failed=getattr(tool_result, "isError", False) is True, **self._origin(event))
        except Exception:
            self._warn("observed_result")

    @filter.after_message_sent()
    async def send_stage(self, event: AstrMessageEvent):
        bridge = self._route(event)
        if bridge is None:
            return
        try:
            await asyncio.to_thread(bridge.note_host_send_stage, event.unified_msg_origin, self._message_id(event))
        except Exception:
            self._warn("send_stage")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command('lovehouse_status')
    async def source_status(self, event: AstrMessageEvent):
        if self.config.get('enabled', False) is not True:
            yield event.plain_result('爱之屋来源适配未启用；没有自动采集。')
            return
        bridge = self._route(event)
        if bridge is None:
            yield event.plain_result('当前来源没有有效绑定；不会采集这段对话。')
            return
        try:
            state = await asyncio.to_thread(bridge.status)
            sdk = await asyncio.to_thread(bridge.client.status)
            yield event.plain_result(f"爱之屋来源已配置（不代表全部活动覆盖）。等待最终回复 {state['awaiting_final']} 条；插件待交 {state['pending']} 条；来源待补交 {sdk.get('pending', 0)} 条。最终生成与宿主发送阶段分别记录，未提供 QQ 已读证明。")
        except Exception:
            yield event.plain_result('爱之屋状态暂不可读取；不表示队列为空。聊天不受影响。')
