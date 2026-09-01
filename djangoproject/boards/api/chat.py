import json

from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.renderers import BaseRenderer
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from djangoproject.boards.llm import ChatNotConfigured
from djangoproject.boards.llm import run_board_chat_stream
from djangoproject.boards.models import ChatMessage
from djangoproject.boards.models import ChatThread
from djangoproject.boards.models import Project

HISTORY_LIMIT = 24


class HistoryItemSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("human", "ai"))
    content = serializers.CharField()


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField()
    history = HistoryItemSerializer(many=True, required=False, default=list)
    project_id = serializers.IntegerField(required=False, allow_null=True)


def _project_for(user, project_id: int | None) -> Project | None:
    if project_id is None:
        return None
    return Project.objects.filter(
        pk=project_id,
        workspace__members=user,
    ).first()


def _project_brief(user, project_id: int | None) -> str:
    project = _project_for(user, project_id)
    if project_id is None:
        return (
            "No project is open. You can still talk, but tools that "
            "read or change cards will refuse until a board is open."
        )
    if project is None:
        return "That project is not available to this user."
    return (
        f"Open project: {project.name} (id={project.pk}) "
        f"in workspace {project.workspace.name}."
    )


def _get_thread(user, project: Project | None) -> ChatThread:
    thread, _created = ChatThread.objects.get_or_create(
        user=user,
        project=project,
    )
    return thread


def _thread_history(thread: ChatThread) -> list[dict]:
    rows = list(thread.messages.order_by("created_at"))[-HISTORY_LIMIT:]
    return [{"role": row.role, "content": row.content} for row in rows]


def _save_turn(thread: ChatThread, human: str, assistant: str) -> None:
    ChatMessage.objects.create(
        thread=thread,
        role=ChatMessage.Role.HUMAN,
        content=human,
    )
    if assistant.strip():
        ChatMessage.objects.create(
            thread=thread,
            role=ChatMessage.Role.AI,
            content=assistant,
        )
    thread.save(update_fields=["updated_at"])


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


_STREAM_END = object()


class EventStreamRenderer(BaseRenderer):
    """DRF must know this media type or Accept: text/event-stream is 406.

    Content negotiation runs *before* post(). Without a matching renderer
    the view never runs — that is the 'Could not satisfy the request Accept
    header' error.
    """

    media_type = "text/event-stream"
    format = "txt"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""
        if isinstance(data, bytes | bytearray):
            return bytes(data)
        if isinstance(data, str):
            return data.encode()
        return json.dumps(data).encode()


class ChatView(APIView):
    """POST /api/chat/ — authenticated. Streams LangGraph tokens as SSE.

    GET  /api/chat/?project_id= — last persisted turns for this board.
    """

    renderer_classes = [EventStreamRenderer, JSONRenderer]

    def get_renderers(self):
        if self.request.method == "GET":
            return [JSONRenderer()]
        return super().get_renderers()

    def perform_content_negotiation(self, request, force=False):  # noqa: FBT002
        # Never 406 this view: the client streams SSE, errors stay JSON.
        return super().perform_content_negotiation(request, force=True)

    def get(self, request):
        raw_id = request.query_params.get("project_id")
        project_id = int(raw_id) if raw_id else None
        project = _project_for(request.user, project_id)
        thread = _get_thread(request.user, project)
        return Response({"messages": _thread_history(thread)})

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project_id = data.get("project_id")
        project = _project_for(request.user, project_id)
        thread = _get_thread(request.user, project)
        saved = _thread_history(thread)
        history = saved or (data.get("history") or [])
        user_message = data["message"]
        brief = _project_brief(request.user, project_id)
        stream = run_board_chat_stream(
            user=request.user,
            user_message=user_message,
            history=history,
            project_brief=brief,
            project_id=project_id,
        )

        def _next_event():
            return next(stream, _STREAM_END)

        pull = sync_to_async(_next_event)

        async def event_stream():
            # Async iterator is required. Django ASGI otherwise does
            # list(sync_generator) and the browser only sees the reply at the end.
            yield _sse({"type": "status", "text": "Working…"})
            assistant = ""
            try:
                while True:
                    event = await pull()
                    if event is _STREAM_END:
                        break
                    if event["type"] == "token":
                        assistant += str(event.get("text") or "")
                    elif event["type"] == "done":
                        assistant = str(event["reply"]["message"])
                        await sync_to_async(_save_turn)(thread, user_message, assistant)
                    yield _sse(event)
            except ChatNotConfigured as exc:
                yield _sse({"type": "error", "detail": str(exc)})

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
