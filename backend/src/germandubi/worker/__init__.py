"""The processing worker: a separate process that performs the expensive stages.

Keeping heavy media and ML work out of the API process is the one deliberate process
boundary in this architecture. It keeps the browser responsive during a long run, makes
cancellation and GPU lifetime tractable, and means a worker crash does not take the UI with
it (ADR-0002).
"""
