# src/ui/library_analysis/task_coordinator.py
"""Operation-scoped background task coordination for Library Analysis."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

MainThreadDispatcher = Callable[[Callable[[], None]], None]


@dataclass(frozen=True)
class TaskOperation:
    """Immutable identity and cancellation handle for one background task."""

    operation_id: int
    cancellation_event: threading.Event

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation was requested for this operation."""
        return self.cancellation_event.is_set()


class TaskCoordinator:
    """Run one task at a time and reject callbacks from superseded operations."""

    def __init__(
        self,
        dispatch_on_main: MainThreadDispatcher,
        is_target_active: Callable[[], bool],
    ) -> None:
        self._dispatch_on_main = dispatch_on_main
        self._is_target_active = is_target_active
        self._lock = threading.Lock()
        self._next_operation_id = 0
        self._active_operation: Optional[TaskOperation] = None
        self._thread: Optional[threading.Thread] = None
        self._local = threading.local()

    @property
    def active_operation(self) -> Optional[TaskOperation]:
        """Return the active operation, if any."""
        with self._lock:
            return self._active_operation

    @property
    def current_operation(self) -> Optional[TaskOperation]:
        """Return the operation associated with the calling worker thread."""
        operation = getattr(self._local, "operation", None)
        return operation if isinstance(operation, TaskOperation) else None

    @property
    def thread(self) -> Optional[threading.Thread]:
        """Return the most recently started worker thread."""
        with self._lock:
            return self._thread

    @property
    def is_busy(self) -> bool:
        """Return whether a non-cancelled operation still owns the coordinator."""
        return self.active_operation is not None

    def start(
        self,
        worker: Callable[[], None],
    ) -> TaskOperation:
        """Start ``worker`` under a new immutable operation identity."""
        with self._lock:
            if self._active_operation is not None:
                raise RuntimeError("A Library Analysis task is already active.")
            self._next_operation_id += 1
            operation = TaskOperation(self._next_operation_id, threading.Event())
            self._active_operation = operation

        def run() -> None:
            self._local.operation = operation
            try:
                worker()
            finally:
                self._local.operation = None

        thread = threading.Thread(target=run, daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()
        return operation

    def cancel_active(self) -> Optional[TaskOperation]:
        """Cancel and invalidate the active operation immediately."""
        with self._lock:
            operation = self._active_operation
            if operation is None:
                return None
            operation.cancellation_event.set()
            self._active_operation = None
            return operation

    def clear_finished_thread(self) -> None:
        """Release the worker reference after its thread has stopped."""
        with self._lock:
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None

    def raise_if_cancelled(self, exception_type: type[Exception]) -> None:
        """Raise ``exception_type`` when the calling operation was cancelled."""
        operation = self.current_operation or self.active_operation
        if operation is not None and operation.is_cancelled:
            raise exception_type()

    def dispatch_current(
        self,
        callback: Callable[..., None],
        *args: object,
        complete: bool = False,
    ) -> bool:
        """Dispatch for the calling task, rejecting calls outside a task."""
        operation = self.current_operation
        if operation is None:
            return False
        return self.dispatch(operation, callback, *args, complete=complete)

    def dispatch(
        self,
        operation: TaskOperation,
        callback: Callable[..., None],
        *args: object,
        complete: bool = False,
    ) -> bool:
        """Queue a callback that runs only while ``operation`` remains active."""

        def invoke() -> None:
            if not self._accepts(operation):
                return
            if complete:
                self._complete(operation)
            callback(*args)

        if not self._accepts(operation):
            return False
        self._dispatch_on_main(invoke)
        return True

    def dispatch_unbound(self, callback: Callable[..., None], *args: object) -> None:
        """Queue a lifecycle callback not associated with a background task."""

        def invoke() -> None:
            if self._is_target_active():
                callback(*args)

        self._dispatch_on_main(invoke)

    def _accepts(self, operation: TaskOperation) -> bool:
        with self._lock:
            is_current = self._active_operation is operation
        return is_current and not operation.is_cancelled and self._is_target_active()

    def _complete(self, operation: TaskOperation) -> None:
        with self._lock:
            if self._active_operation is operation:
                self._active_operation = None
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None
