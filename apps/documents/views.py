from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

from .services import DocumentDownloadError, prepare_document_download


@login_required
@require_GET
def document_download(request, document_id):
    try:
        prepared = prepare_document_download(
            actor=request.user,
            document_id=document_id,
            http_request=request,
        )
    except DocumentDownloadError as exc:
        raise Http404("文件不存在或当前不可下载。") from exc
    response = FileResponse(
        prepared.file,
        as_attachment=True,
        filename=prepared.filename,
        content_type=prepared.content_type,
    )
    response["Content-Length"] = prepared.file_size
    return response
