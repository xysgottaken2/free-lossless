"""Neural enhancement stage for Free Lossless.

Public surface:

* :class:`NeuralRenderer`, :class:`DisabledRenderer`, :class:`RendererStatus`
* :class:`DLSS5Renderer` - optional DLSS 5 Neural Rendering backend
* :func:`create_renderer` - factory used by the pipeline
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .base import (  # noqa: F401
    DisabledRenderer,
    NeuralRenderer,
    RendererStatus,
    STATE_DISABLED,
    STATE_ERROR,
    STATE_READY,
    STATE_UNAVAILABLE,
)
from .log import log_dlss5, log_pipeline, log_rife  # noqa: F401
from .runtime import RuntimeLocator  # noqa: F401


def create_renderer(
    options: Optional[Dict[str, Any]] = None,
    native_dir: Optional[str] = None,
    expected_size: Optional[Tuple[int, int]] = None,
    locator: Optional[RuntimeLocator] = None,
    bridge_loader=None,
    initialize: bool = True,
) -> NeuralRenderer:
    """Build the configured renderer.

    * ``dlss5.enabled`` false -> :class:`DisabledRenderer` (the NVIDIA runtime
      is never loaded).
    * ``dlss5.enabled`` true -> :class:`DLSS5Renderer`.  If probing the runtime
      fails, the renderer stays soft-disabled (pass-through) and the pipeline
      continues RIFE-only.
    """
    options = dict(options or {})
    if not options.get("enabled", False):
        return DisabledRenderer("disabled by configuration")

    from .dlss5 import DLSS5Renderer  # deferred: keeps import surface small

    renderer = DLSS5Renderer(
        options=options,
        native_dir=native_dir,
        locator=locator,
        bridge_loader=bridge_loader,
        expected_size=expected_size,
    )
    if initialize:
        renderer.initialize()
    return renderer
