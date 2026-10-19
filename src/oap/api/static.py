"""Static serving of the built web app with a single-page-app fallback."""

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SPAStaticFiles(StaticFiles):
    """Serve ``index.html`` for any unknown path that is not under ``api/``.

    The web app routes on the client (``/landscape``, ``/spreads``), so a deep link must
    return the app shell. A missing file under ``api/`` stays a 404.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Return the file at ``path``, or the app shell for an unknown client route.

        Args:
            path: Path relative to the mount, without a leading slash.
            scope: The ASGI scope of the request.

        Returns:
            The static file, or ``index.html`` when the path is not a file and is not
            under ``api/``.

        Raises:
            HTTPException: 404 when the path is under ``api/`` or ``index.html`` is missing.
        """
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path == "api" or path.startswith("api/"):
                raise
            return await super().get_response("index.html", scope)
