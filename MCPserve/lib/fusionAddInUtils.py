"""
Fusion 360 Add-In Utilities

Provides helper functions for Fusion 360 add-in development,
including error handling and event handler management.
"""

import traceback

try:
    import adsk.core
    app = adsk.core.Application.get()
    ui = app.userInterface
except:
    app = None
    ui = None

_handlers = []


def add_handler(handler):
    """Add an event handler to the global list to prevent garbage collection."""
    _handlers.append(handler)


def clear_handlers():
    """Clear all stored event handlers."""
    _handlers.clear()


def handle_error(name: str, show_message_box: bool = True):
    """Handle an error, optionally showing a message box in Fusion 360."""
    error_msg = f"Error in {name}:\n{traceback.format_exc()}"
    print(error_msg)
    if show_message_box and ui:
        try:
            ui.messageBox(error_msg)
        except:
            pass
