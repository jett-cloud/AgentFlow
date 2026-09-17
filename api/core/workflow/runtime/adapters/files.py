"""files."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, override

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.app.entities.app_invoke_entities import DifyRunContext
from core.app.file_access import (
    DatabaseFileAccessController,
    grant_upload_file_access,
    is_retriever_segment_access_granted,
)
from core.tools.tool_file_manager import ToolFileManager
from core.workflow.runtime.adapters.file_reference import build_file_reference
from extensions.ext_database import db
from factories import file_factory
from graphon.file import File, FileTransferMethod, FileType
from graphon.nodes.llm.runtime_protocols import (
    RetrieverAttachmentLoaderProtocol,
)
from graphon.nodes.protocols import FileReferenceFactoryProtocol, HttpClientProtocol, ToolFileManagerProtocol
from models.dataset import SegmentAttachmentBinding
from models.model import UploadFile

if TYPE_CHECKING:
    from graphon.nodes.llm.file_saver import LLMFileSaver

from core.workflow.runtime.adapters.context import resolve_dify_run_context

_file_access_controller = DatabaseFileAccessController()


class DifyFileReferenceFactory(FileReferenceFactoryProtocol):
    def __init__(self, run_context: Mapping[str, Any] | DifyRunContext) -> None:
        self._run_context = resolve_dify_run_context(run_context)

    @override
    def build_from_mapping(self, *, mapping: Mapping[str, Any]):
        return file_factory.build_from_mapping(
            mapping=mapping,
            tenant_id=self._run_context.tenant_id,
            access_controller=_file_access_controller,
        )


class DifyRetrieverAttachmentLoader(RetrieverAttachmentLoaderProtocol):
    """Resolve retriever attachments through Dify persistence and return graph file references."""

    _segment_access_checker: Callable[[str], bool] | None

    def __init__(
        self,
        *,
        file_reference_factory: FileReferenceFactoryProtocol,
        segment_access_checker: Callable[[str], bool] | None = None,
    ) -> None:
        self._file_reference_factory = file_reference_factory
        self._segment_access_checker = segment_access_checker

    @override
    def load(self, *, segment_id: str) -> Sequence[File]:
        if not is_retriever_segment_access_granted(segment_id):
            return []
        if self._segment_access_checker is not None and not self._segment_access_checker(segment_id):
            return []

        with Session(db.engine, expire_on_commit=False) as session:
            attachments_with_bindings = session.execute(
                select(SegmentAttachmentBinding, UploadFile)
                .join(UploadFile, UploadFile.id == SegmentAttachmentBinding.attachment_id)
                .where(SegmentAttachmentBinding.segment_id == segment_id)
            ).all()

        grant_upload_file_access(str(upload_file.id) for _, upload_file in attachments_with_bindings)
        return [
            self._file_reference_factory.build_from_mapping(
                mapping={
                    "id": upload_file.id,
                    "filename": upload_file.name,
                    "extension": "." + upload_file.extension,
                    "mime_type": upload_file.mime_type,
                    "type": FileType.IMAGE,
                    "transfer_method": FileTransferMethod.LOCAL_FILE,
                    "remote_url": upload_file.source_url,
                    "reference": build_file_reference(record_id=str(upload_file.id)),
                    "size": upload_file.size,
                }
            )
            for _, upload_file in attachments_with_bindings
        ]


class DifyToolFileManager(ToolFileManagerProtocol):
    """Workflow adapter that resolves conversation scope outside `graphon`."""

    _conversation_id_getter: Callable[[], str | None] | None

    def __init__(
        self,
        run_context: Mapping[str, Any] | DifyRunContext,
        *,
        conversation_id_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self._run_context = resolve_dify_run_context(run_context)
        self._manager = ToolFileManager()
        self._conversation_id_getter = conversation_id_getter

    @override
    def create_file_by_raw(
        self,
        *,
        file_binary: bytes,
        mimetype: str,
        filename: str | None = None,
    ) -> Any:
        conversation_id = self._conversation_id_getter() if self._conversation_id_getter is not None else None
        return self._manager.create_file_by_raw(
            user_id=self._run_context.user_id,
            tenant_id=self._run_context.tenant_id,
            conversation_id=conversation_id,
            file_binary=file_binary,
            mimetype=mimetype,
            filename=filename,
        )

    @override
    def get_file_generator_by_tool_file_id(self, tool_file_id: str):
        return self._manager.get_file_generator_by_tool_file_id(tool_file_id)


def build_dify_llm_file_saver(
    *,
    run_context: Mapping[str, Any] | DifyRunContext,
    http_client: HttpClientProtocol,
    conversation_id_getter: Callable[[], str | None] | None = None,
) -> LLMFileSaver:
    from graphon.nodes.llm.file_saver import FileSaverImpl

    return FileSaverImpl(
        tool_file_manager=DifyToolFileManager(run_context, conversation_id_getter=conversation_id_getter),
        file_reference_factory=DifyFileReferenceFactory(run_context),
        http_client=http_client,
    )
