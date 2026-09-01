import json

from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.renderers import BaseRenderer
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView

from djangoproject.boards.llm import ChatNotConfigured
from djangoproject.boards.llm import run_board_chat_stream
from djangoproject.boards.models import Project
from djangoproject.boards.models import Task


class HistoryItemSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("human", "ai"))
    content = serializers.CharField()


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField()
    history = HistoryItemSerializer(many=True, required=False, default=list)
    project_id = serializers.IntegerField(required=False, allow_null=True)


def _board_context_for(user, project_id: int | None) -> str:
    if project_id is None:
        return ""
    project = Project.objects.filter(
        pk=project_id,
        workspace__members=user,
    ).first()
    if project is None:
        return ""
    lines = [f"Project: {project.name} (id={project.pk})"]
    tasks = Task.objects.filter(project=project).order_by("status", "id")
    if not tasks:
        lines.append("No tasks yet.")
        return "\n".join(lines)
    lines.extend(
        f"- #{task.pk} [{task.status}] ({task.priority}) {task.title}"
        + (f" @{task.assignee.email}" if task.assignee_id else "")
        + (f" due {task.due_date.isoformat()}" if task.due_date else "")
        for task in tasks.select_related("assignee")
    )
    return "\n".join(lines)


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


_STREAM_END = object()


class EventStreamRenderer(BaseRenderer):
    """DRF must know this media type or Accept: text/event-stream is 406.

    Content negotiation runs *before* post(). Without a matching renderer
    the view never runs — that is the 'Could not satisfy the request
    Accept header' error.
    """

    media_type = "text/event-stream"
    format = "txt"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):  # noqa: ARG002
        if data is None:
            return b""
        if isinstance(data, bytes | bytearray):
            return bytes(data)
        if isinstance(data, str):
            return data.encode()
        return json.dumps(data).encode()


class ChatView(APIView):
    """POST /api/chat/ — authenticated. Streams LangChain tokens as SSE."""

    renderer_classes = [EventStreamRenderer, JSONRenderer]

    def perform_content_negotiation(self, request, force=False):  # noqa: FBT001, FBT002
        # Never 406 this view: the client streams SSE, errors stay JSON.
        return super().perform_content_negotiation(request, force=True)

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = _board_context_for(request.user, data.get("project_id"))
        stream = run_board_chat_stream(
            user=request.user,
            user_message=data["message"],
            history=data.get("history") or [],
            board_context=context,
            project_id=data.get("project_id"),
        )

        def _next_event():
            return next(stream, _STREAM_END)

        pull = sync_to_async(_next_event)

        async def event_stream():
            # Async iterator is required. Django ASGI otherwise does
            # list(sync_generator) and the browser only sees the reply at the end.
            yield _sse({"type": "status", "text": "Working…"})
            try:
                while True:
                    event = await pull()
                    if event is _STREAM_END:
                        break
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
