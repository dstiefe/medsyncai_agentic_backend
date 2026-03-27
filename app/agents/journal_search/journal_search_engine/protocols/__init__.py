"""
Extraction Protocols (P1-P8) for non-CMI intent handling.

These handle direct database lookups where the user asks about a specific
trial by name, a definition, or a guideline — bypassing the CMI pipeline.
"""

from .protocol_router import route_protocol

__all__ = ["route_protocol"]
