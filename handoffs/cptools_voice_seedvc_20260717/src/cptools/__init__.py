"""CPtools voice compatibility package.

This handoff keeps the standalone ``ai_voice`` package as the primary
implementation, while also exposing the historical ``cptools.voice`` import
path so the existing app can start without a larger refactor.
"""

